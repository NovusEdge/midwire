"""A page showing what the agent did and what midwire found.

This exists for a commercial reason. A deployment with no visible output gets
deleted, and on Railway that takes the kickback with it. A deployer who can see
findings accumulate keeps the service running.
"""

from __future__ import annotations

import os
import secrets
from html import escape

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse

from midwire.ledger import Ledger

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>midwire</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
:root {{ --bg:#fff; --fg:#111; --dim:#666; --line:#e4e4e7; --err:#b42318; }}
@media (prefers-color-scheme:dark) {{
  :root {{ --bg:#0b0b0c; --fg:#e8e8ea; --dim:#8a8a90; --line:#26262a; --err:#f97066; }}
}}
body {{ background:var(--bg); color:var(--fg); font:15px/1.5 ui-monospace,monospace;
       margin:0; padding:2rem 1rem; }}
main {{ max-width:60rem; margin:0 auto; }}
h1 {{ font-size:1.1rem; margin:0 0 .25rem; }}
p.sub {{ color:var(--dim); margin:0 0 2rem; }}
.stats {{ display:flex; gap:2.5rem; margin-bottom:2rem; flex-wrap:wrap; }}
.stat b {{ display:block; font-size:1.8rem; font-weight:500; }}
.stat span {{ color:var(--dim); font-size:.8rem; text-transform:uppercase;
              letter-spacing:.06em; }}
table {{ width:100%; border-collapse:collapse; }}
th {{ text-align:left; color:var(--dim); font-weight:400; font-size:.8rem;
      text-transform:uppercase; letter-spacing:.06em;
      border-bottom:1px solid var(--line); padding:.5rem .75rem .5rem 0; }}
td {{ padding:.6rem .75rem .6rem 0; border-bottom:1px solid var(--line);
      vertical-align:top; }}
.kind {{ color:var(--err); white-space:nowrap; }}
.empty {{ color:var(--dim); padding:2rem 0; }}
</style></head>
<body><main>
<h1>midwire</h1>
<p class="sub">Closed-loop agency. Wrapping {upstream}</p>
<div class="stats">
  <div class="stat"><b>{turns}</b><span>turns</span></div>
  <div class="stat"><b>{calls}</b><span>calls</span></div>
  <div class="stat"><b>{findings}</b><span>findings</span></div>
  <div class="stat"><b>{unreported}</b><span>turns without a report</span></div>
</div>
<p class="sub">A turn without a report is still in progress, or its agent never
called midwire_report, so its claims went unchecked.</p>
{body}
</main></body></html>"""

TABLE = """<table><thead><tr><th>finding</th><th>tool</th><th>detail</th></tr>
</thead><tbody>{rows}</tbody></table>"""

EMPTY = """<p class="empty">No findings yet. Every write this agent made read
back clean.</p>"""


def build() -> FastAPI:
    ledger = Ledger(os.environ.get("DATABASE_PATH", "/data/midwire.db"))
    token = os.environ.get("MIDWIRE_ADMIN_TOKEN", "")
    upstream = os.environ.get("MIDWIRE_UPSTREAM_URL", "(unset)")
    app = FastAPI()

    @app.get("/health")
    def health() -> dict[str, object]:
        stats = ledger.stats()
        return {"status": "ok", "calls": stats.calls, "findings": stats.findings}

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request) -> str:
        # compare_digest so a wrong token cannot be found a character at a time.
        supplied = request.query_params.get("token", "")
        if token and not secrets.compare_digest(supplied, token):
            raise HTTPException(401, "bad or missing token")

        # Tool names and details come from the agent, so they get escaped.
        findings = ledger.findings(limit=200)
        rows = "".join(
            f'<tr><td class="kind">{escape(f.kind)}</td><td>{escape(f.tool)}</td>'
            f"<td>{escape(f.detail)}</td></tr>" for f in findings)
        stats = ledger.stats()
        return PAGE.format(
            upstream=escape(upstream), turns=stats.turns, calls=stats.calls,
            findings=stats.findings, unreported=stats.unreported,
            body=TABLE.format(rows=rows) if findings else EMPTY)

    return app


app = build()
