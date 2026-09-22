default:
    @just --list

sync:
    uv sync

# Scripted agent runs against a mock world where ground truth is known.
# Answers open question 1: do read-back probes catch anything real.
verify *ARGS:
    uv run scripts/run_scenarios.py {{ARGS}}

test:
    uv run pytest -q
