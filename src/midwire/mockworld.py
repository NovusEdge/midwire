"""A service that can fail the way real ones fail.

Scenario runs need a world where the ground truth is known. The faults here are
the ones practitioners described: a write that returns 200 and never lands, a
read that serves a stale copy, a handler that writes twice.
"""

from __future__ import annotations

import enum
import os
import sqlite3
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel


class Fault(enum.StrEnum):
    NONE = "none"
    DROP_WRITE = "drop_write"      # 200 returned, row never inserted
    STALE_READ = "stale_read"      # read serves the pre-write value
    DUPLICATE = "duplicate"        # handler inserts twice


class Record(BaseModel):
    name: str
    amount: int = 0


DB = Path(os.environ.get("MIDWIRE_MOCK_DB", "/tmp/midwire-mock.sqlite"))
state = {"fault": Fault(os.environ.get("MIDWIRE_MOCK_FAULT", "none"))}


def connect() -> sqlite3.Connection:
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    return db


@asynccontextmanager
async def lifespan(app: FastAPI):
    DB.parent.mkdir(parents=True, exist_ok=True)
    with connect() as db:
        db.execute("CREATE TABLE IF NOT EXISTS records "
                   "(id TEXT PRIMARY KEY, name TEXT, amount INTEGER)")
    yield


app = FastAPI(lifespan=lifespan)


@app.post("/fault/{fault}")
def set_fault(fault: Fault) -> dict[str, str]:
    state["fault"] = fault
    return {"fault": fault}


@app.post("/records")
def create(record: Record) -> dict[str, object]:
    record_id = uuid.uuid4().hex[:8]
    body = {"id": record_id, "name": record.name, "amount": record.amount}

    if state["fault"] is Fault.DROP_WRITE:
        return body

    with connect() as db:
        db.execute("INSERT INTO records VALUES (?, ?, ?)",
                   (record_id, record.name, record.amount))
        if state["fault"] is Fault.DUPLICATE:
            db.execute("INSERT INTO records VALUES (?, ?, ?)",
                       (uuid.uuid4().hex[:8], record.name, record.amount))
    return body


@app.get("/records/{record_id}")
def read(record_id: str) -> dict[str, object]:
    if state["fault"] is Fault.STALE_READ:
        return {"id": record_id, "name": "stale", "amount": 0}
    with connect() as db:
        row = db.execute("SELECT * FROM records WHERE id = ?",
                         (record_id,)).fetchone()
    if row is None:
        raise HTTPException(404, "not found")
    return dict(row)


@app.get("/records")
def count() -> dict[str, int]:
    with connect() as db:
        return {"count": db.execute("SELECT COUNT(*) c FROM records")
                            .fetchone()["c"]}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "fault": state["fault"]}
