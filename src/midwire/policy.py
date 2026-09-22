from __future__ import annotations

import enum

from pydantic import BaseModel, Field

from midwire.models import Finding, Severity


class Action(enum.IntEnum):
    """Ordered so the strongest action across findings wins."""

    PASS = 0
    ANNOTATE = 1
    BLOCK = 2


class Policy(BaseModel):
    mode: str = "annotate"
    fail_closed_tools: list[str] = Field(default_factory=list)

    @staticmethod
    def parse_tools(raw: str) -> list[str]:
        return [t.strip() for t in raw.split(",") if t.strip()]

    def decide(self, findings: list[Finding]) -> Action:
        return max((self._action(f) for f in findings), default=Action.PASS)

    def _action(self, finding: Finding) -> Action:
        # A tool that moves money is the one case where an unverifiable result
        # is worse than a false positive, so even a probe failure blocks it.
        if finding.tool in self.fail_closed_tools:
            return Action.BLOCK
        if finding.severity is Severity.INFO:
            return Action.ANNOTATE
        return Action.BLOCK if self.mode == "block" else Action.ANNOTATE
