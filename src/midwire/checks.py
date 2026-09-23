from __future__ import annotations

import json
import time

import httpx

from midwire.models import Finding, Probe, ToolCall

__all__ = ["Dedupe", "Probe", "check_claims", "run_probe"]


def _served_name(name: str, served: set[str]) -> str | None:
    # Hosts prefix MCP tool names with the server alias the user chose, as in
    # Claude Code's mcp__<alias>__<tool>, so the alias cannot be known here.
    if name in served:
        return name
    return next((t for t in served if name.endswith(f"__{t}")), None)


def check_claims(claimed: list[str], called: list[str],
                 served: set[str]) -> list[Finding]:
    """Tools the agent says it used against the tools it actually called.

    The proxy sees calls, never the agent's prose, so an action claimed with
    no call behind it is invisible from here. Asking the agent to declare its
    own tool names turns that into an exact set comparison, which needs no
    model and cannot drift.

    Only tools midwire serves are checked. Agents also report the host's own
    tools, which never pass through midwire and would all read as fabricated.

    This catches an agent that believes it acted. An agent that fabricates and
    also stays silent reaches no hook at all, and nothing inside MCP sees it.
    """
    actual = set(called)
    resolved = (_served_name(name, served) for name in claimed)
    return [
        Finding(kind="claim_without_call", tool=tool,
                detail=f"agent reported using {tool}, no such call this turn")
        for tool in dict.fromkeys(resolved) if tool and tool not in actual
    ]


def _fingerprint(call: ToolCall) -> str:
    # sort_keys so a caller reordering kwargs cannot hide a repeated write.
    return f"{call.tool}:{json.dumps(call.args, sort_keys=True, default=str)}"


class Dedupe:
    """Catches the same non-idempotent write emitted twice in one turn.

    Most agents never close a turn, and protocol 2026-07-28 has no sessions,
    so the window also expires after `window_s`. Without that, two unrelated
    tasks hours apart that write the same thing read as a duplicate.
    """

    def __init__(self, window_s: float = 120) -> None:
        self.window_s = window_s
        self._seen: dict[str, float] = {}

    def check(self, call: ToolCall, now: float | None = None) -> Finding | None:
        now = time.monotonic() if now is None else now
        self._seen = {fp: t for fp, t in self._seen.items()
                      if now - t < self.window_s}
        fp = _fingerprint(call)
        if fp in self._seen:
            return Finding(kind="duplicate_write", tool=call.tool,
                           detail=f"{call.tool} already called with these arguments "
                                  "in this turn")
        self._seen[fp] = now
        return None

    def reset(self) -> None:
        self._seen.clear()


async def run_probe(probe: Probe, call: ToolCall, timeout_ms: int) -> Finding | None:
    """Read back what the write claims to have created.

    Returns None when the write is confirmed. Probe failures come back as INFO
    findings so the caller can fail open.
    """
    result = call.result if isinstance(call.result, dict) else {}
    record_id = result.get(probe.id_field)
    if record_id is None:
        return Finding(
            kind="probe_misconfigured", tool=call.tool,
            detail=f"no {probe.id_field!r} in the result of {call.tool}")

    url = probe.read_url.format(**{probe.id_field: record_id, "id": record_id})
    try:
        async with httpx.AsyncClient(timeout=timeout_ms / 1000) as client:
            response = await client.get(url)
    except httpx.HTTPError as exc:
        return Finding(kind="probe_unavailable", tool=call.tool,
                       detail=f"probe {url} failed: {exc}")

    if response.status_code == 404:
        return Finding(
            kind="write_not_found", tool=call.tool,
            detail=f"{call.tool} reported success, {url} returns 404")
    if response.is_error:
        return Finding(kind="probe_unavailable", tool=call.tool,
                       detail=f"probe {url} returned {response.status_code}")

    if not probe.compare_fields:
        return None
    try:
        written = response.json()
    except ValueError:
        written = None
    if not isinstance(written, dict):
        return Finding(
            kind="probe_misconfigured", tool=call.tool,
            detail=f"{url} returned no JSON object to compare fields against")
    for field in probe.compare_fields:
        if written.get(field) != result.get(field):
            return Finding(
                kind="readback_mismatch", tool=call.tool,
                detail=f"{field}: wrote {result.get(field)!r}, "
                       f"read back {written.get(field)!r}")
    return None
