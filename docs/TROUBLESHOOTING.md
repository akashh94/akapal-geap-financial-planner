# Troubleshooting — Errors Encountered & Resolved (First Principles)

A first-principles log of every error hit and fixed while getting the
**Financial Planner** and **GEAP Supervisor** deployed on Vertex AI Agent
Engine and talking to each other over A2A.

The guiding principle for each entry:

> **Observe** the exact failure → **locate** the layer that failed (wire,
> platform, IAM, code) → **reason** from how that layer actually works →
> **verify** the fix end-to-end before moving on.

---

## 1. `mcp` 2.0.0 broke `McpToolset` import (planner, pre-deploy)

**Symptom**
```python
import app.agent
# ImportError: cannot import name 'McpToolset' from 'google.adk.tools.mcp_tool'
```

**Layer:** Dependency resolution (local environment).

**Reasoning (first principles)**
- `McpToolset` is imported unconditionally at module load in
  `app/agents/financial_planner_agent.py` — so the agent can't even import.
- ADK 2.6.2 requires `mcp>=1.24,<2` (verified via `importlib.metadata.requires('google-adk')`),
  and its `mcp_toolset.py` does `from mcp.shared.session import ProgressFnT`.
- The planner's `uv.lock` had **`mcp 2.0.0`** — a major bump that removed
  `mcp.shared.session`. `pyproject.toml` declared bare `mcp` (no bound), so the
  resolver allowed 2.x.

**Resolution**
- Pinned `mcp>=1.24,<2` in `pyproject.toml`.
- `uv lock` downgraded `mcp 2.0.0 → 1.29.0`; `uv sync` reinstalled.
- Verified: `app.agent` and `app.fast_api_app` import cleanly.

**Lesson:** always bound major versions that ADK itself bounds; verify with an
import smoke test, not just `pip install`.

---

## 2. Deploy payload exceeded the 8 MB limit

**Symptom**
```
400 INVALID_ARGUMENT: Request payload size exceeds the limit: 8388608 bytes.
```
(this surfaced only after a ~15-minute silent hang — the deploy was retrying)

**Layer:** Deployment packaging (agents-cli → Agent Engine).

**Reasoning (first principles)**
- agents-cli packages the source tree for upload, honoring `.gitignore`
  (via `pathspec`, `_packaged_files()` in `deploy/agent_runtime.py`).
- The planner's `.gitignore` **did not exclude `.venv/`, `*.egg-info/`,
  `.commandcode/`, or `docs/`** — so the 420 MB `.venv` got bundled.
- Reproduced the packaging locally (same `pathspec` logic): **341 MB** packaged.

**Resolution**
- Fixed `.gitignore` to exclude `.venv/`, `venv/`, `env/`, `*.egg-info/`,
  `.commandcode/`, `.env.*`.
- Re-ran the packaging check: **0.7 MB**.
- Redeployed successfully.

**Lesson:** check the deploy payload locally before a real deploy; a hang that
starts after "Creating agent" is often a retrying oversized upload.

---

## 3. Dockerfile `CMD` exec-form broke the container boot

**Symptom** (in Cloud Logging, `reasoning_engine_stderr`)
```
Error: Invalid value for '--port': '${PORT:-8080}' is not a valid integer.
```

**Layer:** Container startup.

**Reasoning (first principles)**
- Dockerfile used **exec form**: `CMD ["uvicorn", ..., "--port", "${PORT:-8080}"]`.
- Exec form does **not** invoke a shell, so `${PORT:-8080}` is passed to uvicorn
  literally. Local `docker run` (which can inject PORT) masked this; Agent
  Runtime doesn't expand it either.

**Resolution**
- Switched to **shell form**: `CMD uvicorn app.fast_api_app:app --host 0.0.0.0 --port "${PORT:-8080}"`.
- Redeployed; container started (`Uvicorn running on http://0.0.0.0:8080`,
  `Application startup complete`).
