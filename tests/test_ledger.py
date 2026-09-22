import pytest

from midwire.ledger import Ledger
from midwire.models import Finding, ToolCall


@pytest.fixture
def ledger(tmp_path):
    return Ledger(tmp_path / "ledger.db")


def test_records_a_call_and_reads_it_back(ledger):
    turn = ledger.begin_turn()
    ledger.record(turn, ToolCall(tool="create_record", args={"name": "a"},
                                 result={"id": "1"}))
    calls = ledger.calls(turn)
    assert [c.tool for c in calls] == ["create_record"]
    assert calls[0].args == {"name": "a"}


def test_turns_are_isolated(ledger):
    first = ledger.begin_turn()
    ledger.record(first, ToolCall(tool="a"))
    second = ledger.begin_turn()
    ledger.record(second, ToolCall(tool="b"))
    assert [c.tool for c in ledger.calls(first)] == ["a"]
    assert [c.tool for c in ledger.calls(second)] == ["b"]


def test_findings_attach_to_the_call_that_produced_them(ledger):
    turn = ledger.begin_turn()
    call_id = ledger.record(turn, ToolCall(tool="pay", args={"amount": 5}))
    ledger.record_finding(call_id, Finding(kind="duplicate_write", tool="pay",
                                           detail="seen before"))
    findings = ledger.findings()
    assert len(findings) == 1
    assert findings[0].kind == "duplicate_write"


def test_findings_are_newest_first(ledger):
    turn = ledger.begin_turn()
    for kind in ("write_not_found", "duplicate_write"):
        call_id = ledger.record(turn, ToolCall(tool="t"))
        ledger.record_finding(call_id, Finding(kind=kind, tool="t", detail="d"))
    assert [f.kind for f in ledger.findings()] == ["duplicate_write",
                                                   "write_not_found"]


def test_survives_reopening_the_same_file(tmp_path):
    path = tmp_path / "ledger.db"
    turn = Ledger(path).begin_turn()
    Ledger(path).record(turn, ToolCall(tool="create_record"))
    assert len(Ledger(path).calls(turn)) == 1


def test_counts_summarise_activity(ledger):
    turn = ledger.begin_turn()
    call_id = ledger.record(turn, ToolCall(tool="a"))
    ledger.record(turn, ToolCall(tool="b"))
    ledger.record_finding(call_id, Finding(kind="duplicate_write", tool="a",
                                           detail="d"))
    stats = ledger.stats()
    assert stats.calls == 2
    assert stats.findings == 1
    assert stats.turns == 1


def test_result_that_is_not_a_dict_round_trips(ledger):
    turn = ledger.begin_turn()
    ledger.record(turn, ToolCall(tool="list", result=["a", "b"]))
    assert ledger.calls(turn)[0].result == ["a", "b"]
