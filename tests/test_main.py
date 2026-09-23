from starlette.testclient import TestClient


def test_mcp_endpoint_accepts_a_session(monkeypatch, tmp_path):
    monkeypatch.setenv("MIDWIRE_UPSTREAM_URL", "http://127.0.0.1:1/mcp")
    monkeypatch.setenv("DATABASE_PATH", str(tmp_path / "db"))
    # status builds an app at import time, which opens DATABASE_PATH.
    from midwire import main
    with TestClient(main.build()) as client:
        response = client.post(
            "/mcp/",
            headers={"Accept": "application/json, text/event-stream"},
            json={"jsonrpc": "2.0", "id": 1, "method": "initialize",
                  "params": {"protocolVersion": "2025-06-18", "capabilities": {},
                             "clientInfo": {"name": "t", "version": "0"}}})
    assert response.status_code == 200
