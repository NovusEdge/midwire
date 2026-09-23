from __future__ import annotations

import json

import httpx

from midwire.models import Finding, Probe, ToolCall

__all__ = ["Dedupe", "Probe", "check_claims", "run_probe"]


def check_claims(claimed: list[str], called: list[str]) -> list[Finding]:
    """Tools the agent says it used against the tools it actually called.

    The proxy sees calls, never the agent's prose, so an action claimed with
    no call behind it is invisible from here. Asking the agent to declare its
    own tool names turns that into an exact set comparison, which needs no
    model and cannot drift.

    This catches an agent that believes it acted. An agent that fabricates and
    also stays silent reaches no hook at all, and nothing inside MCP sees it.
    """
    actual = set(called)
    return [
        Finding(kind="claim_without_call", tool=tool,
                detail=f"agent reported using {tool}, no such call this turn")
        for tool in dict.fromkeys(claimed) if tool not in actual
    ]


def _fingerprint(call: ToolCall) -> str:
    # sort_keys so a caller reordering kwargs cannot hide a repeated write.
    return f"{call.tool}:{json.dumps(call.args, sort_keys=True, default=str)}"


class Dedupe:
    """Catches the same non-idempotent write emitted twice in one turn."""

    def __init__(self) -> None:
        self._seen: set[str] = set()

    def check(self, call: ToolCall) -> Finding | None:
        fp = _fingerprint(call)
        if fp in self._seen:
            return Finding(kind="duplicate_write", tool=call.tool,
                           detail=f"{call.tool} already called with these arguments "
                                  "in this turn")
        self._seen.add(fp)
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

    written = response.json()
    for field in probe.compare_fields:
        if written.get(field) != result.get(field):
            return Finding(
                kind="readback_mismatch", tool=call.tool,
                detail=f"{field}: wrote {result.get(field)!r}, "
                       f"read back {written.get(field)!r}")
    return None
