# midwire

Closed-loop agency. Your agents are open-loop — midwire closes the loop.

## The idea

A control system is open-loop when it acts and never senses the result. It is
closed-loop when the measured outcome feeds back and corrects the next move.

Every agent shipping today is open-loop. It calls a tool, reads its own report
of what the call did, and proceeds. The sensor and the actuator are the same
component, so the loop never closes. When the write silently fails, nothing in
the system knows.

Midwire is the missing sensor. It measures what actually changed in the world
and feeds that back before the agent continues.

## Why this exists

Agents are being wired into systems that move money and mutate durable state.
The verification story has not kept up. Schema validation checks shape. Evals
run after the fact. Tracing tells you what happened once you go looking.
Nothing confirms, at the moment of the claim, that the side effect landed.

Two practitioners described the same failure, unprompted, in a thread that
otherwise drew no engagement:

> We are relying on the model to tell us if it did something. That's the whole
> problem.

> last month my claude workflow was logging record creation that never actually
> hit the db. took me way too long to stop trusting what the model told me.

Deloitte's 2026 Tech Trends puts agent pilot-to-production failure at 89%. The
ARC incident catalog attributes 22% of 312 production incidents to output that
was structurally valid and semantically wrong. Agent success falls from 60% on
a single run to 25% across eight consecutive runs.

## What it does

Three failures leave the loop open:

- The agent asserts an action and emits no tool call
- The call is made, the tool returns success, and the write silently fails
- The same non-idempotent write is emitted twice

Midwire keeps a ledger of every tool call, fires a read-back probe after each
write, and detects duplicate writes. For the first failure, midwire adds a
`midwire_report` tool. The agent calls it at the end of a turn with the names
of the tools it used, and midwire flags any name with no matching call in the
ledger.

## Deploy

[![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/deploy/midwire)

[docs/railway.md](docs/railway.md) walks through a template deploy: upstream
auth, connecting an agent, probes, and reading findings.

## Use it

Point your agent at midwire instead of the server it currently uses. Midwire
registers that server's tools as its own and forwards every call.

```
your agent  ->  midwire/mcp  ->  your MCP server
```

A failed check comes back inside the tool result, as a `midwire` field in the
structured content and as a text block, so the agent reads it and tells the
user. Full findings also go in `ToolResult.meta.midwire`. A status page at `/`
shows what the agent did and what read back wrong.

## Configure

Only the upstream URL is required. With nothing else set, the ledger and
duplicate detection still work.

| Variable | Default | Purpose |
|---|---|---|
| `MIDWIRE_UPSTREAM_URL` | required | the MCP server to wrap |
| `MIDWIRE_UPSTREAM_HEADERS` | `{}` | auth forwarded upstream, JSON |
| `MIDWIRE_MODE` | `annotate` | `annotate` or `block` |
| `MIDWIRE_PROBE_TIMEOUT_MS` | `500` | past this, fail open and count it |
| `MIDWIRE_FAIL_CLOSED_TOOLS` | empty | tools that block instead, comma separated |
| `MIDWIRE_PROBES` | `[]` | write-to-read tool pairs, JSON |
| `MIDWIRE_DEDUPE_WINDOW_S` | `120` | how long an identical write counts as a duplicate |
| `MIDWIRE_ADMIN_TOKEN` | empty | guards the status page; empty leaves it open |
| `DATABASE_PATH` | `/data/midwire.db` | ledger location |

A probe pairs a write tool with the read that confirms it:

```json
[{"write_tool": "create_record",
  "read_url": "https://api.example.com/records/{id}",
  "id_field": "id",
  "compare_fields": ["name", "amount"]}]
```

## The design commitment

No model judges correctness. Every check is deterministic — a read-back probe
finds the row or it does not.

Calibrated model confidence fails out-of-distribution, and a wrong tool result
is by definition out of distribution. A model judging correctness would put the
sensor back inside the loop it exists to close, so midwire asks the world
instead.

Annotate is the default. False positives are what get this class of tool
uninstalled, so blocking is opt-in, globally or per tool.

Midwire fails open. A verifier that breaks your agent when a probe endpoint is
down is worse than the bug it prevents. Tools that move money can opt into
failing closed.

## What it misses

Midwire only runs when the agent calls a tool. Two failures happen in agent
text that the MCP boundary never sees:

- The agent fabricates an action and never calls `midwire_report`
- A write succeeds and the agent misreports what it wrote

Catching either needs the host to hand over the agent's text, which is outside
MCP.

## Honest position

This is category creation. Nobody names this bug class in organic discussion,
and the nearest open-source attempt drew four upvotes on Reddit. The pain is
real in the few places it surfaces and nearly invisible in aggregate.

The open question that decides everything: do read-back probes catch anything
in a live agent, or does a mock world only catch mock bugs. If you deploy this
and it finds something real, that is worth an issue.

## Develop

```
just test        # 66 tests
just mockworld   # a service that fails the way real ones do
just verify      # six scripted turns, ground truth known
just live        # a real Claude Code agent through midwire
```

