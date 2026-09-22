"""Serves the MCP endpoint and the status page from one process.

Railway gives a template one port. The MCP server mounts under /mcp and the
status page takes the root, so a deployer gets both from the single generated
domain.
"""

from __future__ import annotations

import os

import uvicorn
from starlette.applications import Starlette
from starlette.routing import Mount

from midwire import status
from midwire.server import build as build_mcp


def build() -> Starlette:
    mcp = build_mcp()
    return Starlette(routes=[
        Mount("/mcp", app=mcp.http_app(path="/")),
        Mount("/", app=status.build()),
    ])


def run() -> None:
    uvicorn.run(build(), host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))


if __name__ == "__main__":
    run()
