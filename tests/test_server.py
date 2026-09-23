import json

import httpx
import pytest
import respx
from fastmcp.tools.base import ToolResult
from mcp.types import TextContent

from midwire.ledger import Ledger
from midwire.models import Probe
from midwire.server import Blocked, Config, MidwireMiddleware, upstream_client


class FakeMessage:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class FakeTool:
    def __init__(self, name):
        self.name = name


class FakeServer:
    async def list_tools(self):
        return [FakeTool(n) for n in ("search", "create_record", "send_email")]


class FakeFastMCPContext:
    fastmcp = FakeServer()


class FakeContext:
    def __init__(self, name, arguments):
        self.message = FakeMessage(name, arguments)
        self.fastmcp_context = FakeFastMCPContext()


def report(tools):
    return FakeContext("midwire_report", {"tools_used": tools})


@pytest.fixture
def session_header(monkeypatch):
    """Sets the mcp-session-id header the next calls arrive with."""
    def use(session_id):
        monkeypatch.setattr("midwire.server.get_http_headers",
                            lambda include=None: {"mcp-session-id": session_id})
    return use


def kinds(result):
    return [f["kind"] for f in (result.meta or {}).get("midwire", [])]


def text(result):
    return "\n".join(b.text for b in result.content if b.type == "text")


def notes(result):
    return "\n".join((result.structured_content or {}).get("midwire", []))


def upstream(structured):
    async def call_next(_context):
        return ToolResult(structured_content=structured)
    return call_next


@pytest.fixture
def config(tmp_path):
    return Config(
        upstream_url="http://upstream/mcp",
        database_path=tmp_path / "ledger.db",
        probes=[Probe(write_tool="create_record",
                      read_url="http://svc/records/{id}", id_field="id")],
    )


@pytest.fixture
def middleware(config):
    return MidwireMiddleware(config, Ledger(config.database_path))


@respx.mock
async def test_confirmed_write_passes_through_unannotated(middleware):
    respx.get("http://svc/records/7").mock(
        return_value=httpx.Response(200, json={"id": "7"}))
    ctx = FakeContext("create_record", {"name": "a"})
    result = await middleware.on_call_tool(ctx, upstream({"id": "7"}))
    assert (result.meta or {}).get("midwire") is None


@respx.mock
async def test_dropped_write_is_annotated_not_blocked(middleware):
    respx.get("http://svc/records/7").mock(return_value=httpx.Response(404))
    ctx = FakeContext("create_record", {"name": "a"})
    result = await middleware.on_call_tool(ctx, upstream({"id": "7"}))
    findings = result.meta["midwire"]
    assert [f["kind"] for f in findings] == ["write_not_found"]


@respx.mock
async def test_block_mode_raises(config):
    respx.get("http://svc/records/7").mock(return_value=httpx.Response(404))
    config.mode = "block"
    mw = MidwireMiddleware(config, Ledger(config.database_path))
    with pytest.raises(Blocked):
        await mw.on_call_tool(FakeContext("create_record", {"name": "a"}),
                              upstream({"id": "7"}))


@respx.mock
async def test_fail_closed_tool_blocks_even_in_annotate_mode(config):
    respx.get("http://svc/records/7").mock(return_value=httpx.Response(404))
    config.fail_closed_tools = ["create_record"]
    mw = MidwireMiddleware(config, Ledger(config.database_path))
    with pytest.raises(Blocked):
        await mw.on_call_tool(FakeContext("create_record", {"name": "a"}),
                              upstream({"id": "7"}))


async def test_tool_with_no_probe_is_still_recorded(middleware):
    # Zero configuration must still be useful: the ledger and dedupe work with
    # no probes declared at all.
    await middleware.on_call_tool(FakeContext("search", {"q": "x"}),
                                  upstream({"hits": 3}))
    assert middleware.ledger.stats().calls == 1


async def test_duplicate_write_is_caught_without_any_probe(middleware):
    ctx = FakeContext("send_email", {"to": "a@b.c"})
    await middleware.on_call_tool(ctx, upstream({"sent": True}))
    result = await middleware.on_call_tool(ctx, upstream({"sent": True}))
    assert result.meta["midwire"][0]["kind"] == "duplicate_write"


@respx.mock
async def test_annotation_preserves_existing_meta(middleware):
    respx.get("http://svc/records/7").mock(return_value=httpx.Response(404))

    async def call_next(_c):
        return ToolResult(structured_content={"id": "7"}, meta={"upstream": "keep"})

    result = await middleware.on_call_tool(
        FakeContext("create_record", {"name": "a"}), call_next)
    assert result.meta["upstream"] == "keep"
    assert "midwire" in result.meta


async def test_report_checks_only_calls_since_the_last_report(middleware):
    await middleware.on_call_tool(FakeContext("search", {"q": "x"}),
                                  upstream({"hits": 3}))
    await middleware.on_call_tool(report(["search"]), upstream({}))
    # The earlier search belongs to a closed turn and cannot back this claim.
    result = await middleware.on_call_tool(report(["search"]), upstream({}))
    assert kinds(result) == ["claim_without_call"]


