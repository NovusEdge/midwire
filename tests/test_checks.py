import httpx
import pytest
import respx

from midwire.checks import Dedupe, Probe, check_claims, run_probe
from midwire.models import Finding, Severity, ToolCall


def call(tool: str, **args) -> ToolCall:
    return ToolCall(tool=tool, args=args, result={"ok": True})


class TestDedupe:
    def test_first_write_passes(self):
        assert Dedupe().check(call("create_record", name="a")) is None

    def test_identical_write_twice_is_a_finding(self):
        d = Dedupe()
        d.check(call("create_record", name="a"))
        finding = d.check(call("create_record", name="a"))
        assert finding is not None
        assert finding.kind == "duplicate_write"

    def test_argument_order_does_not_hide_a_duplicate(self):
        d = Dedupe()
        d.check(ToolCall(tool="pay", args={"amount": 5, "to": "x"}, result={}))
        finding = d.check(ToolCall(tool="pay", args={"to": "x", "amount": 5}, result={}))
        assert finding is not None

    def test_different_arguments_are_not_duplicates(self):
        d = Dedupe()
        d.check(call("create_record", name="a"))
        assert d.check(call("create_record", name="b")) is None

    def test_same_args_on_a_different_tool_is_not_a_duplicate(self):
        d = Dedupe()
        d.check(call("create_record", name="a"))
        assert d.check(call("delete_record", name="a")) is None

    def test_a_new_turn_clears_history(self):
        d = Dedupe()
        d.check(call("create_record", name="a"))
        d.reset()
        assert d.check(call("create_record", name="a")) is None

    def test_a_repeat_after_the_window_is_not_a_duplicate(self):
        d = Dedupe(window_s=60)
        d.check(call("create_record", name="a"), now=0)
        assert d.check(call("create_record", name="a"), now=59) is not None
        assert d.check(call("create_record", name="a"), now=200) is None


@pytest.mark.anyio
class TestProbe:
    @respx.mock
    async def test_confirmed_write_produces_no_finding(self):
        respx.get("http://svc/records/7").mock(
            return_value=httpx.Response(200, json={"id": "7", "name": "a"}))
        probe = Probe(write_tool="create_record", read_url="http://svc/records/{id}",
                      id_field="id")
        c = ToolCall(tool="create_record", args={"name": "a"},
                     result={"id": "7", "name": "a"})
        assert await run_probe(probe, c, timeout_ms=500) is None

    @respx.mock
    async def test_dropped_write_behind_a_200_is_caught(self):
        # The failure practitioners described: the tool reports success and the
        # row never lands.
        respx.get("http://svc/records/7").mock(return_value=httpx.Response(404))
        probe = Probe(write_tool="create_record", read_url="http://svc/records/{id}",
                      id_field="id")
        c = ToolCall(tool="create_record", args={"name": "a"}, result={"id": "7"})
        finding = await run_probe(probe, c, timeout_ms=500)
        assert finding is not None
        assert finding.kind == "write_not_found"

    @respx.mock
    async def test_a_page_that_exists_confirms_a_write_without_json(self):
        # GitHub's MCP server returns only an html url for a new issue.
        respx.get("https://github.com/o/r/issues/1").mock(
            return_value=httpx.Response(200, text="<html>issue</html>"))
        probe = Probe(write_tool="issue_write", read_url="{url}", id_field="url")
        c = ToolCall(tool="issue_write", args={"title": "t"},
                     result={"url": "https://github.com/o/r/issues/1"})
        assert await run_probe(probe, c, timeout_ms=500) is None

    @respx.mock
    async def test_a_non_json_readback_with_fields_to_compare_fails_open(self):
        respx.get("http://svc/records/7").mock(
            return_value=httpx.Response(200, text="<html>"))
        probe = Probe(write_tool="create_record", read_url="http://svc/records/{id}",
                      compare_fields=["name"])
        c = ToolCall(tool="create_record", args={"name": "a"},
                     result={"id": "7", "name": "a"})
        finding = await run_probe(probe, c, timeout_ms=500)
        assert finding.kind == "probe_misconfigured"

    @respx.mock
    async def test_readback_disagreeing_with_the_write_is_caught(self):
        respx.get("http://svc/records/7").mock(
            return_value=httpx.Response(200, json={"id": "7", "name": "different"}))
        probe = Probe(write_tool="create_record", read_url="http://svc/records/{id}",
                      id_field="id", compare_fields=["name"])
        c = ToolCall(tool="create_record", args={"name": "a"},
                     result={"id": "7", "name": "a"})
        finding = await run_probe(probe, c, timeout_ms=500)
        assert finding is not None
        assert finding.kind == "readback_mismatch"

    @respx.mock
    async def test_probe_timeout_fails_open(self):
        # A verifier that breaks the agent when the probe endpoint hangs is
        # worse than the bug it prevents.
        respx.get("http://svc/records/7").mock(side_effect=httpx.TimeoutException("x"))
        probe = Probe(write_tool="create_record", read_url="http://svc/records/{id}",
                      id_field="id")
        c = ToolCall(tool="create_record", args={"name": "a"}, result={"id": "7"})
        finding = await run_probe(probe, c, timeout_ms=50)
        assert finding is not None
        assert finding.kind == "probe_unavailable"
        assert finding.severity is Severity.INFO

    @respx.mock
    async def test_missing_id_in_the_write_result_is_reported_not_raised(self):
        probe = Probe(write_tool="create_record", read_url="http://svc/records/{id}",
                      id_field="id")
        c = ToolCall(tool="create_record", args={"name": "a"}, result={"status": "ok"})
        finding = await run_probe(probe, c, timeout_ms=500)
        assert finding is not None
        assert finding.kind == "probe_misconfigured"


