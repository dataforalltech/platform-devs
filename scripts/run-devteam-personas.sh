#!/usr/bin/env bash
# run-devteam-personas.sh — sobe os DevTeam persona MCP servers (Model C, kind=mcp_http)
# como processos locais (HTTP-only) e os registra no GATEWAY_MAPPING do platform-mcp,
# para o front-door agregar as tools deles. Depois reinicia o gateway.
#
# Model C = FastAPI puro (GET /v1/health + GET /mcp/tools/list público + POST /mcp/tools/call
# com inner Twin Token). Sem token estático, sem api_key, sem DNS-rebinding: o /mcp/tools/list
# é público (o gateway descobre as tools); o /mcp/tools/call re-verifica o inner twin_token
# (que o gateway injeta em params._meta.twin_token) via JWKS do platform-admin.
#
# ⚠️ Como processo HOST local, o persona pode NÃO alcançar o JWKS do twin (platform-admin:8000
# é interno ao docker) — então as CHAMADAS podem falhar localmente, mas a DESCOBERTA/agregação
# funciona. No deploy docker (personas como containers na rede do gateway) as chamadas funcionam.
# O frontend (Node/stdio) NÃO entra aqui — conecta direto no Desktop.
#
# Uso:  bash scripts/run-devteam-personas.sh
set -uo pipefail

REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
GATEWAY_CONTAINER="${GATEWAY_CONTAINER:-platform-mcp}"
ADMIN_MYSQL="${ADMIN_MYSQL:-dataforall-admin-mysql}"

# persona:porta (frontend 7120 = node/stdio, fora)
PERSONAS="architecture:7118 backend:7119 devops:7121 product-owner:7122 product-manager:7123 qa-engineer:7124 security:7125"

# JWKS do twin (p/ o inner-token verificar as chamadas). Herdado do gateway.
TWIN_JWKS="$(docker exec "$GATEWAY_CONTAINER" printenv URL_ADMIN_TWIN_JWKS 2>/dev/null || true)"
PW="$(docker exec platform-admin printenv ADMIN_DB_PASSWORD 2>/dev/null)"

kill_port() {
  local pid
  pid="$(netstat -ano 2>/dev/null | grep ":$1" | grep LISTENING | awk '{print $NF}' | head -1 || true)"
  if [ -n "$pid" ]; then taskkill //PID "$pid" //F >/dev/null 2>&1 || kill -9 "$pid" 2>/dev/null || true; fi
  return 0
}

register() {  # name port — mcp_http (list público; call usa inner-token). Idempotente.
  docker exec -e MYSQL_PWD="$PW" "$ADMIN_MYSQL" mysql -uroot -e "
    DELETE FROM ADMIN_DATAFORALL.GATEWAY_MAPPING WHERE name_microservice='platform-$1-mcp';
    INSERT INTO ADMIN_DATAFORALL.GATEWAY_MAPPING (name_microservice, kind, mcp_url, health_path, tools_list_path, tools_call_path, call_style)
    VALUES ('platform-$1-mcp','mcp_http','http://host.docker.internal:$2','/v1/health','/mcp/tools/list','/mcp/tools/call','mcp');" 2>/dev/null
  return 0
}

for pp in $PERSONAS; do
  name="${pp%%:*}"; port="${pp##*:}"
  echo "== $name (:$port) =="
  kill_port "$port"; sleep 1
  ( cd "$REPO_ROOT/$name-mcp-server" && \
    PYTHONPATH="$REPO_ROOT" MCP_HTTP_ONLY=1 MCP_PORT="$port" URL_ADMIN_TWIN_JWKS="$TWIN_JWKS" \
    nohup python -m src.server.mcp_server > "/tmp/$name-mcp.log" 2>&1 & )
  sleep 4
  code="$(curl -s -m 5 "http://localhost:$port/v1/health" -o /dev/null -w '%{http_code}' 2>/dev/null || echo 000)"
  echo "  health -> $code"
  register "$name" "$port" && echo "  registrado (mcp_http)"
done

echo "== reiniciando o gateway p/ refresh do catalogo =="
docker restart "$GATEWAY_CONTAINER" >/dev/null
sleep 14
docker logs --tail 20 "$GATEWAY_CONTAINER" 2>&1 | grep -E 'catalog:.*tools across' | tail -1
echo "OK. Conecte no Desktop: scripts/connect-gateway-desktop.sh <PAT> (minta o PAT + claude mcp add)."
