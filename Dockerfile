FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

WORKDIR /app

# Dependencies resolve from the lockfile before the source is copied, so an
# edit to src/ does not invalidate the dependency layer.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-install-project --no-dev

# README.md is required: pyproject declares it, and hatchling validates it
# when the project itself is installed.
COPY README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    DATABASE_PATH=/data/midwire.db

EXPOSE 8080
CMD ["python", "-m", "midwire.main"]
