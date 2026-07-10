#!/usr/bin/env bash
# dockerize-system-mcps.sh — builda e sobe os 12 system-MCPs (Model C, kind=mcp_http) como
# CONTAINERS na rede do gateway (platform-local) e registra no GATEWAY_MAPPING com
# mcp_url=http://<container>:7100. Espelha scripts/dockerize-devteam-personas.sh, mas deriva
# o namespace do DIRETÓRIO (ns = dir - "-server") p/ acertar casos como qa-mcp-server → qa-mcp
# (evita o bug platform-qa-mcp-mcp).
#
# Uso:  bash scripts/dockerize-system-mcps.sh
set -uo pipefail

REPO_ROOT="${REPO_ROOT:-$(cd "$(dirname "$0")/.." && pwd)}"
GATEWAY_CONTAINER="${GATEWAY_CONTAINER:-platform-mcp}"
ADMIN_MYSQL="${ADMIN_MYSQL:-dataforall-admin-mysql}"
NETWORK="${NETWORK:-platform-local}"
TWIN_JWKS="$(docker exec "$GATEWAY_CONTAINER" printenv URL_ADMIN_TWIN_JWKS 2>/dev/null || echo 'http://platform-admin:8000/api/v1/twin/jwks.json')"
PW="$(docker exec platform-admin printenv ADMIN_DB_PASSWORD 2>/dev/null)"

DIRS="ai-governance-mcp-server audit-mcp-server config-mcp-server deploy-mcp-server dev-twin-mcp-server docs-mcp-server infra-mcp-server pipeline-mcp-server qa-mcp-server services-mcp-server session-mcp-server test-mcp-server"

register() {  # $1 = cname (platform-<ns>), $2 = ns
  docker exec -e MYSQL_PWD="$PW" "$ADMIN_MYSQL" mysql -uroot -e "
    DELETE FROM ADMIN_DATAFORALL.GATEWAY_MAPPING WHERE name_microservice='$1';
    INSERT INTO ADMIN_DATAFORALL.GATEWAY_MAPPING (name_microservice, kind, mcp_url, health_path, tools_list_path, tools_call_path, call_style)
    VALUES ('$1','mcp_http','http://$1:7100','/v1/health','/mcp/tools/list','/mcp/tools/call','mcp');" 2>/dev/null
  return 0
}

cd "$REPO_ROOT"
ok=0; fail=0; up=0
for dir in $DIRS; do
  ns="${dir%-server}"          # audit-mcp-server → audit-mcp ; qa-mcp-server → qa-mcp
  cname="platform-$ns"
  echo "== $dir → $cname (aud=mcp:$ns) =="
  if docker build -q -f "$dir/Dockerfile" -t "$cname:local" . >/dev/null 2>&1; then
    echo "  imagem OK"; ok=$((ok+1))
  else
    echo "  ⚠️ build FALHOU"; fail=$((fail+1)); continue
  fi
  docker rm -f "$cname" >/dev/null 2>&1 || true
  docker run -d --name "$cname" --network "$NETWORK" --restart unless-stopped \
    -e MCP_HTTP_ONLY=1 -e MCP_PORT=7100 -e DOCS_ENABLED=false \
    -e URL_ADMIN_TWIN_JWKS="$TWIN_JWKS" -e MCP_TWIN_AUDIENCE="mcp:$ns" \
    "$cname:local" >/dev/null 2>&1 && echo "  container up" || echo "  ⚠️ run FALHOU"
  sleep 3
  h="$(docker exec "$cname" python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://localhost:7100/v1/health',timeout=4).status==200 else 1)" 2>/dev/null && echo ok || echo down)"
  echo "  health: $h"
  [ "$h" = "ok" ] && up=$((up+1))
  register "$cname" "$ns"; echo "  registrado (mcp_url=http://$cname:7100)"
done

echo "== build_ok=$ok build_fail=$fail health_ok=$up =="
echo "== reiniciando o gateway p/ refresh do catalogo =="
docker restart "$GATEWAY_CONTAINER" >/dev/null; sleep 16
docker logs --tail 30 "$GATEWAY_CONTAINER" 2>&1 | grep -Ei 'catalog|tools across|aggregat' | tail -3
echo "DONE_SCRIPT"
