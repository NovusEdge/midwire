"""An MCP server in front of the mock world, for midwire to wrap."""

from __future__ import annotations

import os

import httpx
from fastmcp import FastMCP

MOCK = os.environ.get("MIDWIRE_MOCK_URL", "http://127.0.0.1:8787")

mcp = FastMCP(name="records")


@mcp.tool
def create_record(name: str, amount: int = 0) -> dict:
    """Create a record and return it with its id."""
    return httpx.post(f"{MOCK}/records",
                      json={"name": name, "amount": amount}).raise_for_status().json()


@mcp.tool
def get_record(id: str) -> dict:
    """Fetch one record by id."""
    return httpx.get(f"{MOCK}/records/{id}").raise_for_status().json()


if __name__ == "__main__":
    mcp.run(transport="http", host="127.0.0.1",
            port=int(os.environ.get("PORT", 8788)))
