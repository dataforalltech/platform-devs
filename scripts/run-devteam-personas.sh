#!/usr/bin/env bash
# run-devteam-personas.sh — sobe os DevTeam persona MCP servers (Streamable HTTP) como
# processos locais uvicorn e os registra no GATEWAY_MAPPING do platform-mcp (kind=streamable_http),
# para o front-door agregar as tools deles. Depois reinicia o gateway.
#
# Requisitos: docker (platform-mcp + dataforall-admin-mysql + platform-admin rodando), python.
# Auth do hop gateway->persona: token estatico compartilhado (=INTERNAL_API_TOKEN do ambiente),
# presente no env dos personas (MCP_GATEWAY_STATIC_TOKEN) e no api_key do GATEWAY_MAPPING.
# O frontend (Node/stdio) NAO entra aqui — conecta direto no Desktop.
#
# Uso:  bash scripts/run-devteam-personas.sh          # sobe + registra + reinicia gateway
#       REPO_ROOT=/caminho bash scripts/run-devteam-personas.sh
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
GATEWAY_CONTAINER="${GATEWAY_CONTAINER:-platform-mcp}"
ADMIN_MYSQL="${ADMIN_MYSQL:-dataforall-admin-mysql}"

# persona:porta (frontend 7120 = node/stdio, fora)
PERSONAS="architecture:7118 backend:7119 devops:7121 product-owner:7122 product-manager:7123 qa-engineer:7124 security:7125"

echo "== token DEDICADO do hop gateway->persona (gerado; NAO o master INTERNAL_API_TOKEN) =="
# Token de proposito unico so p/ o S2S gateway->persona (mesmo mecanismo api_key dos
# sidecars mcp_http existentes). Gerado uma vez, guardado gitignored (deploy/secrets/).
TOKEN_FILE="${TOKEN_FILE:-$REPO_ROOT/deploy/secrets/gateway-static-token}"
mkdir -p "$(dirname "$TOKEN_FILE")"
if [ ! -s "$TOKEN_FILE" ]; then
  python -c "import secrets; print('gwsk_'+secrets.token_hex(24))" > "$TOKEN_FILE"
  chmod 600 "$TOKEN_FILE" 2>/dev/null || true
  echo "  gerado token dedicado (gitignored): $TOKEN_FILE"
fi
TOKEN="$(tr -d '\r\n' < "$TOKEN_FILE")"
[ -z "$TOKEN" ] && { echo "ERRO: token vazio"; exit 1; }

kill_port() {
  local port="$1" pid
  pid="$(netstat -ano 2>/dev/null | grep ":$port" | grep LISTENING | awk '{print $NF}' | head -1 || true)"
  if [ -n "$pid" ]; then
    taskkill //PID "$pid" //F >/dev/null 2>&1 || kill -9 "$pid" 2>/dev/null || true
  fi
  return 0
}

PW="$(docker exec platform-admin printenv ADMIN_DB_PASSWORD 2>/dev/null)"
register() {  # name port — DELETE+INSERT (idempotente; name_microservice nao e unique key)
  docker exec -e MYSQL_PWD="$PW" "$ADMIN_MYSQL" mysql -uroot -e "
    DELETE FROM ADMIN_DATAFORALL.GATEWAY_MAPPING WHERE name_microservice='platform-$1';
    INSERT INTO ADMIN_DATAFORALL.GATEWAY_MAPPING (name_microservice, kind, mcp_url, additional_info, health_path)
    VALUES ('platform-$1','streamable_http','http://host.docker.internal:$2/mcp',
            JSON_OBJECT('apiKey','$TOKEN'),'/v1/health');" 2>/dev/null
  return 0
}

for pp in $PERSONAS; do
  name="${pp%%:*}"; port="${pp##*:}"
  echo "== $name (:$port) =="
  kill_port "$port"; sleep 1
  # Proteção anti-DNS-rebinding do FastMCP fica LIGADA; libera só os hosts internos
  # pelos quais o gateway chega (host.docker.internal / localhost). NÃO desliga a proteção.
  ( cd "$REPO_ROOT/$name-mcp-server" && \
    PYTHONPATH="$REPO_ROOT" MCP_GATEWAY_STATIC_TOKEN="$TOKEN" \
    MCP_ALLOWED_HOSTS="host.docker.internal:$port,host.docker.internal,localhost:$port,127.0.0.1:$port" MCP_PORT="$port" \
    nohup python -m src.server.mcp_server > "/tmp/$name-mcp.log" 2>&1 & )
  sleep 4
  code="$(curl -s -m 5 "http://localhost:$port/v1/health" -o /dev/null -w '%{http_code}' 2>/dev/null || echo 000)"
  echo "  health -> $code"
  register "$name" "$port"; echo "  registrado no GATEWAY_MAPPING"
done

echo "== reiniciando o gateway p/ refresh do catalogo =="
docker restart "$GATEWAY_CONTAINER" >/dev/null
sleep 12
docker logs --tail 20 "$GATEWAY_CONTAINER" 2>&1 | grep -E 'catalog:.*tools across' | tail -1
echo "OK. Conecte no Desktop: scripts/connect-gateway-desktop.sh (minta o PAT + claude mcp add)."