- (The supervisor's Dockerfile hardcodes `8080` — no bug there.)

**Lesson:** exec-form CMD never expands env vars; if you need `${VAR:-default}`
in CMD, use shell form.

---

## 4. Wrong assumption: "Agent Runtime exposes A2A only over gRPC"

**Symptom** — no direct failure, but research produced an incorrect mental model
that had to be corrected:

- Google docs say A2A agents expose `on_message_send` /
  `handle_authenticated_agent_card` and "Agent Runtime does not serve the public
  agent card".
- `agents-cli run --mode a2a --url <engine>` failed with **404** fetching the
  card at `.../api/a2a/app/.well-known/agent-card.json`.

**Layer:** Platform behavior / discovery.

**Reasoning (first principles)**
- Docs describe the **`A2aAgent` template** path (a different deployment shape).
- Your deployment is the **ADK FastAPI container** path. The container serves
  A2A at its own `rpc_path` (`/a2a/financial_planner`).
- The passthrough path is `.../api/a2a/<agent_directory>/...` where
  `<agent_directory>` is the **manifest value `app`** — but the route *under* it
  is the container's **`rpc_path` (`financial_planner`)**, not `app`.
- Probing `.../api/a2a/financial_planner/.well-known/agent-card.json` returned
  **200** — the card was live all along; the 404 was the wrong path.

**Resolution**
- No code change — corrected the URL to
  `.../api/a2a/financial_planner/.well-known/agent-card.json`.
- Verified the full message send (`SendMessage`, `ROLE_USER`, `messageId`)
  through the passthrough.

**Lesson:** the passthrough path = `api/a2a/<rpc_path>`, not
`api/a2a/<agent_directory>`. Distinguish "the card is unreachable" from "I'm
probing the wrong path" by testing adjacent paths.

---

## 5. The agent card advertises an internal, non-routable URL

**Symptom**
```
HTTP Error 401: ... for url 'http://reasoning-engine-<id>-<hash>-<region>.a.run.app/a2a/financial_planner'
```
(auth failure because the client used the card's advertised URL verbatim)

**Layer:** Discovery / client.

**Reasoning (first principles)**
- The card's `supportedInterfaces[].url` is built from `APP_URL`, which
  defaults to the container's **internal** host (agents-cli sets it to
  `.../api` only on *update*).
- That internal `http://reasoning-engine-...run.app` is not reachable from
  outside the platform.
- The public, reachable endpoint is the passthrough base
  (`https://<loc>-aiplatform.googleapis.com/reasoningEngines/v1/{resource}/api/a2a/financial_planner`).

**Resolution**
- The supervisor's `call_financial_planner` tool **rewrites** every
  `supported_interfaces[].url` to the passthrough base after fetching the card.
- Verified: send succeeds through the rewritten URL.

**Lesson:** treat the card's URL as a hint, not gospel; behind proxies you must
rebind it to the public base the client can actually reach.

---

## 6. `SendMessage` rejects `role: "user"` — needs protobuf enum `ROLE_USER`

**Symptom**
```
Invalid enum value user for enum type lf.a2a.v1.Role at SendMessageRequest.message.role
```

**Layer:** A2A wire format.

**Reasoning (first principles)**
- The platform's `SendMessage` is served from the A2A **protobuf** schema
  (`a2a_pb2`), where `role` is an enum: `ROLE_USER`, not the JSON string
  `user`.
- Also required: `message_id` on the message (next validation error once the
  role was fixed).

**Resolution**
- Use the a2a-sdk types (`Message(message_id=..., role=Role.ROLE_USER,
  parts=[Part(text=...)])`), which serialize to the correct protobuf fields.
- Verified a full task lifecycle (SUBMITTED → artifact → COMPLETED).

**Lesson:** when a JSON-RPC endpoint is protobuf-backed, string-enum values
differ from the JSON spec. Let the SDK's typed messages build the payload.

---

## 7. Supervisor tool failed in production: `403 Forbidden` on the planner card

**Symptom**
- Locally the tool worked; deployed, the supervisor returned "financial planner
  unavailable".
- Added logging to the tool's exception path →
  `call_financial_planner failed: Client error '403 Forbidden' .../api/a2a/financial_planner/.well-known/agent-card.json`

**Layer:** IAM / identity.

**Reasoning (first principles)**
- The tool authenticates with `google.auth.default()` — inside the deployed
  container that resolves to the **Agent Runtime service agent**
  (`service-947331501288@gcp-sa-aiplatform-re.iam.gserviceaccount.com`).
- That SA had only service-agent roles; it was **not** authorized to invoke the
  planner's engine (the passthrough checks the caller's IAM on the planner's
  reasoning engine).
