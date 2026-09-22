default:
    @just --list

sync:
    uv sync

test:
    uv run pytest -q

# A world that fails the way real ones do. Leave running for `just verify`.
mockworld:
    MIDWIRE_MOCK_DB=/tmp/midwire-mock.sqlite \
    uv run uvicorn midwire.mockworld:app --port 8787 --log-level warning

# Five scripted turns against the mock world. Two are expected to miss: they
# need claim extraction, which the MCP boundary cannot reach.
verify:
    uv run scripts/run_scenarios.py
