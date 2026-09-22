# midwire

Closed-loop agency. Measures what an agent actually changed in the world and
feeds that back before the agent continues.

## Commands

```
just verify             # scripted agent runs against the mock world
just test
```

## Constraints that do not bend

**No model judges correctness.** The model does one job: extracting asserted
actions from agent text. Every check downstream is deterministic — a read-back
probe finds the row or it does not. Model confidence degrades
out-of-distribution, and a wrong tool result is by definition out of
distribution. A model judging correctness would put the sensor back inside the
loop it exists to close.

**Fail open by default.** A verifier that breaks an agent when the probe
endpoint is down is worse than the bug it prevents. Probe timeout at 500ms,
log, pass, increment a counter. Fail-closed is opt-in per tool, for writes that
move money or mutate durable state.

**Annotate before blocking.** False positives are what get this class of tool
uninstalled. Claim extraction ships in annotate-only mode.

**MCP interceptor is the primary hook.** SEP-1763 response phase: mutators run
in sequence, validators run in parallel and block on `error` severity.
Framework middleware (LangGraph `after_model`, Pydantic AI hooks) covers claim
reconciliation, which the MCP boundary cannot see.

## Weekend scope

Deterministic half only: ledger, dedupe, read-back probes, policy, the MCP
interceptor, and the mock world with measured numbers.

Claim extraction and reconciliation stay out until the deterministic half
proves it catches something real. If probes catch nothing, the model half will
not save it.

## Testing

The mock world is a service over SQLite with an injectable fault mode, plus
scripted runs where ground truth is known. Five scenarios: claims without a
call, a dropped write behind a 200, a duplicated write, a misreported object,
and the clean case that must not fire.

Scenarios 1 and 4 need claim extraction and are expected to fail in the
weekend build. They are in deliberately, to measure what the deterministic half
misses.

Publish the failures next to the successes. Report claim-extraction numbers
separately from the deterministic checks.