- The first fix attempt — `roles/aiplatform.user` at project level — needed
  propagation, and the earlier e2e still 403'd during the window.
- Note: `roles/aiplatform.reasoningEngineUser` is **not supported** on the
  reasoning engine resource (`400 Role ... is not supported for this resource`).

**Resolution**
- Granted `roles/aiplatform.user` to
  `service-947331501288@gcp-sa-aiplatform-re.iam.gserviceaccount.com` on the
  project.
- After IAM propagation, the end-to-end flow succeeded: supervisor LLM →
  tool → planner passthrough → planner answer.

**Lesson:** container ADC ≠ your local user. Check which identity the deployed
container uses and grant it IAM on the *target* engine. Add logging to
exception paths so production failures are visible in Cloud Logging.

---

## 8. Trailing whitespace in an env var produced a confusing `%20` 404

**Symptom**
```
Client error '404 Not Found' for url '...agent-card.json%20'
```
(the `%20` is a literal space in the URL)

**Layer:** Configuration hygiene / client robustness.

**Reasoning (first principles)**
- An env var with a trailing space (shell quoting, sourced file, editor) flows
  straight into the URL.
- httpx percent-encodes it as `%20`, hitting the wrong path → 404.

**Resolution**
- `_planner_card_url()` now calls `.strip()` on the env var before use.
- Also added `logging.warning(..., exc_info=True)` to the tool's exception
  handler so real errors are never hidden.

**Lesson:** treat env-var URLs as untrusted input; strip before using, and
always surface real exceptions in logs instead of swallowing them.

---

## 9. Tool executed end-to-end but returned no text (wrong chunk fields)

**Symptom** — during early testing, the tool sometimes returned
"The financial planner returned no answer." despite a completed task.

**Layer:** a2a-sdk response handling.

**Reasoning (first principles)**
- `send_message()` yields a stream of protobuf chunks. The answer text lives in
  either `chunk.artifact_update.artifact.parts` (new executor) or
  `chunk.task.history[*].parts` (aggregated task).
- Reading only one of these misses the text on the other path.

**Resolution**
- The tool collects text from **both** `artifact_update` and `task.history`,
  skipping the user's own echoed message by role.

**Lesson:** with streaming A2A, the final text can arrive via different chunk
shapes depending on executor version — collect from all of them.

---

## Quick map: error → fix

| Error / symptom | Root cause | Fix | Where |
|---|---|---|---|
| `cannot import name 'McpToolset'` | `mcp 2.0.0` incompatible with ADK 2.6.2 | pin `mcp>=1.24,<2`, re-lock | planner `pyproject.toml` |
| `payload size exceeds ... 8388608` | `.venv` (341 MB) packaged | `.gitignore` excludes `.venv/` etc. | planner `.gitignore` |
| `'${PORT:-8080}' is not a valid integer` | exec-form CMD doesn't expand vars | shell-form CMD | planner `Dockerfile` |
| A2A card 404 at `api/a2a/app` | wrong passthrough path | use `api/a2a/financial_planner` | — (URL) |
| `401` on card's advertised URL | card advertises internal host | rewrite URL to passthrough base | supervisor tool |
| `Invalid enum value user` / `message_id required` | protobuf-backed JSON-RPC | a2a-sdk typed `Message`/`Role.ROLE_USER` | supervisor tool |
| `403 Forbidden` on planner passthrough | supervisor SA lacks IAM on planner | `roles/aiplatform.user` on SA | GCP IAM |
| `404 ...agent-card.json%20` | trailing space in env var | `.strip()` the URL | supervisor tool |
| tool returned "no answer" | text in `artifact_update` vs `task.history` | collect from both | supervisor tool |

---

## What was *verified working* (so docs reflect reality)

1. Planner agent imports and FastAPI app boots on Agent Runtime.
2. Planner's A2A card is live at the passthrough (`.../api/a2a/financial_planner/.well-known/agent-card.json`).
3. Full A2A message round-trip to the planner returns a real LLM answer.
4. Supervisor deployed with the a2a-sdk tool + `FINANCIAL_PLANNER_URL`.
5. **End-to-end**: question → supervisor passthrough → `call_financial_planner`
   → planner passthrough → planner answer → back to the user.
