# The zipy image: apps/engine, which runs every enabled chat platform, the HTTP server and the
# workers in one process. The console runs from source.
FROM ghcr.io/astral-sh/uv:0.12-python3.12-trixie-slim

ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PATH=/app/.venv/bin:$PATH

WORKDIR /app
# Every member's pyproject.toml, so the workspace lockfile can be checked.
COPY pyproject.toml uv.lock ./
COPY apps/engine/pyproject.toml apps/engine/
COPY apps/cli/pyproject.toml apps/cli/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-workspace --package engine

COPY zipy.toml ./
COPY apps/engine ./apps/engine
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --package engine

ARG GIT_SHA=unknown
ENV ZIPY_GIT_SHA=${GIT_SHA}

RUN useradd --system --uid 10001 zipy && mkdir -p /var/lib/zipy/traces && chown -R zipy /var/lib/zipy
USER zipy

# Trace files go to a volume; compose mounts one at /var/lib/zipy.
ENV ZIPY_API__HOST=0.0.0.0 \
    ZIPY_APP__ENV=prod \
    ZIPY_TELEMETRY__LOG_JSON=true \
    ZIPY_TELEMETRY__TRACE_DIR=/var/lib/zipy/traces
VOLUME /var/lib/zipy
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/health')"]
ENTRYPOINT ["zipy"]
CMD ["serve"]
