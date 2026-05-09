# syntax=docker/dockerfile:1.7
#
# ai-governance-mcp-server — imagem Docker para distribuição.
#
# Modelo de execução: stdio-via-`docker run -i`. O cliente MCP spawna um
# container por sessão e fala via stdin/stdout. Não é um daemon HTTP — alinhado
# com a arquitetura escolhida em ADR-0001.
#
# Build:
#   docker build -t d4all.azurecr.io/dataforall/3.0/ai-governance-mcp-server:0.1.0 \
#                ai-governance-mcp-server/
#
# Run (interativo, para teste):
#   docker run -i --rm \
#       -v "$(pwd)/ai-governance-mcp-server/knowledge-base/suggestions:/app/knowledge-base/suggestions" \
#       d4all.azurecr.io/dataforall/3.0/ai-governance-mcp-server:0.1.0
#
# Cliente MCP (claude_desktop_config.json ou ~/.claude.json):
#   {
#     "mcpServers": {
#       "ai-governance": {
#         "command": "docker",
#         "args": [
#           "run", "-i", "--rm",
#           "-v", "/abs/path/to/suggestions:/app/knowledge-base/suggestions",
#           "d4all.azurecr.io/dataforall/3.0/ai-governance-mcp-server:0.1.0"
#         ]
#       }
#     }
#   }
#
# Volume RW obrigatório: /app/knowledge-base/suggestions/ (audit trail).
# Caso contrário, sugestões viram efêmeras (perdidas ao desligar o container).
#
# A knowledge-base textual e ecosystem.yaml ficam embutidos na imagem por
# design — política e topologia versionadas com a release.
#
# Host OS testado em produção: Ubuntu 20.04 LTS (VMs cloud do dataforalltech).
# O container roda debian-bookworm-slim (Python 3.12 oficial), independente do
# host — nenhum ajuste é necessário em hosts mais novos. Requisito único do
# host: Docker >= 20.10 (suporte a Buildx). Ver OPERATIONS.md §1 para a matriz
# completa de OS suportados.

# ============================================================== #
# Stage 1 — builder                                              #
# ============================================================== #
FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /build

# Instala deps primeiro (camada cacheada enquanto pyproject.toml não muda).
COPY pyproject.toml ./
COPY src/ ./src/

# Instala em --prefix isolado para depois copiar para a imagem final.
# Inclui o próprio pacote (entry point ai-governance-mcp-server).
RUN pip install --prefix=/install --no-deps . \
    && pip install --prefix=/install \
        "mcp>=1.2.0,<2.0" \
        "pydantic>=2.6.0,<3.0" \
        "pydantic-settings>=2.2.0,<3.0" \
        "networkx>=3.2,<4.0" \
        "pyyaml>=6.0,<7.0"

# ============================================================== #
# Stage 2 — runtime                                              #
# ============================================================== #
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONUTF8=1 \
    PYTHONIOENCODING=utf-8 \
    GOVERNANCE_LOG_LEVEL=INFO \
    GOVERNANCE_LOG_FORMAT=json \
    GOVERNANCE_KB_PATH=/app/knowledge-base \
    GOVERNANCE_SUGGESTIONS_PATH=/app/knowledge-base/suggestions

# tini é PID 1 confiável: encaminha sinais corretamente quando docker manda
# SIGTERM, evita zumbis. Pequeno (~30KB) e estável.
RUN apt-get update \
    && apt-get install --no-install-recommends -y tini \
    && rm -rf /var/lib/apt/lists/*

# Copia Python deps + scripts instalados pelo builder.
COPY --from=builder /install /usr/local

# Cria usuário não-root e estrutura de dirs.
ARG APP_UID=10001
RUN useradd --system --create-home --uid ${APP_UID} mcp \
    && mkdir -p /app/knowledge-base/suggestions \
    && chown -R mcp:mcp /app

WORKDIR /app

# A knowledge-base (markdowns + ecosystem.yaml) é embutida na imagem para
# garantir que política e topologia ficam versionadas com a release. Volume
# mount externo continua suportado via env GOVERNANCE_KB_PATH.
COPY --chown=mcp:mcp knowledge-base/ /app/knowledge-base/

# Pacote já está instalado em /usr/local — só precisamos do entry point.
USER mcp

# Healthcheck: spawnar e listar tools (resposta MCP em <2s = saudável).
# Dentro de um container stdio-only, healthcheck via `docker exec` exige um
# script auxiliar; mantemos comentado por enquanto. Quando rolar HTTP transport,
# substituir por `curl -f http://localhost:8000/health`.
# HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
#     CMD python -c "from src.knowledge.governance_repository import GovernanceRepository; \
#         from pathlib import Path; GovernanceRepository(kb_path=Path('/app/knowledge-base'))" || exit 1

ENTRYPOINT ["tini", "--", "ai-governance-mcp-server"]

# ============================================================== #
# OCI labels (auditoria + supply chain)                          #
# ============================================================== #
LABEL org.opencontainers.image.title="ai-governance-mcp-server" \
      org.opencontainers.image.description="Centralized MCP Server for AI agent governance in the dataforalltech ecosystem." \
      org.opencontainers.image.source="https://github.com/dataforalltech/platform-service-template" \
      org.opencontainers.image.documentation="https://github.com/dataforalltech/platform-service-template/blob/master/ai-governance-mcp-server/README.md" \
      org.opencontainers.image.licenses="Proprietary" \
      org.opencontainers.image.vendor="dataforalltech"
