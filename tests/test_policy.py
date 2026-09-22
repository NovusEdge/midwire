import pytest

from midwire.models import Finding
from midwire.policy import Action, Policy


def error(kind: str = "write_not_found", tool: str = "create_record") -> Finding:
    return Finding(kind=kind, tool=tool, detail="d")


def info(tool: str = "create_record") -> Finding:
    return Finding(kind="probe_unavailable", tool=tool, detail="d")


class TestAnnotateMode:
    def test_clean_call_passes(self):
        assert Policy().decide([]) is Action.PASS

    def test_error_annotates_without_blocking(self):
        # Annotate is the default because false positives are what get this
        # class of tool uninstalled.
        assert Policy().decide([error()]) is Action.ANNOTATE

    def test_probe_failure_annotates(self):
        assert Policy().decide([info()]) is Action.ANNOTATE


class TestBlockMode:
    def test_error_blocks(self):
        assert Policy(mode="block").decide([error()]) is Action.BLOCK

    def test_probe_failure_still_only_annotates(self):
        # The probe endpoint being down is midwire's failure, never the agent's.
        assert Policy(mode="block").decide([info()]) is Action.ANNOTATE

    def test_clean_call_passes(self):
        assert Policy(mode="block").decide([]) is Action.PASS


class TestFailClosedTools:
    def test_named_tool_blocks_even_in_annotate_mode(self):
        p = Policy(fail_closed_tools=["charge_card"])
        assert p.decide([error(tool="charge_card")]) is Action.BLOCK

    def test_other_tools_keep_annotating(self):
        p = Policy(fail_closed_tools=["charge_card"])
        assert p.decide([error(tool="create_record")]) is Action.ANNOTATE

    def test_probe_failure_on_a_fail_closed_tool_blocks(self):
        # A write that moves money is the one case where an unverifiable result
        # is worse than a false positive.
        p = Policy(fail_closed_tools=["charge_card"])
        assert p.decide([info(tool="charge_card")]) is Action.BLOCK


class TestParsing:
    @pytest.mark.parametrize("raw,expected", [
        ("", []),
        ("charge_card", ["charge_card"]),
        ("a, b ,c", ["a", "b", "c"]),
    ])
    def test_fail_closed_tools_parse_from_a_comma_list(self, raw, expected):
        assert Policy.parse_tools(raw) == expected

    def test_strongest_action_wins_over_mixed_findings(self):
        p = Policy(fail_closed_tools=["charge_card"])
        assert p.decide([info(), error(tool="charge_card")]) is Action.BLOCK
