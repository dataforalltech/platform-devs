# syntax=docker/dockerfile:1.7
FROM python:3.12.11-slim@sha256:47ae396f09c1303b8653019811a8498470603d7ffefc29cb07c88f1f8cb3d19f AS builder
ENV PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1
WORKDIR /build
RUN apt-get update && apt-get install --yes --no-install-recommends ca-certificates git && rm -rf /var/lib/apt/lists/*
COPY project-product-mcp-server/pyproject.toml ./
RUN --mount=type=secret,id=github_token,required=true \
    TOKEN="$(tr -d '[:space:]' < /run/secrets/github_token)" \
    && test -n "${TOKEN}" \
    && git config --global url."https://x-access-token:${TOKEN}@github.com/".insteadOf "ssh://git@github.com/" \
    && git config --global --add url."https://x-access-token:${TOKEN}@github.com/".insteadOf "git@github.com:" \
    && python -m pip wheel --wheel-dir=/wheels . \
    && rm -f /root/.gitconfig

FROM python:3.12.11-slim@sha256:47ae396f09c1303b8653019811a8498470603d7ffefc29cb07c88f1f8cb3d19f AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/app/project-product-mcp-server:/app/project-product-mcp-server/src:/app/project-product-mcp-server/mcp
RUN groupadd --system platform && useradd --system --gid platform --home-dir /app --shell /usr/sbin/nologin platform
WORKDIR /app
COPY --from=builder /wheels /wheels
RUN find /wheels -maxdepth 1 -type f -name '*.whl' \
      ! -name 'platform_project_product-*.whl' -print0 \
      | xargs -0 python -m pip install --no-cache-dir \
    && python -m pip install --no-cache-dir --no-deps \
      /wheels/platform_project_product-*.whl \
    && rm -rf /wheels
COPY --chown=platform:platform project-product-mcp-server ./project-product-mcp-server
USER platform
WORKDIR /app/project-product-mcp-server
EXPOSE 8000 9090 7121
HEALTHCHECK --interval=30s --timeout=3s --start-period=20s --retries=3 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:9090/health/ready', timeout=2)"]
CMD ["python", "-m", "app.main"]