async def test_report_ignores_calls_from_another_session(middleware,
                                                         session_header):
    session_header("other")
    await middleware.on_call_tool(FakeContext("search", {"q": "x"}),
                                  upstream({"hits": 3}))
    session_header("mine")
    result = await middleware.on_call_tool(report(["search"]), upstream({}))
    assert kinds(result) == ["claim_without_call"]


async def test_calls_without_a_session_header_share_a_turn(middleware):
    # Protocol 2026-07-28 clients send no session id. Their calls must still
    # meet the report that follows them.
    await middleware.on_call_tool(FakeContext("search", {"q": "x"}),
                                  upstream({"hits": 3}))
    result = await middleware.on_call_tool(report(["search"]), upstream({}))
    assert kinds(result) == []


async def test_report_matching_the_turn_passes(middleware):
    await middleware.on_call_tool(FakeContext("search", {"q": "x"}),
                                  upstream({"hits": 3}))
    result = await middleware.on_call_tool(report(["search"]), upstream({}))
    assert kinds(result) == []


async def test_turn_without_report_is_counted(middleware):
    await middleware.on_call_tool(FakeContext("search", {"q": "x"}),
                                  upstream({"hits": 3}))
    await middleware.on_call_tool(report(["search"]), upstream({}))
    await middleware.on_call_tool(FakeContext("search", {"q": "y"}),
                                  upstream({"hits": 1}))
    assert middleware.ledger.stats().unreported == 1


@respx.mock
async def test_the_agent_reads_a_finding_in_the_result(middleware):
    # Claude Code hands the model structuredContent only, and drops both meta
    # and the text blocks. Hosts without structured output read the text.
    respx.get("http://svc/records/7").mock(return_value=httpx.Response(404))
    result = await middleware.on_call_tool(
        FakeContext("create_record", {"name": "a"}), upstream({"id": "7"}))
    assert result.structured_content["id"] == "7"
    assert "returns 404" in notes(result)
    assert "returns 404" in text(result)


@respx.mock
async def test_a_probe_outage_stays_out_of_the_result(middleware):
    respx.get("http://svc/records/7").mock(side_effect=httpx.ConnectError("down"))
    result = await middleware.on_call_tool(
        FakeContext("create_record", {"name": "a"}), upstream({"id": "7"}))
    assert kinds(result) == ["probe_unavailable"]
    assert "probe" not in notes(result)


async def test_a_clean_result_passes_through_untouched(middleware):
    # An instruction in a tool result reads to the model as prompt injection,
    # so a clean call must not gain a reminder.
    result = await middleware.on_call_tool(FakeContext("search", {"q": "x"}),
                                           upstream({"hits": 3}))
    assert result.structured_content == {"hits": 3}
    assert "midwire" not in text(result)


@respx.mock
async def test_a_json_text_result_is_probed(middleware):
    # GitHub's MCP server returns JSON as text, with no structuredContent.
    respx.get("http://svc/records/7").mock(return_value=httpx.Response(404))

    async def call_next(_c):
        return ToolResult(content=[TextContent(type="text", text='{"id": "7"}')])

    result = await middleware.on_call_tool(
        FakeContext("create_record", {"name": "a"}), call_next)
    assert kinds(result) == ["write_not_found"]
    assert "returns 404" in text(result)


async def test_a_failed_write_is_not_probed(middleware):
    # GitHub answers a refused write with an error result and no url, which
    # would read as a misconfigured probe.
    async def call_next(_c):
        return ToolResult(content=[TextContent(type="text", text="403")],
                          is_error=True)

    result = await middleware.on_call_tool(
        FakeContext("create_record", {"name": "a"}), call_next)
    assert kinds(result) == []


def test_upstream_client_carries_headers(config):
    config.upstream_headers = {"Authorization": "Bearer t"}
    client = upstream_client(config)
    assert client.transport.headers == {"Authorization": "Bearer t"}


class TestConfig:
    def test_reads_env(self, monkeypatch, tmp_path):
        monkeypatch.setenv("MIDWIRE_UPSTREAM_URL", "http://up/mcp")
        monkeypatch.setenv("MIDWIRE_FAIL_CLOSED_TOOLS", "charge, refund")
        monkeypatch.setenv("MIDWIRE_PROBES", json.dumps(
            [{"write_tool": "w", "read_url": "http://x/{id}"}]))
        monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "db"))
        config = Config.from_env()
        assert config.fail_closed_tools == ["charge", "refund"]
        assert config.probes[0].write_tool == "w"

    def test_empty_optional_vars_are_tolerated(self, monkeypatch, tmp_path):
        # A deployer who sets nothing beyond the upstream must still boot.
        monkeypatch.setenv("MIDWIRE_UPSTREAM_URL", "http://up/mcp")
        monkeypatch.setenv("MIDWIRE_PROBES", "")
        monkeypatch.setenv("MIDWIRE_UPSTREAM_HEADERS", "")
        monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "db"))
        config = Config.from_env()
        assert config.probes == []
        assert config.mode == "annotate"
