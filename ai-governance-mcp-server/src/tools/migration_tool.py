"""Tool validate_migration — verifica arquivo de migration Alembic contra §29 AGENTS.md.

O agente lê o arquivo de migration e passa o conteúdo como string. A tool verifica:

  1. Sem operações de ORM (session.add/query, import de modelos)
  2. SQL raw usa op.execute(sa.text(...)) — não string direta
  3. Operações de criação são idempotentes (IF NOT EXISTS)
  4. Nenhum DROP destrutivo dentro da função upgrade()
  5. Função downgrade() existe e não é um no-op (pass/...)
"""

from __future__ import annotations

import re

from ..knowledge.governance_repository import GovernanceRepository
from ..utils.validators import require_non_empty_string

# ---------------------------------------------------------------------- #
# Padrões de verificação                                                  #
# ---------------------------------------------------------------------- #

_ORM_PATTERNS = [
    (r"\bsession\.(add|query|execute|commit|flush|delete)\b", "uso de session ORM"),
    (r"\bdb\.session\b", "uso de db.session"),
    (r"\bBase\.metadata\.(create_all|drop_all)\b", "Base.metadata.create_all/drop_all"),
    (r"from\s+\S+\.models\s+import", "import de models no migration"),
    (r"from\s+app\.(models|db)\b", "import de app.models/db"),
]

_DESTRUCTIVE_UPGRADE_PATTERNS = [
    (r"\bop\.drop_column\b", "op.drop_column"),
    (r"\bop\.drop_table\b", "op.drop_table"),
    (r"\bDROP\s+TABLE\b", "DROP TABLE"),
    (r"\bTRUNCATE\b", "TRUNCATE"),
    (r"\bDELETE\s+FROM\b", "DELETE FROM"),
]

_NOOP_DOWNGRADE_RE = re.compile(
    # Handles plain and annotated signatures: def downgrade(): / def downgrade() -> None:
    r"def\s+downgrade\s*\([^)]*\)[^:]*:\s*\n(?:\s*#[^\n]*)?\s*(?:pass|\.\.\.)\s*$",
    re.MULTILINE,
)

_SA_TEXT_RE = re.compile(r"op\.execute\s*\(\s*sa\.text\s*\(", re.IGNORECASE)
_RAW_STRING_EXECUTE_RE = re.compile(r'op\.execute\s*\(\s*["\']', re.IGNORECASE)
_IF_NOT_EXISTS_RE = re.compile(r"IF\s+NOT\s+EXISTS", re.IGNORECASE)
_CREATE_DESTRUCTIVE_RE = re.compile(
    r"\b(op\.create_table|op\.add_column|CREATE\s+TABLE|ADD\s+COLUMN)\b",
    re.IGNORECASE,
)
_DOWNGRADE_DEF_RE = re.compile(r"def\s+downgrade\s*\(")
_UPGRADE_BODY_RE = re.compile(
    r"def\s+upgrade\s*\([^)]*\)\s*:(.*?)(?=\ndef\s|\Z)", re.DOTALL
)


def _line_of(content: str, pos: int) -> int:
    return content[:pos].count("\n") + 1


# ---------------------------------------------------------------------- #
# validate_migration                                                      #
# ---------------------------------------------------------------------- #

