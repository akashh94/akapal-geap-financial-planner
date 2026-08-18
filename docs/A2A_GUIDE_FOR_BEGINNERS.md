# A2A from First Principles — A Beginner's Guide

A walkthrough of how the **GEAP supervisor** (`geap_agent`) talks to the
**Financial Planner** (this repo) using the **A2A (Agent2Agent)** protocol.
Read this before the [A2A_ARCHITECTURE.md](./A2A_ARCHITECTURE.md) deep dive.

---

## 1. What is A2A, really?

A2A is Google's open protocol for letting **one agent call another agent as if
it were a service**. Think of it as "HTTP + JSON for agents".

- **Transport** — plain HTTPS POST requests with JSON bodies. No special
  networking; works across clouds and companies.
- **Message format** — **JSON-RPC 2.0**, the same style of protocol as calling
  a remote function (`SendMessage`, `GetTask`, `CancelTask`).
- **Discovery** — every A2A agent publishes an **agent card**: a JSON file that
  works like an API's OpenAPI spec. It says "here's my name, here's my JSON-RPC
  endpoint URL, here's what I can do" (its *skills*).
- **Unit of work** — a **task**. Each message you send becomes a task with an
  id, a status (`working` → `completed` / `failed`), and a stream of events.

> Nothing more magical than that: find another agent's card, send it a
> message over HTTP, get an answer back.

---

## 2. The two roles in this system

```mermaid
flowchart LR
    subgraph ClientSide["Supervisor side (geap_agent)"]
        LLM["Supervisor LLM (orchestrator)"]
        Sub["financial_planner sub-agent<br/>(RemoteA2aAgent)"]
        Cli["ADK RemoteA2aAgent client<br/>(Bearer auth)"]
    end
    subgraph Wire["A2A wire (HTTPS + JSON-RPC)"]
        Card["GET agent-card.json<br/>discovery"]
        RPC["POST .../v1beta1/.../a2a<br/>SendMessage"]
    end
    subgraph ServerSide["Planner side (this repo)"]
        A2a["A2aAgent (Agent Engine)<br/>on_message_send"]
        Exec["A2aAgentExecutor"]
        PlannerAgent["Financial planner LlmAgent<br/>Gemini + calculator tools + MCP"]
    end

    LLM -->|"decides: planning question"| Sub
    Sub -->|"builds A2A client"| Cli
    Cli --> Card
    Card --> RPC
    RPC --> A2a
    A2a --> Exec
    Exec --> PlannerAgent
```

**Client side — the supervisor (`geap_agent`)**

- Exposes a `financial_planner` sub-agent — an ADK **`RemoteA2aAgent`**.
- Inside, ADK's built-in A2A client talks A2A directly (no custom tool code).
- Authenticates with a **Google Bearer token** from the ambient credentials
  (`google.auth.default()`), which the Agent Engine passthrough requires.
- Knows where the planner lives via `FINANCIAL_PLANNER_URL`, which points at
  the planner's agent-card URL on the Agent Engine passthrough
  (`.../reasoningEngines/<id>/a2a/.well-known/agent-card.json`).

**Server side — the planner (this repo)**

- Deployed to **Agent Engine as an `A2aAgent`** (Model B) via
  `app/deploy_a2a.py` — the platform serves the A2A protocol natively.
- Exposes the A2A endpoints through the platform's passthrough:

| Endpoint | Method | Purpose |
|---|---|---|
| `.../a2a/.well-known/agent-card.json` | GET | The agent card (discovery) |
| `.../a2a` | POST | The JSON-RPC endpoint (needs an `A2A-Version: 1.0` header) |

- Internally bridges incoming A2A calls to ADK's `Runner` via
  `A2aAgentExecutor`, which runs the actual `financial_planner` `LlmAgent`
  (Gemini + 6 calculator tools + MCP portfolio tools).

---

## 3. The flow, end to end

Example: the user asks the chat *"Can I retire in 10 years if I save $1,000/month?"*

```mermaid
sequenceDiagram
    autonumber
    actor User
    participant Sup as Supervisor LLM
    participant Sub as financial_planner sub-agent<br/>(RemoteA2aAgent)
    participant Cli as ADK A2A client
    participant Card as Planner agent-card (passthrough)
    participant API as Planner A2aAgent (Agent Engine)
    participant Exec as A2aAgentExecutor
    participant Agent as Planner LlmAgent + tools

    User->>Sup: "Can I retire in 10 years if I save $1,000/mo?"
    Sup->>Sup: prompt routes planning questions to the sub-agent
    Sup->>Sub: financial_planner(request)

    Sub->>Cli: build authenticated A2A client
    Cli->>Card: GET .../.well-known/agent-card.json
    Card-->>Cli: name, skills, capabilities
    Cli->>API: JSON-RPC SendMessage (A2A-Version: 1.0)
    API->>Exec: creates task, runs executor
    Exec->>Agent: converts A2A parts → ADK content, runs LlmAgent
    Agent->>Agent: calls retirement_projection / n_periods / MCP tools
    Agent-->>Exec: text answer
    Exec-->>API: ADK events → A2A events (working → completed)
    API-->>Cli: JSON-RPC response (task + message parts)

    Cli-->>Sub: collects text parts → answer
    Sub-->>Sup: answer text
    Sup-->>User: "Based on your savings, here's the projection…"
```

