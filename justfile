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

# Six scripted turns against the mock world, each with known ground truth.
verify:
    uv run scripts/run_scenarios.py
