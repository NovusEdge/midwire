import json

import httpx
import pytest
import respx
from fastmcp.tools.base import ToolResult

from midwire.ledger import Ledger
from midwire.models import Probe
from midwire.server import Blocked, Config, MidwireMiddleware


class FakeMessage:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class FakeContext:
    def __init__(self, name, arguments):
        self.message = FakeMessage(name, arguments)


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