---

## 4. Step by step

### Step 1 — The supervisor decides to delegate
The user's question enters the supervisor LLM. Its prompt routes
financial-planning questions to the `financial_planner` sub-agent, so the LLM
delegates to it with the question as the argument.

### Step 2 — The sub-agent builds an A2A client
```python
# geap_agent/app/agents/financial_planner_agent.py (simplified)
financial_planner = RemoteA2aAgent(
    name="financial_planner",
    agent_card=_planner_card_url(),  # FINANCIAL_PLANNER_URL
    httpx_client=httpx.AsyncClient(headers=_auth_headers()),  # Bearer token
    full_history_when_stateless=True,
)
```
ADK's `RemoteA2aAgent` resolves the card lazily on first use and talks A2A
directly through its authenticated `httpx` client. The Model B passthrough
card's advertised URL is already public — no rewriting needed. Each call uses a
fresh message/task, so the planner stays stateless.

### Step 3 — Client fetches the agent card
The sub-agent does an HTTP GET on `FINANCIAL_PLANNER_URL` with the Bearer token.
The card returns: name `financial_planner`, capabilities, and one *skill* per
tool (`financial_planner-retirement_projection`, etc.). This is the "how do I
talk to you" discovery step.

### Step 4 — JSON-RPC round trip
The client POSTs a JSON-RPC `SendMessage` (with `A2A-Version: 1.0` and the
Bearer token) to the passthrough base. On the server, `DefaultRequestHandler`
creates a task, and `A2aAgentExecutor` converts the A2A message into a Gemini
`Content(role="user", ...)`.

### Step 5 — The planner does its job
The planner's LLM picks the calculator tools to call — for "Can I retire in 10
years with $1,000/month?" that's likely `retirement_projection` or
`n_periods` — and, if `MCP_PORTFOLIO_URL` is set, the remote MCP portfolio
tools too. It produces a text answer.

### Step 6 — The response converts back
ADK run events become A2A events (`working` → `completed`, plus a final `Task`
with the message parts), carried back in the JSON-RPC response. (If the client
had asked for streaming via `SendStreamingMessage`, the server would reply with
a Server-Sent Events stream instead.)

### Step 7 — Answer → supervisor answer
The sub-agent collects the text parts from the task's artifacts and history,
joins them, and returns a plain string — that string is the answer the
supervisor LLM sees, and it phrases the final answer to the user.

---

## 5. The mental model

```mermaid
flowchart TD
    U["User"] --> S["Supervisor (orchestrator LLM)"]
    S -->|"delegates"| T["financial_planner sub-agent<br/>(RemoteA2aAgent)"]
    T -->|"ADK A2A client + Bearer token"| C["Discovery (GET agent card)"]
    C -->|"POST JSON-RPC SendMessage"| P["Planner A2aAgent (Agent Engine)"]
    P --> E["A2aAgentExecutor"]
    E --> A["LlmAgent → calculator/MCP tools"]
    A -->|"text answer"| E
    E -->|"JSON-RPC response"| T
    T -->|"answer text"| S
    S -->|"final answer"| U
```

Things worth internalizing:

- **A2A is just HTTP + JSON-RPC + a discovery card.** Everything between the
  ADK A2A client (supervisor side) and the planner's executor is standard wire
  protocol, so either side could be any framework — not just ADK.
- **The conversion layers** (ADK content ↔ A2A message parts) exist because ADK
  has its own internal message model, separate from the A2A spec. That's what
  the `convert_genai_part_to_a2a_part` warnings are about.
- **The planner is stateless by design** — each call gets a fresh task, so
  follow-up questions start clean (no planner-side memory between calls).
- **Deployment note:** on Vertex AI Agent Engine (Model B), the planner runs as
  an `A2aAgent` and the platform serves the card natively at
  `.../reasoningEngines/<id>/a2a/.well-known/agent-card.json`. The card's
  advertised URL is already public, so no client-side rewriting is needed.

---

## 6. Where to go next

- [A2A_ARCHITECTURE.md](./A2A_ARCHITECTURE.md) — the deep dive: deployment
  models, protocol edge cases, and the calculator sign-convention fix.
- [TROUBLESHOOTING.md](./TROUBLESHOOTING.md) — every error hit and resolved
  during deployment, explained from first principles.
- `app/deploy_a2a.py` — the planner's Model B deployment script (A2aAgent
  wrapper + `ReasoningEngine.create()`).
- `geap_agent/app/agents/financial_planner_agent.py` — the supervisor's
  client-side `RemoteA2aAgent` sub-agent.
