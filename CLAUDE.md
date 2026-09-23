# midwire

Closed-loop agency. Measures what an agent actually changed in the world and
feeds that back before the agent continues.

## Constraints that do not bend

**No model anywhere.** Every check is deterministic. A read-back probe finds
the row or it does not, and a declared tool name is in the ledger or it is not.
Model confidence degrades out-of-distribution, and a wrong tool result is by
definition out of distribution. A model judging correctness would put the
sensor back inside the loop the system exists to close.

Earlier designs reserved a model for pulling asserted actions out of agent
prose. `midwire_report` removed the need: the agent declares the tool names it
used, and the comparison is set membership.

**Fail open by default.** A verifier that breaks an agent when the probe
endpoint is down is worse than the bug it prevents. Fail-closed is opt-in per
tool, for writes that move money or mutate durable state.

**Annotate before blocking.** False positives are what get this class of tool
uninstalled. Claim findings annotate like every other kind.
Blocking a turn because an agent forgot to declare a tool would be the fastest
way to get midwire removed.

## Things that look arbitrary and are not

All six scenarios pass. One case stays out of reach and is not a bug to fix: an
agent that fabricates a write and declares nothing reaches no hook, because
midwire is only invoked when a tool is called. Catching that needs the host to
hand over turn text, which is outside MCP and works on fewer frameworks than
everything else here.

Probe read-back can be fooled by caching. A read served from a cache written by
the same request confirms nothing, so consistency is per-tool and defaults to
strict.

`midwire_report` asks the agent to declare its own tool use, which sounds
circular and is not. The agent lies about the world, never about which tool
name it invoked, because it has no reason to name a tool it did not intend to
call. The ledger holds the ground truth either way.

Midwire wraps an upstream MCP server rather than hooking a protocol
interceptor. SEP-1763 would be the cleaner hook and does not exist — it has
been Draft since November 2025 and the 2026-07-28 spec shipped without it.
Secondary sources describe it as production-ready. They are wrong.
