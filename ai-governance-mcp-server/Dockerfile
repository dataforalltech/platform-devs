# ai-governance-mcp — sidecar kind=mcp_http (Model C). STD-DEPLOY-001: non-root.
# Build context = raiz do repo (mesma convenção dos demais servers).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app \
    MCP_PORT=7100 \
    DOCS_ENABLED=false

WORKDIR /app

# Compute-only: sem shared/ (o PEP inner-token é inline; sem backend REST).
# A knowledge-base é a fonte de dados do serviço — precisa ir na imagem.
COPY ai-governance-mcp-server/pyproject.toml ./
COPY ai-governance-mcp-server/README.md ./
COPY ai-governance-mcp-server/src/ ./src/
COPY ai-governance-mcp-server/knowledge-base/ ./knowledge-base/
RUN pip install --no-cache-dir .

# STD-DEPLOY-001: usuário não-root (UID 1000).
RUN useradd --uid 1000 --create-home appuser
USER 1000

EXPOSE 7100
HEALTHCHECK --interval=30s --timeout=10s --start-period=45s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:7100/v1/health',timeout=4).status==200 else 1)"

CMD ["ai-governance-mcp"]
