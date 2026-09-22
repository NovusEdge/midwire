from __future__ import annotations

import json
import sqlite3
import uuid
from pathlib import Path

from pydantic import BaseModel

from midwire.models import Finding, ToolCall

SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
    id      INTEGER PRIMARY KEY,
    turn    TEXT NOT NULL,
    tool    TEXT NOT NULL,
    args    TEXT NOT NULL,
    result  TEXT,
    at      REAL DEFAULT (unixepoch('subsec'))
);
CREATE TABLE IF NOT EXISTS findings (
    id       INTEGER PRIMARY KEY,
    call_id  INTEGER NOT NULL REFERENCES calls(id),
    kind     TEXT NOT NULL,
    tool     TEXT NOT NULL,
    detail   TEXT NOT NULL,
    at       REAL DEFAULT (unixepoch('subsec'))
);
CREATE INDEX IF NOT EXISTS calls_turn ON calls(turn);
"""


class Stats(BaseModel):
    turns: int
    calls: int
    findings: int


class Ledger:
    """Every tool call and every finding, on disk.

    Useful on its own. A deployment where the probes never fire still shows the
    operator what its agent did, which is what keeps the service running.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.executescript(SCHEMA)

    def _connect(self) -> sqlite3.Connection:
        db = sqlite3.connect(self.path)
        db.row_factory = sqlite3.Row
        return db

    def begin_turn(self) -> str:
        return uuid.uuid4().hex

    def record(self, turn: str, call: ToolCall) -> int:
        with self._connect() as db:
            cur = db.execute(
                "INSERT INTO calls (turn, tool, args, result) VALUES (?, ?, ?, ?)",
                (turn, call.tool, json.dumps(call.args, default=str),
                 json.dumps(call.result, default=str)))
            return cur.lastrowid

    def record_finding(self, call_id: int, finding: Finding) -> None:
        with self._connect() as db:
            db.execute(
                "INSERT INTO findings (call_id, kind, tool, detail) VALUES (?,?,?,?)",
                (call_id, finding.kind, finding.tool, finding.detail))

    def calls(self, turn: str) -> list[ToolCall]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT tool, args, result FROM calls WHERE turn = ? ORDER BY id",
                (turn,)).fetchall()
        return [ToolCall(tool=r["tool"], args=json.loads(r["args"]),
                         result=json.loads(r["result"]) if r["result"] else None)
                for r in rows]

    def findings(self, limit: int = 100) -> list[Finding]:
        with self._connect() as db:
            rows = db.execute(
                "SELECT kind, tool, detail FROM findings ORDER BY id DESC LIMIT ?",
                (limit,)).fetchall()
        return [Finding(**dict(r)) for r in rows]

    def stats(self) -> Stats:
        with self._connect() as db:
            return Stats(
                turns=db.execute("SELECT COUNT(DISTINCT turn) c FROM calls")
                        .fetchone()["c"],
                calls=db.execute("SELECT COUNT(*) c FROM calls").fetchone()["c"],
                findings=db.execute("SELECT COUNT(*) c FROM findings")
                           .fetchone()["c"])
