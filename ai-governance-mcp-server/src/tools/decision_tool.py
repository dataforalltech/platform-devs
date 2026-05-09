"""Tool validate_agent_decision — bloqueia ou marca como alto risco decisões perigosas.

A política implementada aqui é deliberadamente **conservadora**:

- Quando detecta sinal claro de proibição (fallback silencioso, bypass de auth,
  mock em prod, hardcoded de credencial) — `approved=False` e `risk_level=critical`.
- Quando detecta sinal de risco (alteração de contrato sem consumidor declarado,
  dependência nova sem justificativa, mudanças fora do escopo) — `risk_level=high`
  com `required_actions` que precisam ser cumpridas.
- Quando o sinal é fraco — devolve `recommendations` mas não bloqueia.

A ideia é que o agente chame esta tool ANTES de fazer a alteração, e refaça a
proposta caso seja reprovada.
"""

from __future__ import annotations

import re

from ..knowledge.governance_repository import GovernanceRepository
from ..utils.validators import (
    coerce_bool,
    coerce_string_list,
    require_non_empty_string,
)

# ---------------------------------------------------------------------- #
# Padrões textuais que disparam regras                                   #
# ---------------------------------------------------------------------- #

_SILENT_FALLBACK_PATTERNS = [
    r"\btry\s*:\s*[^\n]*\n[\s\S]{0,200}?except\s*[^\n]*:\s*pass\b",
    r"\bcatch\s*\(?[^)]*\)?\s*\{\s*\}",  # JS catch vazio
    r"\bcatch\s*\(?[^)]*\)?\s*\{\s*return\s+\{[^}]*-1[^}]*\}",  # retorno -1 fake
    r"\bexcept\b[^\n]*:\s*return\s+(true|true\s*,|none|\{\s*\}|\[\s*\])",
    r"\bsilent\s*fallback\b",
    r"fallback\s+silencioso",
]

_HARDCODED_PATTERNS = [
    r"\b(api_key|apikey|access_token|secret|password)\s*=\s*['\"][^'\"]{6,}['\"]",
    r"https?://[a-zA-Z0-9.\-]+\.(com|net|io|cloud|app)[/\"'\s]",
    r"\btoken\s*=\s*['\"][a-zA-Z0-9\-_]{16,}['\"]",
    r"sk-[a-zA-Z0-9]{16,}",  # ex.: openai key
]

_AUTH_BYPASS_PATTERNS = [
    r"skip[_-]?auth",
    r"x[-_]skip[-_]auth",
    r"\bbypass\s+auth",
    r"disable\s+authentication",
    r"@?\s*(no_auth|public_route|skip_authorization)",
]

_MOCK_IN_PROD_PATTERNS = [
    r"\bMockProvider\b",
    r"\bFakeService\b",
    r"return\s+(mock|fake|stub)_",
    r"if\s+os\.getenv\(['\"]USE_MOCK['\"]\)",
]

_CROSS_LAYER_HINTS = {
    "frontend_fixing_backend": [
        r"esconder\s+(o\s+)?erro\s+do\s+(backend|api)",
        r"hide\s+(the\s+)?backend\s+error",
        r"corrigir\s+bug\s+do\s+backend\s+no\s+frontend",
        r"workaround\s+(in|no)\s+frontend\s+(for|para)\s+(api|backend)",
    ],
    "backend_fixing_frontend": [
        r"formatar\s+mensagem\s+(de|para)\s+UI",
        r"backend\s+(retornando|returning)\s+texto\s+formatado\s+(para|for)\s+(tela|UI)",
        r"backend\s+resolvendo\s+problema\s+de\s+(frontend|UI)",
    ],
}

_SCOPE_DRIFT_PATTERNS = [
    r"refator(ei|ar|ando)\s+(também|tambem|de\s+quebra)",
    r"aproveit(ei|ar|ando)\s+para\s+(refatorar|limpar|reescrever)",
    r"while\s+i\s+was\s+(here|there)",
    r"de\s+quebra",
]

_DELETE_TEST_PATTERNS = [
    r"removi\s+(o\s+)?teste",
    r"apaguei\s+(o\s+)?teste",
    r"delet(ei|ed)\s+(the\s+)?test",
    r"@pytest\.mark\.skip",
    r"\.skip\(.+\)",
]

