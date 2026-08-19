# MALFORMED_FUNCTION_CALL — TVM tools and natural units

## Symptom

Any query that makes the planner call a time-value-of-money tool fails with:

```
finishReason: MALFORMED_FUNCTION_CALL
errorMessage: Malformed function call: print(default_api.future_value(
    present_value=238846.12, rate_per_period=(0.07 / 12), n_periods=12, payment=5000))
```

Fails on both `gemini-2.5-flash` and `gemini-2.5-pro`, on every serving path
(dev UI `/run_sse`, A2A `SendMessage`). Simple text queries (no tool calls)
work fine. Reproduced in a **raw google-genai call** with a minimal
`FunctionDeclaration` — no ADK, prompt, or MCP involvement.

## Root cause

The `future_value` / `present_value` / `payment` / `n_periods` tools exposed
`rate_per_period` and `n_periods` — **monthly** units. The model therefore had
to compute conversions like `0.07 / 12` and `1 * 12` itself while emitting the
function call. LLMs are probabilistic: sometimes they pre-compute
(`0.005833`), sometimes they emit the unevaluated expression
(`0.07 / 12`).

Vertex AI's function-calling gateway validates arguments as strict JSON
literals. An arithmetic expression is not a valid JSON number, so the whole
call is rejected as `MALFORMED_FUNCTION_CALL`. The `print(default_api.<fn>(...))`
text in the error is the gateway's **diagnostic rendering** of the rejected
call — it is not code the model generated, and not something a prompt
instruction can prevent (the model's reasoning is what varies, not its
instructions).

Isolation matrix (raw genai call, same declaration, `gemini-2.5-flash`):

| Tool name | Query | Result |
|---|---|---|
| `future_value` | math query ($5000/mo, 7%, 1y) | MALFORMED (`0.07/12` emitted) |
| `calc_fv` (renamed) | same math query | MALFORMED (`(0.07 / 12)` emitted) |
| `future_value` | "future value of 100 at 5% for 2 years" | OK — literal args |
| `calc_fv` | same simple query | OK — literal args |

Tool name is irrelevant; the trigger is whether the model must *derive* an
argument by arithmetic. Relying on the model to consistently pre-compute math
is an anti-pattern.

## Solution

Move unit conversion from the probabilistic layer (the model) to the
deterministic layer (the tool code). The TVM tools now accept **natural units**:

- `rate_per_period: float` → `annual_rate: float` (e.g. `0.07` for 7%)
- `n_periods: float` → `years: float`

The tool computes `annual_rate / 12.0` and `years * 12.0` internally
(`app/tools/planning_calculator.py`). `retirement_projection` and
`savings_goal_projection` already took natural units and are unchanged.

The model now copies `annual_rate=0.07, years=1` straight from the user's
wording — literal JSON numbers, no arithmetic, no rejection.

## Verification (live, Cloud Run)

Same failing query now produces a proper structured call end-to-end:

1. `functionCall: future_value(present_value=238846.12, annual_rate=0.07, years=1, payment=5000)`
2. `functionResponse: result 318436.7`
3. Final answer: "~$318,436.70" with disclaimer.

An assert-based self-check lives in `planning_calculator._demo()`
(run `python app/tools/planning_calculator.py`).
