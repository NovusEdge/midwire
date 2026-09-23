# Running midwire from the Railway template

This guide covers a deploy from
[railway.com/deploy/midwire](https://railway.com/deploy/midwire), from the
first click to a finding on the status page. The full variable list is in the
[README](../README.md#configure).

## 1. Deploy

Open the template and set `MIDWIRE_UPSTREAM_URL` to the MCP server you want
wrapped. The server must speak streamable HTTP. For GitHub's hosted server:

```
MIDWIRE_UPSTREAM_URL=https://api.githubcopilot.com/mcp/
```

Railway builds the image, mounts a volume at `/data` for the ledger, and gives
the service a domain such as `midwire-production-xxxx.up.railway.app`. The
service is up when `https://<domain>/health` returns `{"status":"ok",...}`.

## 2. Give midwire the upstream's credentials

Most MCP servers need auth. Midwire forwards `MIDWIRE_UPSTREAM_HEADERS` on
every upstream request:

```
MIDWIRE_UPSTREAM_HEADERS={"Authorization":"Bearer <token>"}
```

Scope the token to what the agent needs. A GitHub fine-grained token needs
**Repository access: Only select repositories** and **Issues: Read and write**.
Under **Public repositories** access, the permission list is disabled. The token
can then open issues and nothing else, and GitHub answers every edit with a 403.

> **The `/mcp` endpoint has no auth of its own.** Anyone who has the domain can
> call the upstream with the token above. Keep the domain private, and give
> the token the smallest scope that works.

## 3. Point your agent at midwire

Your agent connects to `https://<domain>/mcp/` in place of the upstream URL.
For Claude Code:

```
claude mcp add --transport http midwire https://<domain>/mcp/
```

The agent sees the upstream's tools plus one more, `midwire_report`. The
server instructions ask the agent to call it before answering, with the names
of the tools it used. Midwire flags a reported tool that has no matching call.

Serve one agent per deployment. MCP protocol 2026-07-28 has no sessions, so
calls from clients that send no `mcp-session-id` header share one turn.

## 4. Declare probes

Without probes, midwire records every call and catches duplicate writes. A
probe also reads each write back. It pairs a write tool with a URL that
confirms the write:

| Field | Meaning |
|---|---|
| `write_tool` | the tool name as the upstream lists it |
| `read_url` | the confirming URL, with `{field}` filled from the write's result |
| `id_field` | the result field that fills `read_url`, default `id` |
| `compare_fields` | fields that must match between the result and the read-back |

A missing record (404) is a `write_not_found` finding. A field that differs
is a `readback_mismatch`.

For GitHub issues the result carries only `id` and an html `url`, so the probe
reads the issue page back and checks that it exists:

```
MIDWIRE_PROBES=[{"write_tool":"issue_write","read_url":"{url}","id_field":"url"}]
```

For a JSON API that returns the record it created:

```
MIDWIRE_PROBES=[{"write_tool":"create_record","read_url":"https://api.example.com/records/{id}","compare_fields":["name","amount"]}]
```

The probe sends no credentials. It suits public reads, or APIs that accept
the read without auth. Raise `MIDWIRE_PROBE_TIMEOUT_MS` above the 500 ms
default for slow endpoints. A probe that times out is counted and the call
passes, unless the tool is listed in `MIDWIRE_FAIL_CLOSED_TOOLS`.

## 5. Read the results

The agent sees a failed check inside the tool result and tells the user. The
operator sees everything on the status page:

```
https://<domain>/?token=<MIDWIRE_ADMIN_TOKEN>
```

The token is in the service's **Variables** tab. With `MIDWIRE_ADMIN_TOKEN`
empty, the page is open to anyone with the domain. The page shows turns,
calls, findings, and turns with no report.

| Finding | Meaning |
|---|---|
| `write_not_found` | the write reported success and the read-back returned 404 |
| `readback_mismatch` | a compared field reads back different from what was written |
| `duplicate_write` | the same call with the same arguments, within `MIDWIRE_DEDUPE_WINDOW_S` |
| `claim_without_call` | the agent reported a tool it did not call this turn |
| `probe_unavailable` | the probe endpoint failed or timed out; the call passed |
| `probe_misconfigured` | the result lacked `id_field`, or the read-back had no JSON to compare |

## Troubleshooting

| Symptom | Cause |
|---|---|
| The agent sees only `midwire_report` | Midwire cannot list the upstream's tools. Check `MIDWIRE_UPSTREAM_URL` and the auth in `MIDWIRE_UPSTREAM_HEADERS`. |
| Every write is `probe_misconfigured` | `id_field` names a field the result lacks. Call the tool once and read the result for the real field names. |
| Every write is `probe_unavailable` | The read URL is slow or needs auth. Raise the timeout, or pick a read the probe can make without credentials. |
| `duplicate_write` on unrelated tasks | Two tasks wrote identical arguments inside the dedupe window. Lower `MIDWIRE_DEDUPE_WINDOW_S`. |
| The status page returns 401 | The `token` query parameter does not match `MIDWIRE_ADMIN_TOKEN`. |