# Detecção de adição de dependência. ADR-0004: o 4º padrão antes era
# `requirements\.txt|package\.json|pyproject\.toml` — match literal puro
# disparava em qualquer string contendo o nome do manifesto, mesmo em
# docstrings ou comentários (falso positivo do dogfood). Agora exigimos
# verbo de modificação dentro de uma janela de 60 chars antes da menção.
_DEPENDENCY_PATTERNS = [
    r"add(ed|ing)?\s+(dependency|biblioteca|lib|package)",
    r"adicion(ei|ar|ando)\s+(dependência|dependencia|biblioteca|lib)",
    r"new\s+dependency",
    # Verbo PT/EN de modificação + nome de manifesto a até 60 chars de distância.
    r"(?:adicion(?:ei|ar|ando|ado)|inclu[ií](?:r|ndo|do)|colocar|put|inserir|"
    r"add(?:ed|ing)?|new|incluindo|requer(?:ido|er)?|require[ds]?|pin(?:ned)?|"
    r"upgrad(?:e|ed|ing)|bump(?:ed|ing)?)\b[\s\S]{0,60}?"
    r"(?:requirements\.txt|package\.json|pyproject\.toml|poetry\.lock)",
]

_PREMATURE_ABSTRACTION_PATTERNS = [
    r"crie?i?\s+(uma\s+)?factory",
    r"crie?i?\s+(uma\s+)?abstração",
    r"created?\s+(a\s+)?factory",
    r"created?\s+(an?\s+)?abstraction",
    r"interface\s+gen[ée]rica",
    r"para\s+ficar\s+gen[ée]rico",
]


# Marcadores de negação que invalidam um match no contexto imediato.
# Cobertura: PT (não, sem, nunca, jamais) e EN (no, not, never, don't, didn't, doesn't).
_NEGATION_RE = re.compile(
    r"\b(n[aã]o|sem|nunca|jamais|no|not|never|don['’]?t|didn['’]?t|doesn['’]?t|do\s+not|did\s+not)\b",
    re.IGNORECASE,
)


def _is_negated(text: str, match_start: int, window: int = 40) -> bool:
    """Devolve True se há negação a até `window` chars antes do match,
    sem cruzar fronteira de sentença (`.`, `;`, `\n`).
    Evita falsos positivos do tipo 'Não removi teste; ao contrário, criei 40'.
    """
    snippet_start = max(0, match_start - window)
    snippet = text[snippet_start:match_start]
    # Não atravessar fim de sentença anterior.
    boundary = max(snippet.rfind("."), snippet.rfind(";"), snippet.rfind("\n"))
    if boundary >= 0:
        snippet = snippet[boundary + 1:]
    return bool(_NEGATION_RE.search(snippet))


def _matches_any(text: str, patterns: list[str]) -> bool:
    """True se qualquer pattern casa no texto e não está negado no contexto imediato."""
    text_norm = text or ""
    for pat in patterns:
        for match in re.finditer(pat, text_norm, re.IGNORECASE | re.MULTILINE):
            if not _is_negated(text_norm, match.start()):
                return True
    return False


def _bump_risk(current: str, new: str) -> str:
    order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    return new if order[new] > order[current] else current


