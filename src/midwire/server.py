"""The wrapping MCP server.

Midwire registers an upstream server's tools as its own and inspects each
result before the agent sees it. FastMCP gives one hook for this,
`on_call_tool`, which wraps the upstream call. There is no mutator phase and no
severity system in the protocol, so midwire owns both.
"""

from __future__ import annotations

import json
import os
from collections import OrderedDict
from pathlib import Path

from fastmcp import Client, FastMCP
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.server.providers import ProxyProvider
from fastmcp.tools.base import ToolResult
from mcp.types import TextContent
from pydantic import BaseModel, Field

from midwire.checks import Dedupe, check_claims, run_probe
from midwire.ledger import Ledger
from midwire.models import REPORT_TOOL, Finding, Probe, Severity, ToolCall
from midwire.policy import Action, Policy


class Config(BaseModel):
    upstream_url: str
    upstream_headers: dict[str, str] = Field(default_factory=dict)
    mode: str = "annotate"
    probe_timeout_ms: int = 500
    fail_closed_tools: list[str] = Field(default_factory=list)
    probes: list[Probe] = Field(default_factory=list)
    dedupe_window_s: float = 120
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
            dedupe_window_s=float(env.get("MIDWIRE_DEDUPE_WINDOW_S") or 120),
            database_path=Path(env.get("DATABASE_PATH", "/data/midwire.db")),
        )


def payload(result: ToolResult) -> object:
    """What the tool returned, for the ledger and the probe.

    Many servers, GitHub's among them, return JSON as a text block and leave
    structuredContent empty.
    """
    if result.structured_content is not None:
        return result.structured_content
    for block in result.content:
        if isinstance(block, TextContent):
            try:
                return json.loads(block.text)
            except ValueError:
                continue
    return None


class Blocked(Exception):
    """Raised to stop a result reaching the agent."""


class Session:
    """One connected agent.

    MCP has no turn boundary, so midwire_report supplies one: each report
    closes the turn it checks.
    """

    def __init__(self, ledger: Ledger, dedupe_window_s: float) -> None:
        self.ledger = ledger
        self.dedupe = Dedupe(dedupe_window_s)
        self.turn = ledger.begin_turn()

    def close_turn(self) -> None:
        self.dedupe.reset()
        self.turn = self.ledger.begin_turn()


# Past this many live sessions the oldest one is dropped. A dropped session
# only loses its dedupe window; its ledger rows stay.
MAX_SESSIONS = 1024


class MidwireMiddleware(Middleware):
    def __init__(self, config: Config, ledger: Ledger) -> None:
        self.config = config
        self.ledger = ledger
        self.policy = Policy(mode=config.mode,
                             fail_closed_tools=config.fail_closed_tools)
        self.probes = {p.write_tool: p for p in config.probes}
        self.sessions: OrderedDict[str, Session] = OrderedDict()

    def session(self, context: MiddlewareContext) -> Session:
        # One middleware serves every client, so a client that sends a session
        # id gets its own turns. Protocol 2026-07-28 dropped sessions, and
        # FastMCP's Context.session_id then invents a fresh id per request.
        # Clients without the header share one turn, so one deployment should
        # serve one agent.
        key = get_http_headers(include={"mcp-session-id"}).get("mcp-session-id", "")
        if key not in self.sessions:
            self.sessions[key] = Session(self.ledger, self.config.dedupe_window_s)
            if len(self.sessions) > MAX_SESSIONS:
                self.sessions.popitem(last=False)
        self.sessions.move_to_end(key)
        return self.sessions[key]

    async def served(self, context: MiddlewareContext) -> set[str]:
        tools = await context.fastmcp_context.fastmcp.list_tools()
        return {t.name for t in tools} - {REPORT_TOOL}

    async def on_call_tool(self, context: MiddlewareContext,
                           call_next) -> ToolResult:
        result = await call_next(context)
        session = self.session(context)

        call = ToolCall(
            tool=context.message.name,
            args=dict(context.message.arguments or {}),
            result=payload(result),
        )
        call_id = self.ledger.record(session.turn, call)

        findings: list[Finding] = []
        if call.tool == REPORT_TOOL:
            # Its own row is already in the ledger by now, and the agent never
            # claims to have called it.
            called = [c.tool for c in self.ledger.calls(session.turn)
                      if c.tool != REPORT_TOOL]
            findings.extend(check_claims(call.args.get("tools_used") or [],
                                         called, await self.served(context)))
            session.close_turn()
        # An agent that used the same tools twice sends identical reports, and
        # a report writes nothing, so it never counts as a duplicate write.
        elif duplicate := session.dedupe.check(call):
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

        # Claude Code hands the model structuredContent alone and drops meta
        # and text blocks, so notes go in both places the model might read.
        # Notes state facts only: models treat an instruction inside a tool
        # result as prompt injection. Probe outages stay in meta, since they
        # are midwire's own failure and say nothing about the write.
        notes = [f"midwire: {f.detail}" for f in findings
                 if f.severity is Severity.ERROR]
        if notes:
            result.content = [*result.content,
                              TextContent(type="text", text="\n".join(notes))]
            if isinstance(result.structured_content, dict):
                result.structured_content = result.structured_content | {
                    "midwire": notes}
        return result


# Hosts put server instructions in the system prompt, the one channel from
# which a model accepts instructions from midwire.
SERVER_INSTRUCTIONS = """Midwire checks that write tools changed what they
report changing. A result may carry a "midwire" field naming a check that
failed; tell the user about it. Before you answer the user in any turn where
you used tools from this server, call midwire_report with their names."""

REPORT_INSTRUCTIONS = """Call once at the end of every turn in which you used
any tool from this server, passing the exact names of the tools from this
server that you used. Verification of your own account of the turn depends
on it."""


def upstream_client(config: Config) -> Client:
    return Client(StreamableHttpTransport(
        config.upstream_url, headers=config.upstream_headers or None))


def build(config: Config | None = None) -> FastMCP:
    config = config or Config.from_env()
    ledger = Ledger(config.database_path)
    middleware = MidwireMiddleware(config, ledger)

    server = FastMCP(
        name="midwire",
        instructions=SERVER_INSTRUCTIONS,
        providers=[ProxyProvider(lambda: upstream_client(config))],
        middleware=[middleware],
    )

    # A stub: the comparison happens in the middleware, where the call already
    # has a ledger row to hang findings on and the policy already runs.
    @server.tool(description=REPORT_INSTRUCTIONS)
    def midwire_report(tools_used: list[str]) -> dict:
        return {"reported": tools_used}

    return server
