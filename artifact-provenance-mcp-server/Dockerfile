FROM python:3.12-slim AS builder
WORKDIR /build
COPY artifact-provenance-mcp-server/pyproject.toml ./
RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PLATFORM_REPO_ROOT=/workspace
RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/* \
    && groupadd --system mcp && useradd --system --gid mcp --home-dir /app mcp
WORKDIR /app
COPY --from=builder /install /usr/local
COPY shared ./shared
COPY artifact-provenance-mcp-server ./artifact-provenance-mcp-server
RUN mkdir /workspace && chown mcp:mcp /workspace
USER mcp
WORKDIR /app/artifact-provenance-mcp-server
EXPOSE 7120
HEALTHCHECK --interval=30s --timeout=3s --retries=3 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7120/v1/health/ready', timeout=2)"]
CMD ["python", "-m", "artifact_provenance_mcp.server"]
