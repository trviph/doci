# syntax=docker/dockerfile:1.9
#
# Multi-stage build for the doci API server.
#
# Build from the repo root:
#   docker build -f docker/Dockerfile -t doci .
# (BuildKit reads docker/Dockerfile.dockerignore automatically.)
#
# doci is pure-Python with wheel-only dependencies (psycopg2-binary, pymupdf,
# redis[hiredis], boto3), so the runtime needs no system build tools or libs —
# only ca-certificates for outbound HTTPS (S3 / OTLP). The entrypoint is the
# `doci-api` console script, which binds HOST:PORT (set to 0.0.0.0:8000 here).
ARG PYTHON_VERSION=3.14

# ---------- build stage ----------
FROM ghcr.io/astral-sh/uv:python${PYTHON_VERSION}-bookworm-slim AS build
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never
WORKDIR /app

# Install dependencies first (cached layer) without the project itself, so a
# code-only change doesn't re-resolve/re-download the dependency graph.
RUN --mount=type=cache,target=/root/.cache/uv \
    --mount=type=bind,source=uv.lock,target=uv.lock \
    --mount=type=bind,source=pyproject.toml,target=pyproject.toml \
    uv sync --frozen --no-install-project --no-dev

# Then the project (creates the `doci-api` console script in /app/.venv/bin).
COPY . /app
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ---------- runtime stage ----------
FROM python:${PYTHON_VERSION}-slim-bookworm
# ca-certificates: outbound HTTPS to S3 / OTLP collector. Run as a non-root user.
RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/* \
    && useradd -r -u 10001 -m -d /home/doci doci
COPY --from=build --chown=doci:doci /app /app
ENV PATH="/app/.venv/bin:$PATH" \
    HOST=0.0.0.0 \
    PORT=8000
USER doci
WORKDIR /app
EXPOSE 8000
ENTRYPOINT ["doci-api"]