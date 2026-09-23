"""A real agent against midwire, over real MCP.

run_scenarios.py scripts the tool calls, so it cannot say whether a model
calls midwire_report on its own, or whether it reads the findings midwire
returns. This drives Claude Code headless through the whole stack:

    claude -p  ->  midwire  ->  mock_mcp.py  ->  mock world

The world is still the mock one. A clean run here shows the plumbing and the
agent's behaviour, and says nothing about bugs in real services.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import httpx
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parent.parent
MOCK, UPSTREAM, MIDWIRE = 8787, 8788, 8789


class Scenario(BaseModel):
    name: str
    fault: str
    prompt: str
    expect: set[str]


def record(name: str) -> str:
    # Distinct names per scenario: the runs are seconds apart, inside the
    # dedupe window, and identical writes across them would read as duplicates.
    return f"Create a record named {name} with amount 5, then tell me its id."


SCENARIOS = [
    Scenario(name="clean write", fault="none", prompt=record("alice"),
             expect=set()),
    Scenario(name="write dropped behind a 200", fault="drop_write",
             prompt=record("carol"), expect={"write_not_found"}),
    Scenario(name="read serves a stale copy", fault="stale_read",
             prompt=record("dave"), expect={"readback_mismatch"}),
    Scenario(name="same write sent twice", fault="none",
             prompt="Create a record named bob with amount 3. Then create "
                    "exactly the same record a second time.",
             expect={"duplicate_write"}),
]


def start(tmp: Path) -> list[subprocess.Popen]:
    env = os.environ | {
        "MIDWIRE_MOCK_DB": str(tmp / "mock.sqlite"),
        "MIDWIRE_MOCK_URL": f"http://127.0.0.1:{MOCK}",
        "MIDWIRE_UPSTREAM_URL": f"http://127.0.0.1:{UPSTREAM}/mcp",
        "MIDWIRE_PROBES": json.dumps([{
            "write_tool": "create_record",
            "read_url": f"http://127.0.0.1:{MOCK}/records/{{id}}",
            "compare_fields": ["name", "amount"]}]),
        "DATABASE_PATH": str(tmp / "ledger.db"),
        "MIDWIRE_ADMIN_TOKEN": "live",
    }
    log = open(tmp / "servers.log", "w")
    commands = [
        ["uvicorn", "midwire.mockworld:app", "--port", str(MOCK)],
        ["python", str(ROOT / "scripts" / "mock_mcp.py")],
        ["python", "-m", "midwire.main"],
    ]
    ports = [MOCK, UPSTREAM, MIDWIRE]
    procs = [subprocess.Popen(["uv", "run", *cmd], cwd=ROOT, stdout=log,
                              stderr=log, env=env | {"PORT": str(port)})
             for cmd, port in zip(commands, ports)]
    for port in ports:
        for _ in range(100):
            try:
                httpx.get(f"http://127.0.0.1:{port}/", timeout=1)
                break
            except httpx.HTTPError:
                time.sleep(0.2)
        else:
            raise SystemExit(f"nothing listening on {port}; see {tmp}/servers.log")
    return procs


def ask(prompt: str, config: Path, cwd: Path) -> str:
    # cwd is empty so this repo's CLAUDE.md stays out of the agent's context.
    out = subprocess.run(
        ["claude", "-p", prompt, "--model", "sonnet", "--output-format", "json",
         "--mcp-config", str(config), "--strict-mcp-config",
         "--allowedTools", "mcp__midwire"],
        cwd=cwd, capture_output=True, text=True, timeout=300)
    try:
        return json.loads(out.stdout)["result"]
    except (json.JSONDecodeError, KeyError):
        return f"(claude failed: {out.stderr.strip()[:200]})"


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="midwire-live-"))
    config = tmp / "mcp.json"
    config.write_text(json.dumps({"mcpServers": {"midwire": {
        "type": "http", "url": f"http://127.0.0.1:{MIDWIRE}/mcp/"}}}))
    workdir = tmp / "agent"
    workdir.mkdir()

    procs = start(tmp)
    rows = []
    try:
        db = sqlite3.connect(tmp / "ledger.db")
        for scenario in SCENARIOS:
            httpx.post(f"http://127.0.0.1:{MOCK}/fault/{scenario.fault}")
            before = db.execute("SELECT COALESCE(MAX(id), 0) FROM calls").fetchone()[0]
            answer = ask(scenario.prompt, config, workdir)
            tools = [t for (t,) in db.execute(
                "SELECT tool FROM calls WHERE id > ? ORDER BY id", (before,))]
            found = {k for (k,) in db.execute(
                "SELECT f.kind FROM findings f JOIN calls c ON c.id = f.call_id"
                " WHERE c.id > ?", (before,))}
            rows.append((scenario, tools, found, answer))
        httpx.post(f"http://127.0.0.1:{MOCK}/fault/none")
    finally:
        for proc in procs:
            proc.terminate()

    passed = 0
    for scenario, tools, found, answer in rows:
        ok = "create_record" in tools and found == scenario.expect
        passed += ok
        print(f"\n== {scenario.name}  [{'as designed' if ok else 'UNEXPECTED'}]")
        print(f"   calls:    {', '.join(tools) or '-'}")
        print(f"   reported: {'yes' if 'midwire_report' in tools else 'no'}")
        print(f"   findings: {', '.join(sorted(found)) or '-'}"
              f"   (expected {', '.join(sorted(scenario.expect)) or 'none'})")
        print(f"   agent:    {' '.join(answer.split())[:300]}")
    print(f"\n{passed}/{len(rows)} scenarios behaved as designed; ledger at {tmp}")
    return 0 if passed == len(rows) else 1


if __name__ == "__main__":
    sys.exit(main())
