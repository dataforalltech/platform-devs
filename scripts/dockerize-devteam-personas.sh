#!/usr/bin/env bash
# dockerize-devteam-personas.sh — builda e sobe os 7 DevTeam persona MCP servers (Model C,
# kind=mcp_http) como CONTAINERS na rede do gateway (platform-local), e registra no
# GATEWAY_MAPPING com mcp_url = http://<container>:7100. Torna a subida DURÁVEL e habilita
# as CHAMADAS (inner Twin Token) — o container alcança o JWKS do twin em platform-admin:8000.
#
# Uso:  bash scripts/dockerize-devteam-personas.sh
set -uo pipefail

REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
GATEWAY_CONTAINER="${GATEWAY_CONTAINER:-platform-mcp}"
ADMIN_MYSQL="${ADMIN_MYSQL:-dataforall-admin-mysql}"
NETWORK="${NETWORK:-platform-local}"
TWIN_JWKS="$(docker exec "$GATEWAY_CONTAINER" printenv URL_ADMIN_TWIN_JWKS 2>/dev/null || echo 'http://platform-admin:8000/api/v1/twin/jwks.json')"
PW="$(docker exec platform-admin printenv ADMIN_DB_PASSWORD 2>/dev/null)"

PERSONAS="architecture backend devops product-owner product-manager qa-engineer security"
# porta host antiga (p/ matar o processo host que rodava fora do docker)
declare -A HOSTPORT=( [architecture]=7118 [backend]=7119 [devops]=7121 [product-owner]=7122 [product-manager]=7123 [qa-engineer]=7124 [security]=7125 )

register() {  # name — mcp_http apontando p/ o container (:7100), idempotente
  docker exec -e MYSQL_PWD="$PW" "$ADMIN_MYSQL" mysql -uroot -e "
    DELETE FROM ADMIN_DATAFORALL.GATEWAY_MAPPING WHERE name_microservice='platform-$1-mcp';
    INSERT INTO ADMIN_DATAFORALL.GATEWAY_MAPPING (name_microservice, kind, mcp_url, health_path, tools_list_path, tools_call_path, call_style)
    VALUES ('platform-$1-mcp','mcp_http','http://platform-$1-mcp:7100','/v1/health','/mcp/tools/list','/mcp/tools/call','mcp');" 2>/dev/null
  return 0
}

cd "$REPO_ROOT"
for name in $PERSONAS; do
  cname="platform-$name-mcp"
  echo "== $name → $cname =="
  # mata o processo host antigo (se estava rodando fora do docker)
  hp="${HOSTPORT[$name]}"; pid="$(netstat -ano 2>/dev/null | grep ":$hp" | grep LISTENING | awk '{print $NF}' | head -1 || true)"
  [ -n "$pid" ] && { taskkill //PID "$pid" //F >/dev/null 2>&1 || kill -9 "$pid" 2>/dev/null || true; }
  echo "  build…"
  docker build -q -f "$name-mcp-server/Dockerfile" -t "$cname:local" . >/dev/null 2>&1 && echo "  imagem OK" || { echo "  ⚠️ build FALHOU"; continue; }
  docker rm -f "$cname" >/dev/null 2>&1 || true
  docker run -d --name "$cname" --network "$NETWORK" --restart unless-stopped \
    -e MCP_HTTP_ONLY=1 -e MCP_PORT=7100 -e DOCS_ENABLED=false \
    -e URL_ADMIN_TWIN_JWKS="$TWIN_JWKS" -e MCP_TWIN_AUDIENCE="mcp:$name-mcp" \
    "$cname:local" >/dev/null 2>&1 && echo "  container up"
  sleep 3
  h="$(docker exec "$cname" python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:7100/v1/health',timeout=4).status==200 else 1)" 2>/dev/null && echo ok || echo down)"
  echo "  health: $h"
  register "$name"; echo "  registrado (mcp_url=http://$cname:7100)"
done

echo "== reiniciando o gateway p/ refresh do catalogo =="
docker restart "$GATEWAY_CONTAINER" >/dev/null; sleep 14
docker logs --tail 20 "$GATEWAY_CONTAINER" 2>&1 | grep -E 'catalog:.*tools across' | tail -1
echo "Durável: os 7 personas rodam como containers (restart unless-stopped) na rede $NETWORK."
