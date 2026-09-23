"""The wrapping MCP server.

Midwire registers an upstream server's tools as its own and inspects each
result before the agent sees it. FastMCP gives one hook for this,
`on_call_tool`, which wraps the upstream call. There is no mutator phase and no
severity system in the protocol, so midwire owns both.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from fastmcp import FastMCP
from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.server.providers import ProxyProvider
from fastmcp.tools.base import ToolResult
from pydantic import BaseModel, Field

from midwire.checks import Dedupe, check_claims, run_probe
from midwire.ledger import Ledger
from midwire.models import Finding, Probe, ToolCall
from midwire.policy import Action, Policy


class Config(BaseModel):
    upstream_url: str
    upstream_headers: dict[str, str] = Field(default_factory=dict)
    mode: str = "annotate"
    probe_timeout_ms: int = 500
    fail_closed_tools: list[str] = Field(default_factory=list)
    probes: list[Probe] = Field(default_factory=list)
    database_path: Path = Path("/data/midwire.db")

    @classmethod
    def from_env(cls) -> Config:
        env = os.environ
        return cls(
            upstream_url=env["MIDWIRE_UPSTREAM_URL"],
            upstream_headers=json.loads(env.get("MIDWIRE_UPSTREAM_HEADERS") or "{}"),
            mode=env.get("MIDWIRE_MODE", "annotate"),
            probe_timeout_ms=int(env.get("MIDWIRE_PROBE_TIMEOUT_MS", 500)),
            fail_closed_tools=Policy.parse_tools(
                env.get("MIDWIRE_FAIL_CLOSED_TOOLS", "")),
            probes=[Probe(**p) for p in json.loads(env.get("MIDWIRE_PROBES") or "[]")],
            database_path=Path(env.get("DATABASE_PATH", "/data/midwire.db")),
        )


REPORT_TOOL = "midwire_report"


class Blocked(Exception):
    """Raised to stop a result reaching the agent."""


class MidwireMiddleware(Middleware):
    def __init__(self, config: Config, ledger: Ledger) -> None:
        self.config = config
        self.ledger = ledger
        self.policy = Policy(mode=config.mode,
                             fail_closed_tools=config.fail_closed_tools)
        self.probes = {p.write_tool: p for p in config.probes}
        # One turn per session. MCP has no turn boundary, so the dedupe window
        # is the connection; a long-lived agent gets a wider window than ideal.
        self.dedupe = Dedupe()
        self.turn = ledger.begin_turn()

    async def on_call_tool(self, context: MiddlewareContext,
                           call_next) -> ToolResult:
        result = await call_next(context)

        call = ToolCall(
            tool=context.message.name,
            args=dict(context.message.arguments or {}),
            result=result.structured_content,
        )
        call_id = self.ledger.record(self.turn, call)

        findings: list[Finding] = []
        if call.tool == REPORT_TOOL:
            # Its own row is already in the ledger by now, and the agent never
            # claims to have called it.
            called = [c.tool for c in self.ledger.calls(self.turn)
                      if c.tool != REPORT_TOOL]
            findings.extend(check_claims(call.args.get("tools_used") or [],
                                         called))
        if duplicate := self.dedupe.check(call):
            findings.append(duplicate)
        if probe := self.probes.get(call.tool):
            if finding := await run_probe(probe, call,
                                          self.config.probe_timeout_ms):
                findings.append(finding)

        for finding in findings:
            self.ledger.record_finding(call_id, finding)

        action = self.policy.decide(findings)
        if action is Action.BLOCK:
            raise Blocked(f"midwire blocked {call.tool}: "
                          + "; ".join(f.detail for f in findings))
        if action is Action.ANNOTATE:
            result.meta = (result.meta or {}) | {
                "midwire": [f.model_dump(mode="json") for f in findings]}
        return result


REPORT_INSTRUCTIONS = """Call once at the end of every turn in which you used
any tool, passing the exact names of the tools you used. Verification of your
own account of the turn depends on it."""


def build(config: Config | None = None) -> FastMCP:
    config = config or Config.from_env()
    ledger = Ledger(config.database_path)
    middleware = MidwireMiddleware(config, ledger)

    def client_factory():
        from fastmcp import Client
        return Client(config.upstream_url, headers=config.upstream_headers or None)

    server = FastMCP(
        name="midwire",
        instructions="Verifies that write tools actually changed the world.",
        providers=[ProxyProvider(client_factory)],
        middleware=[middleware],
    )

    # A stub: the comparison happens in the middleware, where the call already
    # has a ledger row to hang findings on and the policy already runs.
    @server.tool(description=REPORT_INSTRUCTIONS)
    def midwire_report(tools_used: list[str]) -> dict:
        return {"reported": tools_used}

    return server
