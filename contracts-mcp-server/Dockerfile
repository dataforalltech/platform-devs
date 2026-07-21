FROM python:3.12-slim AS builder
WORKDIR /build
COPY contracts-mcp-server/pyproject.toml ./
RUN pip install --no-cache-dir --prefix=/install .

FROM python:3.12-slim AS runtime
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PLATFORM_REPO_ROOT=/workspace
RUN groupadd --system mcp && useradd --system --gid mcp --home-dir /app mcp
WORKDIR /app
COPY --from=builder /install /usr/local
COPY shared ./shared
COPY contracts-mcp-server ./contracts-mcp-server
RUN mkdir /workspace && chown mcp:mcp /workspace
USER mcp
WORKDIR /app/contracts-mcp-server
EXPOSE 7119
HEALTHCHECK --interval=30s --timeout=3s --retries=3 CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:7119/v1/health/ready', timeout=2)"]
CMD ["python", "-m", "contracts_mcp.server"]
