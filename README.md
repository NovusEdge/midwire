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
write, detects duplicate writes, and reconciles what the agent claimed against
what it actually called.

## The design commitment

The model does one narrow job: extracting asserted actions from agent text.
Everything downstream is deterministic. A read-back probe either finds the row
or it does not.

This is deliberate. Calibrated model confidence fails out-of-distribution, and
a wrong tool result is by definition out of distribution. Three independent
research passes flagged this. A model judging correctness would put the sensor
back inside the loop it is supposed to close, so the architecture asks the
world instead.

## Honest position

This is category creation. Nobody names this bug class in organic discussion,
and the adjacent open-source attempt drew four upvotes. The pain is real in the
few places it surfaces and nearly invisible in aggregate.

The open question that decides everything: do read-back probes catch anything
real in a live agent, or does a mock world only catch mock bugs.

## Status

Design complete, nothing built. See
[the design doc](docs/superpowers/specs/2026-09-22-midwire-design.md).

Next step is the mock world and the deterministic checks, which answer the open
question in a weekend.

```
just verify
```
