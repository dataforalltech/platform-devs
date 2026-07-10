#!/usr/bin/env bash
# connect-gateway-desktop.sh — conecta o front-door platform-mcp no seu Claude Code Desktop.
#
# O gateway exige um Bearer que ele troca por Twin Token (PAT->Twin). O PAT é mintado com
# a SUA autenticação de admin — este script NÃO manuseia sua senha. Duas formas:
#
#   A) Você já tem um PAT (d4all_pat_...):
#        bash scripts/connect-gateway-desktop.sh d4all_pat_XXXX
#      -> roda o `claude mcp add` pronto.
#
#   B) Mintar um PAT (você autentica): no admin logado, ou via API com o SEU token de acesso:
#        # 1. obtenha seu auth_token de admin (login no frontend / fluxo normal)
#        # 2. minte o PAT:
#        curl -s -X POST http://localhost:9999/api/v1/admin/pats \
#             -H "Authorization: Bearer <SEU_AUTH_TOKEN>" \
#             -H "X-Tenant-Id: dataforall" -H "Content-Type: application/json" \
#             -d '{"label":"claude-code-desktop"}'
#        # -> copie o campo "token" (d4all_pat_...) e rode a forma (A).
#
set -euo pipefail

GATEWAY_URL="${GATEWAY_URL:-http://localhost:8090/mcp}"
NAME="${MCP_NAME:-platform-mcp}"
PAT="${1:-}"

if [ -z "$PAT" ]; then
  cat <<EOF
Uso: bash scripts/connect-gateway-desktop.sh <PAT d4all_pat_...>

Sem um PAT ainda? Minte um (você autentica — ver bloco B no topo deste script), depois rode:
  bash scripts/connect-gateway-desktop.sh d4all_pat_SEU_TOKEN

O comando final que será executado:
  claude mcp add --transport http $NAME $GATEWAY_URL --header "Authorization: Bearer <PAT>"
EOF
  exit 0
fi

echo "Registrando '$NAME' no Claude Code (HTTP, $GATEWAY_URL)..."
claude mcp add --transport http "$NAME" "$GATEWAY_URL" --header "Authorization: Bearer $PAT"
echo "OK. Reinicie/abra o Claude Code Desktop e liste as tools — os personas do DevTeam"
echo "(architecture./backend./devops./product-owner./product-manager./qa-engineer./security.*)"
echo "aparecem agregados pelo front-door."
