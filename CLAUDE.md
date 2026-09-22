# midwire

Closed-loop agency. Measures what an agent actually changed in the world and
feeds that back before the agent continues.

## Constraints that do not bend

**No model judges correctness.** The model does one job: extracting asserted
actions from agent text. Every check downstream is deterministic — a read-back
probe finds the row or it does not. Model confidence degrades
out-of-distribution, and a wrong tool result is by definition out of
distribution. A model judging correctness would put the sensor back inside the
loop it exists to close.

**Fail open by default.** A verifier that breaks an agent when the probe
endpoint is down is worse than the bug it prevents. Fail-closed is opt-in per
tool, for writes that move money or mutate durable state.

**Annotate before blocking.** False positives are what get this class of tool
uninstalled. Claim extraction ships in annotate-only mode.

**Deterministic half ships first.** Ledger, dedupe, read-back probes, policy.
Claim extraction stays out until probes prove they catch something real. If
probes catch nothing, the model half will not save it.

## Things that look arbitrary and are not

Two of the five test scenarios — an action claimed with no call, and a
misreported object — are expected to fail in the weekend build. They need claim
extraction. They are in deliberately, to measure what the deterministic half
misses. A future session reading two red scenarios as a bug will "fix" them by
adding the model back into the correctness path.

Probe read-back can be fooled by caching. A read served from a cache written by
the same request confirms nothing, so consistency is per-tool and defaults to
strict.

The MCP boundary never sees agent text. Claim reconciliation therefore needs
framework middleware and works on fewer frameworks than the rest of the system.

Midwire wraps an upstream MCP server rather than hooking a protocol
interceptor. SEP-1763 would be the cleaner hook and does not exist — it has
been Draft since November 2025 and the 2026-07-28 spec shipped without it.
Secondary sources describe it as production-ready. They are wrong.
