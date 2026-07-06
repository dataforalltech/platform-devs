#!/usr/bin/env bash
# register-mcp-backends.sh — registra os sidecars MCP no ADMIN_DATAFORALL.GATEWAY_MAPPING
# para o platform-mcp (front-door) agregar as tools deles. Idempotente.
#
# Cada sidecar tem convencao propria (path/transport) — ver bring-up-errors-and-fixes.md K3:
#   gateway-mcp : mcp_http, http://platform-api-gateway-mcp:7100, /mcp/tools/list + /mcp/tools/call (mcp)
#   admin-mcp   : mcp_http, http://platform-admin-mcp:7100,       /v1/tools + /v1/call            (v1)  [110 tools]
#   auth-mcp    : sse,      http://platform-auth-mcp:28000,       /sse   (agregacao SSE pendente)
#
# Depois de registrar, o platform-mcp recarrega o registry (restart ou a cada CATALOG_REFRESH_SECONDS).
set -uo pipefail
PW=$(grep '^MYSQL_ROOT_PASSWORD=' /opt/dataforall/deploy/.env | cut -d= -f2-)
M(){ docker exec dataforall-admin-mysql mysql -uroot -p"$PW" -e "$1" 2>/dev/null; }

echo "== colunas MCP no GATEWAY_MAPPING (migration 0003 do platform-mcp) =="
M "ALTER TABLE ADMIN_DATAFORALL.GATEWAY_MAPPING
   ADD COLUMN kind VARCHAR(32) NOT NULL DEFAULT 'rest',
   ADD COLUMN mcp_url VARCHAR(512) DEFAULT NULL,
   ADD COLUMN tools_list_path VARCHAR(255) DEFAULT '/mcp/tools/list',
   ADD COLUMN tools_call_path VARCHAR(255) DEFAULT '/mcp/tools/call',
   ADD COLUMN call_style VARCHAR(16) DEFAULT 'mcp';" 2>&1 | grep -iv 'Duplicate column' || true

reg(){ # nome kind mcp_url list call style
  M "INSERT INTO ADMIN_DATAFORALL.GATEWAY_MAPPING (name_microservice,kind,mcp_url,tools_list_path,tools_call_path,call_style)
     VALUES ('$1','$2','$3','$4','$5','$6')
     ON DUPLICATE KEY UPDATE kind='$2',mcp_url='$3',tools_list_path='$4',tools_call_path='$5',call_style='$6';"
  echo "  + $1 ($2, $3)"
}
echo "== registra sidecars =="
reg platform-api-gateway-mcp mcp_http http://platform-api-gateway-mcp:7100 /mcp/tools/list /mcp/tools/call mcp
reg platform-admin-mcp       mcp_http http://platform-admin-mcp:7100       /v1/tools        /v1/call         v1
reg platform-auth-mcp        sse      http://platform-auth-mcp:28000       /sse             /sse             mcp
reg platform-connectors-mcp  mcp_http http://platform-connectors-mcp:28000 /mcp/tools/list  /mcp/tools/call  mcp
reg platform-analytics-mcp   mcp_http http://platform-analytics-mcp:7100   /mcp/tools/list  /mcp/tools/call  mcp
reg platform-cdc-mcp         mcp_http http://platform-cdc-mcp:28000        /mcp/tools/list  /mcp/tools/call  mcp
reg platform-communication-mcp mcp_http http://platform-communication-mcp:7100 /mcp/tools/list /mcp/tools/call mcp  # 65 tools (K5 resolvido)
reg platform-ml-mcp          mcp_http http://platform-ml-mcp:7104          /mcp/tools/list  /mcp/tools/call  mcp
reg platform-agents-factory-mcp mcp_http http://platform-agents-factory-mcp:7130 /mcp/tools/list /mcp/tools/call mcp
reg platform-monitor-mcp     mcp_http http://platform-monitor-mcp:28000     /mcp/tools/list  /mcp/tools/call  mcp
reg platform-iceberg-mcp     mcp_http http://platform-iceberg-mcp:7104      /mcp/tools/list  /mcp/tools/call  mcp  # 13 tools (tenants/warehouses/sql-users/permissions)
reg platform-scheduler-mcp   mcp_http http://platform-scheduler-mcp:7106     /mcp/tools/list  /mcp/tools/call  mcp
reg platform-dai-mcp         mcp_http http://platform-dai-mcp:7120          /mcp/tools/list  /mcp/tools/call  mcp  # 46 tools (le o OpenAPI da API)
reg platform-crm-mcp         mcp_http http://platform-crm-mcp:7100          /mcp/tools/list  /mcp/tools/call  mcp  # 240 tools (crm-domain, tenant sales) — estilo mcp; openapi expoe /mcp/tools/{list,call} (NAO /v1/tools)
reg platform-sales-partners-mcp mcp_http http://platform-sales-partners-mcp:7107 /mcp/tools/list /mcp/tools/call mcp  # comissoes/parceiros (tenant sales)
reg platform-governance-mcp  mcp_http http://platform-governance-mcp:7103    /mcp/tools/list  /mcp/tools/call  mcp  # 8 tools; healthy. ATENCAO: /mcp/tools/list exige Bearer (Twin PEP, MCP_GOVERNANCE_SERVICE_TOKEN) -> front-door da 401 no refresh ate mandar auth por backend (K10)
# notification-mcp: MCP de transporte SSE (Starlette Route /sse + Mount /messages), NAO http.
#   -> registrar como sse (igual auth-mcp): reg platform-notification-mcp sse http://platform-notification-mcp:7100 /sse /sse mcp
#   mas a agregacao SSE do platform-mcp esta pendente, entao nao agrega tools ainda (ver K3/auth-mcp).

echo "== recarrega o registry do platform-mcp =="
docker restart platform-mcp >/dev/null 2>&1 && echo "platform-mcp reiniciado"
sleep 18
docker logs platform-mcp 2>&1 | grep -iE 'catalog:' | tail -1
