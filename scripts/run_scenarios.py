"""Five scripted agent turns against a world where the truth is known.

Answers the question the design is blocked on: do read-back probes catch
anything, and what does the deterministic half miss.

Two scenarios are expected to fail. They need claim extraction, which needs a
model and access to agent text that the MCP boundary never sees. They are here
to measure the gap, not to pass. A future session reading two red rows as a bug
will "fix" them by putting a model back into the correctness path, which the
whole design exists to avoid.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import httpx
from pydantic import BaseModel

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from midwire.checks import Dedupe, run_probe
from midwire.ledger import Ledger
from midwire.models import Finding, Probe, ToolCall
from midwire.policy import Action, Policy

MOCK = "http://127.0.0.1:8787"
PROBE = Probe(write_tool="create_record", read_url=f"{MOCK}/records/{{id}}",
              id_field="id", compare_fields=["name"])


class Scenario(BaseModel):
    name: str
    fault: str
    writes: int
    claims_extra_action: bool = False
    expect_caught: bool
    why: str = ""


SCENARIOS = [
    Scenario(name="clean write", fault="none", writes=1, expect_caught=False,
             why="must not fire"),
    Scenario(name="write dropped behind a 200", fault="drop_write", writes=1,
             expect_caught=True, why="probe reads back a 404"),
    Scenario(name="same write emitted twice", fault="none", writes=2,
             expect_caught=True, why="fingerprint repeats within the turn"),
    Scenario(name="read serves a stale copy", fault="stale_read", writes=1,
             expect_caught=True, why="read-back disagrees with what was written"),
    Scenario(name="action claimed, no call emitted", fault="none", writes=0,
             claims_extra_action=True, expect_caught=False,
             why="needs claim extraction; the MCP boundary never sees agent text"),
]


async def run(scenario: Scenario, ledger: Ledger,
              policy: Policy) -> tuple[list[Finding], Action]:
    async with httpx.AsyncClient(timeout=5) as client:
        await client.post(f"{MOCK}/fault/{scenario.fault}")

        turn = ledger.begin_turn()
        dedupe = Dedupe()
        findings: list[Finding] = []

        for _ in range(scenario.writes):
            response = await client.post(f"{MOCK}/records",
                                         json={"name": "alice", "amount": 1})
            call = ToolCall(tool="create_record", args={"name": "alice", "amount": 1},
                            result=response.json())
            call_id = ledger.record(turn, call)

            for finding in (dedupe.check(call),
                            await run_probe(PROBE, call, timeout_ms=500)):
                if finding:
                    findings.append(finding)
                    ledger.record_finding(call_id, finding)

        await client.post(f"{MOCK}/fault/none")
    return findings, policy.decide(findings)


async def main() -> int:
    try:
        async with httpx.AsyncClient(timeout=3) as c:
            await c.get(f"{MOCK}/health")
    except httpx.HTTPError:
        print(f"mock world unreachable at {MOCK}. Start it with: just mockworld")
        return 2

    ledger = Ledger(Path("/tmp/midwire-scenarios.db"))
    policy = Policy()
    rows = []

    for scenario in SCENARIOS:
        findings, action = await run(scenario, ledger, policy)
        caught = bool(findings)
        rows.append((scenario, caught, findings, action))

    print(f"{'scenario':32} {'expect':>7} {'caught':>7} {'action':>9}  finding")
    print("-" * 96)
    expected = 0
    for scenario, caught, findings, action in rows:
        ok = caught == scenario.expect_caught
        expected += ok
        kinds = ",".join(sorted({f.kind for f in findings})) or "-"
        print(f"{scenario.name:32} {str(scenario.expect_caught):>7} "
              f"{str(caught):>7} {action.name:>9}  {kinds}"
              f"{'' if ok else '   <- UNEXPECTED'}")

    gaps = [s for s, c, _, _ in rows if not s.expect_caught and s.claims_extra_action]
    print(f"\n{expected}/{len(rows)} scenarios behaved as designed")
    print(f"{len(gaps)} known gap(s) needing claim extraction: "
          f"{', '.join(s.name for s in gaps)}")

    stats = ledger.stats()
    print(f"ledger: {stats.turns} turns, {stats.calls} calls, "
          f"{stats.findings} findings")
    return 0 if expected == len(rows) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
