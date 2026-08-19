# Troubleshooting: A2A client can't get an answer — MCP tools invisible to the A2A executor

## Symptom

Asking the supervisor *"Can I retire in 10 years if I save $1000 per month?"*
returns:

> "I'm sorry, I was unable to get an answer from the financial planner."

The planner's Cloud Run logs show, for every A2A `SendMessage`:

```
ERROR Error handling A2A request: Tool 'get_account_summary' not found.
Available tools: future_value, present_value, payment, n_periods,
retirement_projection, savings_goal_projection
```

Only the six calculator tools are available. The MCP portfolio tools
(`get_account_summary`, `get_portfolio_holdings`, ...) are missing — even
though the model called `get_account_summary` and the planner's prompt tells
it to.

## First-principles breakdown

The system has three layers. Work backwards from the symptom to the layer
that breaks.

### Layer 1: The model must SEE the tool

The planner's prompt tells the model to call `get_account_summary`. The model
did exactly that (the function call is in the A2A history). So the model saw
the tool. **Layer 1 is fine** — the problem is not a prompt or model issue.

### Layer 2: The executor must HAVE the tool

The A2A executor builds its own tool registry from the agent. The error says
`Tool 'get_account_summary' not found` and lists only the calculators. So at
**execution** time, the agent's resolved tool set had only the calculators.
The model was shown a tool the executor could not run.

How did the MCP tools disappear between "the agent was built" and "the
executor resolved it"?

### Layer 3: The toolset must be resolvable in the running context

The MCP portfolio tools come from an `McpToolset` (a lazy, async tool
container — tools are fetched from the MCP server on demand via
`await toolset.get_tools()`).

The planner originally attached the toolset to the agent directly
(`tools=[..., McpToolset(...)]`). That worked on the **dev path** (`/run_sse`)
because the dev path resolves toolsets asynchronously. But the **A2A executor
only surfaces individual `BaseTool`s, not toolsets** — so the toolset's tools
were invisible to it. The card confirmed it: it advertised only the six
calculator skills.

Attempting to fix this by "flattening" the toolset at module import:

```python
_tools.extend(asyncio.run(toolset.get_tools()))   # ❌
```

fails in the container with:

```
RuntimeWarning: coroutine 'AgentRegistrySingleMcpToolset.get_tools' was never awaited
Failed to load portfolio MCP tools (asyncio.run() cannot be called from a running event loop)
```

**Why:** the planner's module is imported during FastAPI app startup, which
runs inside an event loop. `asyncio.run()` creates a *new* loop and cannot be
called when one is already running. The `except` swallowed the error, leaving
only the calculators — the exact "Available tools" list in the log.

Local CLI reproduction worked (no running loop), which is why the bug only
surfaced in the deployed container.

## The fix

1. **Don't resolve the toolset at import time.** `financial_planner_agent.py`
   exposes `build_financial_planner_agent()`, which attaches the toolset as a
   placeholder (no `asyncio.run`).

2. **Resolve it inside the running event loop.** `fast_api_app.py`'s lifespan
   (an async context, so `await` is legal) flattens the toolset:

   ```python
   agent = build_financial_planner_agent()
   agent.tools = [t for t in agent.tools if not isinstance(t, BaseToolset)]
   toolset = build_portfolio_mcp_toolset()
   agent.tools.extend(await toolset.get_tools())
   ```

   This replaces the toolset placeholder with its concrete tools, so the A2A
   executor sees `get_account_summary` etc. The dedup filter prevents listing
   the tools twice (once prefixed by the toolset, once flattened).

3. **IAM:** the planner's Cloud Run service account needed
   `roles/agentregistry.viewer` to resolve the registered MCP server from the
   Agent Registry (the supervisor's runtime SA needed the same grant).

## Verification

The A2A retirement question now returns `TASK_STATE_COMPLETED`:

1. `get_account_summary` → $238,846.12
2. `get_portfolio_holdings` → 12 holdings
3. `future_value(annual_rate=0.07, years=10, payment=1000)` → $653,084.63
4. `retirement_projection` → `balance_at_retirement: 654094.29, sustainable: true`
5. Answer: "~$654,094.29 nest egg, sustainable well beyond age 85"

The agent card now advertises all 15 skills (6 calculators + 9 MCP tools).

## Key takeaways

- **Toolsets are lazy and async.** `McpToolset.get_tools()` must be awaited in
  an async context; never call `asyncio.run()` inside a running event loop
  (FastAPI startup, uvicorn, etc.).
- **A2A executor surfaces tools, not toolsets.** If you need A2A clients to
  call toolset-backed tools, flatten the toolset into concrete tools before
  building the agent.
- **Reproduce in the real runtime.** A bug that passes locally (CLI, no
  event loop) can fail in the container (FastAPI lifespan). Always check the
  deployed logs for warnings like "coroutine ... never awaited".
