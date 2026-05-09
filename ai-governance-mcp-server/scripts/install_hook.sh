#!/usr/bin/env bash
# install_hook.sh — instala o pre-commit hook de ai-governance em um repositório git.
#
# Uso:
#   bash /caminho/para/ai-governance-mcp-server/scripts/install_hook.sh [TARGET_REPO]
#
# Argumentos:
#   TARGET_REPO — path absoluto ou relativo do repositório alvo.
#                 Default: diretório atual.
#
# Variáveis de ambiente opcionais:
#   GOVERNANCE_MCP_SERVER_DIR — path do ai-governance-mcp-server.
#                               Default: diretório pai deste script.
#   PRECOMMIT_BLOCK_ON_HIGH=1 — bloqueia também em risk=high (default: só critical).
#
# O que é instalado:
#   .git/hooks/pre-commit — script que invoca precommit_validate.py via Python
#   (ou acrescenta chamada ao pre-commit existente).
#
# Requisitos no ambiente que roda o hook:
#   - Python 3.11+
#   - mcp[cli] (pip install mcp)
#   - ai-governance-mcp-server instalado (pip install -e /path/to/ai-governance-mcp-server)

set -euo pipefail

# ------------------------------------------------------------------ #
# Utilitários                                                          #
# ------------------------------------------------------------------ #
_green() { printf '\033[0;32m%s\033[0m\n' "$*"; }
_yellow() { printf '\033[1;33m%s\033[0m\n' "$*"; }
_red() { printf '\033[0;31m%s\033[0m\n' "$*"; }
_info() { printf '[install-hook] %s\n' "$*"; }

# ------------------------------------------------------------------ #
# Argumentos                                                          #
# ------------------------------------------------------------------ #
TARGET_REPO="${1:-$(pwd)}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MCP_SERVER_DIR="${GOVERNANCE_MCP_SERVER_DIR:-"$(cd "$SCRIPT_DIR/.." && pwd)"}"
PRECOMMIT_SCRIPT="$MCP_SERVER_DIR/scripts/precommit_validate.py"
BLOCK_ON_HIGH="${PRECOMMIT_BLOCK_ON_HIGH:-0}"

# ------------------------------------------------------------------ #
# Validações                                                           #
# ------------------------------------------------------------------ #
if [[ ! -d "$TARGET_REPO/.git" ]]; then
    _red "Erro: '$TARGET_REPO' não é um repositório git (sem .git/)."
    exit 1
fi

if [[ ! -f "$PRECOMMIT_SCRIPT" ]]; then
    _red "Erro: precommit_validate.py não encontrado em $PRECOMMIT_SCRIPT"
    _red "Verifique GOVERNANCE_MCP_SERVER_DIR ou passe o caminho correto."
    exit 1
fi

if ! python3 -c "import mcp" 2>/dev/null; then
    _yellow "Aviso: pacote 'mcp' não encontrado. Instale: pip install mcp"
    _yellow "O hook será instalado mas não funcionará sem o pacote mcp."
fi

HOOKS_DIR="$TARGET_REPO/.git/hooks"
HOOK_FILE="$HOOKS_DIR/pre-commit"

# ------------------------------------------------------------------ #
# Conteúdo do hook                                                    #
# ------------------------------------------------------------------ #
BLOCK_FLAG=""
if [[ "$BLOCK_ON_HIGH" == "1" ]]; then
    BLOCK_FLAG=" --block-on-high"
fi

HOOK_BLOCK="
# ------- ai-governance pre-commit hook (auto-instalado) -------
GOVERNANCE_MCP_SERVER_DIR=\"$MCP_SERVER_DIR\"
if [ -f \"\$GOVERNANCE_MCP_SERVER_DIR/scripts/precommit_validate.py\" ]; then
    python3 \"\$GOVERNANCE_MCP_SERVER_DIR/scripts/precommit_validate.py\"$BLOCK_FLAG || exit 1
else
    echo \"[ai-governance] WARN: precommit_validate.py não encontrado em \$GOVERNANCE_MCP_SERVER_DIR — pulando.\" >&2
fi
# ------- fim do ai-governance pre-commit hook -------
"

# ------------------------------------------------------------------ #
# Instalação                                                          #
# ------------------------------------------------------------------ #
mkdir -p "$HOOKS_DIR"

if [[ -f "$HOOK_FILE" ]]; then
    # Já existe — verifica se o hook já está instalado.
    if grep -q "ai-governance pre-commit hook" "$HOOK_FILE" 2>/dev/null; then
        _yellow "Hook já instalado em $HOOK_FILE — nada a fazer."
        exit 0
    fi
    # Acrescenta ao hook existente.
    _info "Hook existente encontrado — acrescentando chamada ao ai-governance..."
    echo "$HOOK_BLOCK" >> "$HOOK_FILE"
else
    # Cria um hook novo.
    cat > "$HOOK_FILE" <<'HEADER'
#!/usr/bin/env bash
# pre-commit hook — gerado por install_hook.sh
set -euo pipefail
HEADER
    echo "$HOOK_BLOCK" >> "$HOOK_FILE"
fi

chmod +x "$HOOK_FILE"

_green "✓ Hook instalado em $HOOK_FILE"
_info "MCP server: $MCP_SERVER_DIR"
_info "block_on_high: $BLOCK_ON_HIGH"
_info ""
_info "Para testar manualmente:"
_info "  cd $TARGET_REPO"
_info "  git add <algum arquivo> && python3 $PRECOMMIT_SCRIPT --dry-run"
_info ""
_info "Para desinstalar: remova o bloco entre os marcadores em $HOOK_FILE"
