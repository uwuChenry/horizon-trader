# Multi-arch (amd64/arm64): python-slim + uv, installs exactly what uv.lock pins.
#   docker build -f deploy/Dockerfile -t horizon-trader .
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.12 /uv /uvx /bin/

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    HT_DATA_DIR=/data

# Dependencies first so code changes don't bust the cache. No dev/research groups on the server.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --locked --no-dev --no-install-project

COPY src ./src
COPY config ./config
RUN uv sync --locked --no-dev

VOLUME ["/data"]
CMD ["uv", "run", "--no-sync", "python", "-m", "horizon_trader.run_daily", "--dry-run"]