def validate_migration(repo: GovernanceRepository, content: str) -> dict:
    """Valida o conteúdo de um arquivo de migration Alembic contra §29 AGENTS.md.

    Parâmetro `content`: conteúdo completo do arquivo como string.
    O agente deve ler o arquivo e passar o conteúdo — a tool não acessa filesystem.
    """
    require_non_empty_string(content, "content")

    issues: list[str] = []
    warnings: list[str] = []
    info: list[str] = []
    checks: dict[str, bool] = {}

    # ------------------------------------------------------------------ #
    # Check 1 — sem ORM                                                   #
    # ------------------------------------------------------------------ #
    orm_hits: list[str] = []
    for pat, label in _ORM_PATTERNS:
        for m in re.finditer(pat, content, re.IGNORECASE):
            orm_hits.append(f"linha {_line_of(content, m.start())}: {label} ({m.group(0)!r})")
    if orm_hits:
        for hit in orm_hits:
            issues.append(
                f"ORM detectado — {hit}. "
                "Migrations devem usar SQL raw via op.execute(sa.text('...')). §29."
            )
        checks["no_orm_operations"] = False
    else:
        checks["no_orm_operations"] = True
        info.append("✓ Sem operações de ORM detectadas.")

    # ------------------------------------------------------------------ #
    # Check 2 — op.execute usa sa.text, não string direta                 #
    # ------------------------------------------------------------------ #
    raw_str_hits = [
        f"linha {_line_of(content, m.start())}: {m.group(0)!r}"
        for m in _RAW_STRING_EXECUTE_RE.finditer(content)
    ]
    if raw_str_hits:
        for hit in raw_str_hits:
            warnings.append(
                f"op.execute() com string direta — {hit}. "
                "Prefira op.execute(sa.text('...')) para portabilidade entre dialetos. §29."
            )
        checks["uses_sa_text"] = False
    else:
        checks["uses_sa_text"] = True

    checks["uses_raw_sql"] = bool(_SA_TEXT_RE.search(content))
    if checks["uses_raw_sql"]:
        info.append("✓ op.execute(sa.text(...)) encontrado.")

    # ------------------------------------------------------------------ #
    # Check 3 — idempotência                                              #
    # ------------------------------------------------------------------ #
    has_create_op = bool(_CREATE_DESTRUCTIVE_RE.search(content))
    has_if_not_exists = bool(_IF_NOT_EXISTS_RE.search(content))

    if has_create_op and not has_if_not_exists:
        warnings.append(
            "CREATE TABLE / ADD COLUMN sem IF NOT EXISTS. "
            "Migrations devem ser idempotentes — adicione IF NOT EXISTS às operações DDL. §29."
        )
        checks["is_idempotent"] = False
    else:
        checks["is_idempotent"] = True
        if has_if_not_exists:
            info.append("✓ IF NOT EXISTS detectado (idempotência).")

    # ------------------------------------------------------------------ #
    # Check 4 — sem DROP destrutivo na função upgrade()                   #
    # ------------------------------------------------------------------ #
    upgrade_match = _UPGRADE_BODY_RE.search(content)
    upgrade_body = upgrade_match.group(1) if upgrade_match else content

    drop_hits: list[str] = []
    for pat, label in _DESTRUCTIVE_UPGRADE_PATTERNS:
        for m in re.finditer(pat, upgrade_body, re.IGNORECASE):
            # Calcula linha real no arquivo completo
            offset = content.find(upgrade_body)
            real_line = _line_of(content, offset + m.start()) if offset >= 0 else "?"
            drop_hits.append(f"linha {real_line}: {label} ({m.group(0)!r})")

    if drop_hits:
        for hit in drop_hits:
            issues.append(
                f"Operação destrutiva em upgrade() — {hit}. "
                "DROP/TRUNCATE/DELETE em upgrade() pode causar perda de dados. "
                "Use runbook controlado ou mova para downgrade(). §29."
            )
        checks["no_data_destroying_drops"] = False
    else:
        checks["no_data_destroying_drops"] = True
        info.append("✓ Nenhuma operação destrutiva em upgrade().")

    # ------------------------------------------------------------------ #
    # Check 5 — downgrade() existe e não é no-op                         #
    # ------------------------------------------------------------------ #
    has_downgrade = bool(_DOWNGRADE_DEF_RE.search(content))
    noop_downgrade = bool(_NOOP_DOWNGRADE_RE.search(content))

    if not has_downgrade:
        issues.append(
            "Função downgrade() ausente. Toda migration precisa de downgrade reversível. §29."
        )
        checks["has_reversible_downgrade"] = False
    elif noop_downgrade:
        warnings.append(
            "downgrade() parece ser um no-op (pass/...). "
            "Se a operação for genuinamente irreversível, documente o motivo explicitamente "
            "no corpo da função com um comentário. §29."
        )
        checks["has_reversible_downgrade"] = False
    else:
        checks["has_reversible_downgrade"] = True
        info.append("✓ downgrade() presente e não-vazio.")

    # ------------------------------------------------------------------ #
    # Resultado                                                           #
    # ------------------------------------------------------------------ #
    approved = len(issues) == 0
    result: dict = {
        "approved": approved,
        "issues": issues,
        "warnings": warnings,
        "info": info,
        "checks": checks,
    }
    if not approved:
        result["required_actions"] = [
            "Corrigir todos os `issues` antes de abrir PR. "
            "`warnings` são recomendações fortes mas não bloqueiam."
        ]
    else:
        result["notes"] = ["Migration passou em todos os checks críticos do §29."]
    return result