class TestFindingSeverity:
    def test_duplicate_and_missing_write_are_errors(self):
        for kind in ("duplicate_write", "write_not_found", "readback_mismatch"):
            assert Finding(kind=kind, tool="t", detail="d").severity is Severity.ERROR

    def test_probe_problems_do_not_block(self):
        for kind in ("probe_unavailable", "probe_misconfigured"):
            assert Finding(kind=kind, tool="t", detail="d").severity is Severity.INFO


SERVED = {"create_record", "read_record", "a", "b", "c"}


class TestCheckClaims:
    def test_a_claim_with_a_matching_call_passes(self):
        assert check_claims(["create_record"], ["create_record"], SERVED) == []

    def test_a_claim_with_no_call_behind_it_is_caught(self):
        findings = check_claims(["create_record"], ["read_record"], SERVED)
        assert [f.kind for f in findings] == ["claim_without_call"]
        assert findings[0].tool == "create_record"

    def test_calling_more_than_claimed_is_not_a_finding(self):
        # Extra calls are the agent doing work it did not mention, which is
        # noise rather than a lie about the world.
        assert check_claims(["a"], ["a", "b", "c"], SERVED) == []

    def test_a_repeated_claim_reports_once(self):
        findings = check_claims(["a", "a", "a"], [], SERVED)
        assert len(findings) == 1

    def test_claiming_nothing_passes(self):
        assert check_claims([], ["a"], SERVED) == []

    def test_a_host_tool_is_ignored(self):
        # The host's own tools never pass through midwire, so a claim of one
        # has nothing to compare against.
        assert check_claims(["ToolSearch", "Bash"], [], SERVED) == []

    def test_a_host_prefixed_name_matches_the_served_tool(self):
        # Claude Code calls this tool mcp__midwire__create_record.
        assert check_claims(["mcp__midwire__create_record"], ["create_record"],
                            SERVED) == []
        findings = check_claims(["mcp__midwire__create_record"], [], SERVED)
        assert [f.tool for f in findings] == ["create_record"]

    def test_claim_without_call_blocks(self):
        assert Finding(kind="claim_without_call", tool="t",
                       detail="d").severity is Severity.ERROR
