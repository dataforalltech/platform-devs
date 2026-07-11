# docs-mcp — sidecar kind=mcp_http (Model C). STD-DEPLOY-001: non-root.
# Build context = raiz do repo (mesma convenção dos demais servers).
#
# Deps privadas (platform-database-lib/tenant-lib/core-lib) via git+https → o build
# precisa de git + auth. Padrão K10: builder stage instala tudo num venv com o token
# montado como secret (--mount=type=secret,id=github_token); o runtime slim só copia o
# venv — sem git, sem token, sem gitconfig no image final.
#   Build: docker build -f docs-mcp-server/Dockerfile \
#            --secret id=github_token,src=<arquivo-com-o-PAT> -t docs-mcp:local .

FROM python:3.12-slim AS builder

ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY docs-mcp-server/pyproject.toml ./
COPY docs-mcp-server/src/ ./src/

# venv isolado; git autentica via token montado como secret (nunca persistido no layer).
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN --mount=type=secret,id=github_token \
    git config --global "url.https://x-access-token:$(cat /run/secrets/github_token)@github.com/.insteadOf" "https://github.com/" \
    && pip install --no-cache-dir . \
    && rm -f /root/.gitconfig


FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app \
    MCP_PORT=7100 \
    DOCS_ENABLED=false

WORKDIR /app

# Runtime slim: só o venv com o pacote + deps já resolvidas (sem git/token).
COPY --from=builder /opt/venv /opt/venv
COPY docs-mcp-server/src/ ./src/

# STD-DEPLOY-001: usuário não-root (UID 1000).
RUN useradd --uid 1000 --create-home appuser
USER 1000

EXPOSE 7100
HEALTHCHECK --interval=30s --timeout=10s --start-period=45s --retries=5 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:7100/v1/health',timeout=4).status==200 else 1)"

CMD ["docs-mcp"]
