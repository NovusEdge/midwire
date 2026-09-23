# Deploy and Host midwire on Railway

midwire sits between your agent and an MCP server, and checks that writes
actually landed. It reads back every write, catches writes that were dropped
behind a 200, catches the same write sent twice, and records everything your
agent did.

## About Hosting midwire

You point midwire at an MCP server you already use. It registers that server's
tools as its own and forwards every call, so your agent changes one URL and
nothing else. After a write returns, midwire fires the read that confirms it
and compares the two. A failed check comes back inside the tool result, so the
agent reads it and tells the user. A status page shows what the agent did and
what read back wrong.

Hosting it means one container, one volume for the ledger, and one environment
variable. Every check is deterministic, so there is no GPU, no model and no
inference cost.

## Why Deploy midwire?

An agent calls a tool, reads its own report of what the call did, and moves on.
The component that acts is the component that reports, so a write that silently
fails is invisible. Practitioners describe the same failure repeatedly: the
workflow logs a record creation that never hit the database.

midwire measures what actually changed and feeds that back before the agent
continues. It annotates by default rather than blocking, because false
positives are what get this kind of tool uninstalled. Tools that move money can
opt into blocking.

It fails open. If a probe endpoint is down, traffic passes and the failure is
counted, because a verifier that breaks your agent is worse than the bug it
prevents.

## Common Use Cases

- Confirm that an agent's database writes, ticket updates or emails actually
  landed, instead of trusting the tool's status code
- Catch duplicate non-idempotent writes before they create two records or two
  charges
- Keep an audit trail of every tool call an agent made, with the findings
  attached

## Dependencies for midwire

- An MCP server for midwire to wrap, reachable over HTTP
- A volume mounted at `/data` for the ledger

### Deployment Dependencies

- [midwire source](https://github.com/NovusEdge/midwire)
- [Model Context Protocol](https://modelcontextprotocol.io)

Set `MIDWIRE_UPSTREAM_URL` to the MCP server you want wrapped. Everything else
has a default: the ledger and duplicate detection work with no further
configuration, and read-back probes switch on when you declare write-to-read
tool pairs in `MIDWIRE_PROBES`.
