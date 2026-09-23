"""A real agent writing to GitHub through midwire.

No faults are injected. The world here is real, so this measures what the
mock cannot: whether midwire stays quiet when nothing is wrong, and whether
anything real trips it.

    claude -p  ->  midwire  ->  GitHub's hosted MCP server

Opens issues in MIDWIRE_SANDBOX_REPO (default NovusEdge/midwire-sandbox).
Needs `gh auth login`.
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

ROOT = Path(__file__).resolve().parent.parent
PORT = 8790
REPO = os.environ.get("MIDWIRE_SANDBOX_REPO", "NovusEdge/midwire-sandbox")

PROMPTS = [
    f"Open an issue in {REPO} titled 'midwire live test {{stamp}}' with a one "
    "line body saying it was opened by an automated test.",
    f"Find the most recent open issue in {REPO} and add a comment saying "
    "'checked by midwire'.",
    f"Close every open issue in {REPO} whose title starts with 'midwire live test'.",
]


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="midwire-github-"))
    token = subprocess.run(["gh", "auth", "token"], capture_output=True,
                           text=True, check=True).stdout.strip()
    env = os.environ | {
        "PORT": str(PORT),
        "MIDWIRE_UPSTREAM_URL": "https://api.githubcopilot.com/mcp/",
        "MIDWIRE_UPSTREAM_HEADERS": json.dumps({"Authorization": f"Bearer {token}"}),
        "MIDWIRE_PROBES": json.dumps([{"write_tool": "issue_write",
                                       "read_url": "{url}", "id_field": "url"}]),
        "MIDWIRE_PROBE_TIMEOUT_MS": "5000",
        "DATABASE_PATH": str(tmp / "ledger.db"),
        "MIDWIRE_ADMIN_TOKEN": "live",
    }
    log = open(tmp / "server.log", "w")
    proc = subprocess.Popen(["uv", "run", "python", "-m", "midwire.main"],
                            cwd=ROOT, env=env, stdout=log, stderr=log)
    config = tmp / "mcp.json"
    config.write_text(json.dumps({"mcpServers": {"midwire": {
        "type": "http", "url": f"http://127.0.0.1:{PORT}/mcp/"}}}))
    workdir = tmp / "agent"
    workdir.mkdir()

    try:
        for _ in range(100):
            try:
                httpx.get(f"http://127.0.0.1:{PORT}/health", timeout=1)
                break
            except httpx.HTTPError:
                time.sleep(0.2)
        db = sqlite3.connect(tmp / "ledger.db")
        for prompt in PROMPTS:
            prompt = prompt.format(stamp=int(time.time()))
            before = db.execute("SELECT COALESCE(MAX(id), 0) FROM calls").fetchone()[0]
            out = subprocess.run(
                ["claude", "-p", prompt, "--model", "sonnet",
                 "--output-format", "json", "--mcp-config", str(config),
                 "--strict-mcp-config", "--allowedTools", "mcp__midwire"],
                cwd=workdir, capture_output=True, text=True, timeout=300)
            try:
                answer = json.loads(out.stdout)["result"]
            except (json.JSONDecodeError, KeyError):
                answer = f"(claude failed: {out.stderr.strip()[:200]})"
            tools = [t for (t,) in db.execute(
                "SELECT tool FROM calls WHERE id > ? ORDER BY id", (before,))]
            found = [f"{k}: {d}" for k, d in db.execute(
                "SELECT f.kind, f.detail FROM findings f JOIN calls c"
                " ON c.id = f.call_id WHERE c.id > ?", (before,))]
            print(f"\n== {prompt}")
            print(f"   calls:    {', '.join(tools) or '-'}")
            print(f"   findings: {'; '.join(found) or '-'}")
            print(f"   agent:    {' '.join(answer.split())[:300]}")
    finally:
        proc.terminate()
    print(f"\nledger at {tmp}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