def validate_agent_decision(
    repo: GovernanceRepository,
    repository_name: str,
    task_description: str,
    proposed_change: str,
    affected_files: list[str] | str | None = None,
    affected_layers: list[str] | str | None = None,
    changes_contracts: bool | str | None = False,
    adds_fallback: bool | str | None = False,
    adds_dependency: bool | str | None = False,
    modifies_security: bool | str | None = False,
) -> dict:
    """Valida a decisão proposta. Devolve approved/risk_level/violations/required_actions."""
    require_non_empty_string(repository_name, "repository_name")
    require_non_empty_string(task_description, "task_description")
    require_non_empty_string(proposed_change, "proposed_change")

    files = coerce_string_list(affected_files)
    layers = [layer.lower() for layer in coerce_string_list(affected_layers)]
    flag_contracts = coerce_bool(changes_contracts)
    flag_fallback = coerce_bool(adds_fallback)
    flag_dependency = coerce_bool(adds_dependency)
    flag_security = coerce_bool(modifies_security)

    # Texto agregado para busca de padrões.
    blob = "\n".join([task_description, proposed_change])

    violations: list[str] = []
    required_actions: list[str] = []
    recommendations: list[str] = []
    notes: list[str] = []
    risk = "low"
    approved = True

    # ------------------------------------------------------------------ #
    # CRITICAL — bloqueio imediato                                        #
    # ------------------------------------------------------------------ #
    if _matches_any(blob, _SILENT_FALLBACK_PATTERNS):
        violations.append(
            "Fallback silencioso detectado (try/except retornando estado fake ou pass). "
            "Proibido pelo AGENTS.md §2/§4."
        )
        required_actions.append(
            "Remover o fallback silencioso. Propagar a exceção com contexto, logar com "
            "log.exception(...), emitir métrica e tratar explicitamente no caller."
        )
        approved = False
        risk = _bump_risk(risk, "critical")

    if flag_fallback and not re.search(
        r"(log\.warning|log\.exception|metrics?\.|alerta|alert)", blob, re.IGNORECASE
    ):
        violations.append(
            "adds_fallback=True mas a descrição não menciona log/métrica/alerta. "
            "Fallback sem observabilidade é silencioso."
        )
        required_actions.append(
            "Adicionar log.warning('fallback_triggered', ...), métrica de fallback e alerta. "
            "Ver fallback.md."
        )
        approved = False
        risk = _bump_risk(risk, "critical")

    if _matches_any(blob, _HARDCODED_PATTERNS):
        violations.append(
            "Valor que parece credencial/URL/token hardcoded na proposta. "
            "Proibido pelo AGENTS.md §2."
        )
        required_actions.append(
            "Mover o valor para configuração (env var via Settings tipado / cofre)."
        )
        approved = False
        risk = _bump_risk(risk, "critical")

    if _matches_any(blob, _AUTH_BYPASS_PATTERNS) or (
        flag_security and re.search(r"bypass|skip.?auth|disable.?auth", blob, re.IGNORECASE)
    ):
        violations.append(
            "Bypass de autenticação/autorização detectado. Proibido sem ADR explícito de segurança."
        )
        required_actions.append(
            "Remover o bypass. Se a rota precisa ser pública, abrir ADR e revisão de segurança."
        )
        approved = False
        risk = _bump_risk(risk, "critical")

    if _matches_any(blob, _MOCK_IN_PROD_PATTERNS):
        violations.append(
            "Mock/Fake/Stub aparentemente em código produtivo. Proibido pelo AGENTS.md §2."
        )
        required_actions.append(
            "Remover mock de código produtivo. Mocks só em código de teste."
        )
        approved = False
        risk = _bump_risk(risk, "critical")

    if _matches_any(blob, _DELETE_TEST_PATTERNS):
        violations.append(
            "Indicação de remoção/skip de teste para resolver problema. Proibido."
        )
        required_actions.append(
            "Restaurar o teste. Se o teste estava errado, abrir PR explicando a correção do teste."
        )
        approved = False
        risk = _bump_risk(risk, "critical")

    # ------------------------------------------------------------------ #
    # HIGH — não bloqueia mas exige ação                                  #
    # ------------------------------------------------------------------ #
    for layer_pair, patterns in _CROSS_LAYER_HINTS.items():
        if _matches_any(blob, patterns):
            violations.append(
                f"Possível cross-layer fix detectado ({layer_pair}). Resolva na camada responsável."
            )
            required_actions.append(
                "Identificar a camada certa para a correção e refazer a proposta."
            )
            risk = _bump_risk(risk, "high")

    if flag_contracts:
        consumers_mentioned = re.search(
            r"(consumidor|consumer|cliente do serviço|client of)", blob, re.IGNORECASE
        )
        if not consumers_mentioned:
            violations.append(
                "changes_contracts=True mas a proposta não cita consumidores impactados."
            )
            required_actions.append(
                "Listar consumidores afetados (grep no monorepo + lista de serviços). "
                "Ver contracts.md."
            )
            risk = _bump_risk(risk, "high")
        else:
            recommendations.append(
                "Garanta versionamento e testes de contrato antes do merge (contracts.md)."
            )
            risk = _bump_risk(risk, "medium")

    if flag_dependency or _matches_any(blob, _DEPENDENCY_PATTERNS):
        justification = re.search(
            r"(justific|porque|because|necessária|necessario|preciso|need(ed)?\s+to)",
            blob,
            re.IGNORECASE,
        )
        if not justification:
            violations.append(
                "Nova dependência sem justificativa explícita."
            )
            required_actions.append(
                "Justificar a dependência: por que ela? alternativas avaliadas? supply chain ok?"
            )
            risk = _bump_risk(risk, "high")
        else:
            recommendations.append(
                "Documente a dependência no PR (motivação, versão fixa, licença)."
            )

    if _matches_any(blob, _SCOPE_DRIFT_PATTERNS):
        violations.append(
            "Indicação de alteração fora do escopo da tarefa ('de quebra', 'aproveitei para...')."
        )
        required_actions.append(
            "Reduzir o PR ao escopo declarado. Refactors amplos vão em PR dedicado."
        )
        risk = _bump_risk(risk, "high")

    if _matches_any(blob, _PREMATURE_ABSTRACTION_PATTERNS):
        recommendations.append(
            "Abstração prematura tem alto custo. Confirme que há ≥3 usos reais antes de criar factory/interface."
        )
        risk = _bump_risk(risk, "medium")

    # ------------------------------------------------------------------ #
    # Heurísticas por camada                                              #
    # ------------------------------------------------------------------ #
    if "integrations" in layers:
        if not re.search(r"(timeout|retry|circuit)", blob, re.IGNORECASE):
            violations.append(
                "Camada 'integrations' afetada mas timeout/retry/circuit-breaker não mencionados."
            )
            required_actions.append(
                "Definir timeout, retry e estratégia de falha. Ver integrations.md + fallback.md."
            )
            risk = _bump_risk(risk, "high")
        if not re.search(r"(log\.|metric|metrica|métrica|trace)", blob, re.IGNORECASE):
            violations.append(
                "Camada 'integrations' afetada sem observabilidade declarada (log/métrica)."
            )
            required_actions.append(
                "Adicionar log estruturado e métrica. Ver observability.md."
            )
            risk = _bump_risk(risk, "high")

    if "database" in layers:
        if re.search(r"\b(drop\s+table|truncate|delete\s+from)\b", blob, re.IGNORECASE):
            violations.append(
                "Operação destrutiva em banco (DROP/TRUNCATE/DELETE FROM) detectada. "
                "Não pode ir em código de aplicação."
            )
            required_actions.append(
                "Mover operação destrutiva para runbook controlado. Ver database.md."
            )
            risk = _bump_risk(risk, "critical")
            approved = False
        if not re.search(r"(migration|alembic|reversível|reversivel)", blob, re.IGNORECASE):
            recommendations.append(
                "Alterações em banco devem ir por migration versionada e reversível."
            )
            risk = _bump_risk(risk, "medium")

    if "security" in layers and flag_security:
        recommendations.append(
            "Mudanças de segurança exigem revisão humana (security.md)."
        )
        risk = _bump_risk(risk, "high")

    # ------------------------------------------------------------------ #
    # Sinais informativos                                                 #
    # ------------------------------------------------------------------ #
    if not files:
        notes.append(
            "affected_files vazio — tarefas reais sempre têm um conjunto limitado de arquivos."
        )
        risk = _bump_risk(risk, "medium")
    if len(files) > 30:
        notes.append(
            f"affected_files muito grande ({len(files)}). PRs grandes são mais arriscados."
        )
        risk = _bump_risk(risk, "medium")

    if not violations:
        recommendations.append(
            "Antes do merge: rodar testes, verificar checklist de resposta final (final-response-format.md)."
        )

    return {
        "approved": approved,
        "risk_level": risk,
        "violations": violations,
        "required_actions": required_actions,
        "recommendations": recommendations,
        "notes": notes,
        "input_summary": {
            "repository_name": repository_name,
            "task_description": task_description,
            "affected_files_count": len(files),
            "affected_layers": layers,
            "changes_contracts": flag_contracts,
            "adds_fallback": flag_fallback,
            "adds_dependency": flag_dependency,
            "modifies_security": flag_security,
        },
    }
