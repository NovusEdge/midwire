from __future__ import annotations

import enum
from typing import Any

from pydantic import BaseModel, Field, computed_field


class Severity(enum.StrEnum):
    INFO = "info"
    ERROR = "error"


# Probe problems are the firewall's own failure, never the agent's. Reporting
# them as errors would block traffic whenever the probe endpoint is down, which
# is worse than the bug being prevented.
NON_BLOCKING = frozenset({"probe_unavailable", "probe_misconfigured"})

# The agent calls this to close a turn. A turn with calls and no report row is
# one the agent never accounted for, or one still in progress.
REPORT_TOOL = "midwire_report"


class ToolCall(BaseModel):
    tool: str
    args: dict[str, Any] = Field(default_factory=dict)
    result: Any = None


class Finding(BaseModel):
    kind: str
    tool: str
    detail: str

    @computed_field
    @property
    def severity(self) -> Severity:
        return Severity.INFO if self.kind in NON_BLOCKING else Severity.ERROR


class Probe(BaseModel):
    """A write tool paired with the read that confirms it landed."""

    write_tool: str
    read_url: str
    id_field: str = "id"
    compare_fields: list[str] = Field(default_factory=list)
