"""Tools de diretrizes e checklist pré-execução."""

from __future__ import annotations

from ..knowledge.governance_repository import GovernanceRepository
from ..utils.validators import normalize_layer, normalize_task_type, safe_lower

# Diretrizes universais — sempre se aplicam, independentemente da tarefa.
_UNIVERSAL_MANDATORY = [
    "Ler AGENTS.md, README.md e ADRs do repositório antes de qualquer alteração.",
    "Não alterar arquivos fora do escopo da tarefa.",
    "Não modificar contratos (API, eventos, schemas) sem coordenar com consumidores.",
    "Não criar abstrações, helpers ou factories sem necessidade direta da tarefa.",
    "Manter PRs pequenos, focados e reversíveis.",
    "Respeitar padrões existentes (estilo, libs, naming) do repositório.",
]

_UNIVERSAL_FORBIDDEN = [
    "Fallback silencioso para 'fazer funcionar'.",
    "Hardcoded de credenciais, URLs, IDs ou tokens.",
    "Mock em código produtivo.",
    "Apagar testes para fazer build passar.",
    "Pular hooks de pré-commit ou CI (`--no-verify`).",
    "Misturar responsabilidades entre camadas (frontend resolvendo bug de backend, etc.).",
    "Try/except genérico engolindo erros de integração.",
]

_UNIVERSAL_CHECKLIST = [
    "Confirmei o escopo exato da tarefa.",
    "Li o AGENTS.md do repositório.",
    "Identifiquei contratos afetados (API, eventos, schemas).",
    "Identifiquei consumidores impactados.",
    "Defini logs/métricas necessários.",
    "Defini os testes que vou rodar.",
    "Listei pendências e riscos no formato de resposta final.",
]


_LAYER_EXTRA_RULES = {
    "frontend": [
        "Validação no frontend é UX; backend valida sempre.",
        "Não inventar regra de negócio — frontend é consumidor de contrato.",
        "URLs, tokens e IDs vêm de configuração, nunca hardcoded.",
    ],
    "backend": [
        "Toda rota deve estar documentada via OpenAPI.",
        "Toda integração externa precisa de retry, timeout e log estruturado.",
        "Não vazar UX para a API (mensagens de erro genéricas, contratos estáveis).",
    ],
    "database": [
        "Toda alteração de schema vai por migração versionada (ex.: Alembic).",
        "Migrations devem ser reversíveis quando possível.",
        "Nunca rodar `DROP`/`TRUNCATE` em código de aplicação.",
    ],
    "integrations": [
        "Definir comportamento em caso de falha do parceiro (ver fallback.md).",
        "Logar request_id, tenant_id e correlation_id em toda chamada.",
        "Timeout e retry são obrigatórios.",
    ],
    "infrastructure": [
        "Mudanças em CI/CD ou infra exigem aprovação humana.",
        "Não alterar `.gitignore`, `pyproject.toml` ou `package.json` sem necessidade da tarefa.",
        "Secrets vêm de cofre (não commitar nada sensível).",
    ],
    "security": [
        "Nunca enfraquecer auth/autz para resolver bug.",
        "Toda rota é autenticada por padrão; rotas públicas exigem ADR.",
        "Logs nunca contêm credenciais, PII bruta ou tokens.",
    ],
    "observability": [
        "Toda integração crítica precisa de log estruturado + métrica + alerta.",
        "request_id, tenant_id e correlation_id são obrigatórios em logs.",
        "Erros silenciosos são bug, não feature.",
    ],
    "testing": [
        "Não apagar testes existentes para verde no CI.",
        "Bugfix sem teste de regressão é incompleto.",
        "Testes de integração com banco real (não mock) quando o bug envolve persistência.",
    ],
}


def get_agent_guidelines(
    repo: GovernanceRepository,
    repository_name: str | None = None,
    task_type: str | None = None,
    layer: str | None = None,
) -> dict:
    """Devolve diretrizes aplicáveis ao contexto."""
    layer_norm = normalize_layer(layer)
    task_norm = normalize_task_type(task_type)
    repo_name = safe_lower(repository_name)

    mandatory = list(_UNIVERSAL_MANDATORY)
    forbidden = list(_UNIVERSAL_FORBIDDEN)
    checklist = list(_UNIVERSAL_CHECKLIST)

    if layer_norm:
        mandatory.extend(_LAYER_EXTRA_RULES.get(layer_norm, []))

    if task_norm == "migration":
        mandatory.append("Migration deve ser reversível e testada em ambiente de homologação.")
        checklist.append("Plano de rollback documentado.")
    if task_norm == "bugfix":
        mandatory.append("Adicionar teste de regressão que falharia antes do fix.")
        checklist.append("Teste de regressão escrito e verde.")
    if task_norm == "refactor":
        mandatory.append(
            "Refactor não muda comportamento observável — cobertura de testes deve ficar igual ou maior."
        )

    references = [
        "AGENTS.md",
        "forbidden-actions.md",
        "final-response-format.md",
    ]
    if layer_norm:
        references.append(f"{layer_norm}.md")

    return {
        "repository_name": repo_name,
        "task_type": task_norm,
        "layer": layer_norm,
        "mandatory_rules": mandatory,
        "forbidden_actions": forbidden,
        "recommended_checklist": checklist,
        "references": references,
    }


def get_pre_execution_checklist(
    repo: GovernanceRepository,
    repository_name: str,
    task_description: str,
    layer: str | None = None,
) -> dict:
    """Checklist a executar ANTES de tocar em qualquer arquivo."""
    if not repository_name or not isinstance(repository_name, str):
        raise ValueError("repository_name é obrigatório")
    if not task_description or not isinstance(task_description, str):
        raise ValueError("task_description é obrigatório")

    layer_norm = normalize_layer(layer)
    desc_lower = task_description.lower()

    pre_checklist = [
        "Li AGENTS.md (ou equivalente local) deste repositório.",
        "Li README.md do repositório.",
        "Identifiquei o(s) arquivo(s) que precisam ser alterados (sem listar 'tudo').",
        "Confirmei que a tarefa cabe em um único PR pequeno.",
        "Verifiquei se há ADR relevante em docs/decisions/.",
    ]

    docs_to_read = ["AGENTS.md", "README.md"]
    questions = [
        "Esta tarefa altera contrato com outro serviço?",
        "Esta tarefa precisa de migration de banco?",
        "Esta tarefa exige novos logs ou métricas?",
        "Esta tarefa requer atualização de testes existentes?",
    ]
    expected_risks: list[str] = []

    if layer_norm == "backend":
        docs_to_read.append("backend.md")
        questions.append("A rota a ser alterada está documentada via OpenAPI?")
        expected_risks.append("Quebra de contrato com frontend ou outro serviço.")
    if layer_norm == "frontend":
        docs_to_read.append("frontend.md")
        questions.append("Há tratamento de loading/erro/vazio no componente afetado?")
    if layer_norm == "database":
        docs_to_read.append("database.md")
        questions.append("A migration é reversível?")
        expected_risks.append("Lock prolongado em tabela grande durante migration.")
    if layer_norm == "integrations":
        docs_to_read.append("integrations.md")
        docs_to_read.append("fallback.md")
        questions.append("O comportamento em caso de falha do parceiro está definido?")
        expected_risks.append("Parceiro indisponível derruba fluxo crítico.")
    if layer_norm == "security":
        docs_to_read.append("security.md")
        expected_risks.append("Enfraquecimento acidental de autenticação.")
    if layer_norm == "observability":
        docs_to_read.append("observability.md")
    if layer_norm == "testing":
        docs_to_read.append("testing.md")
    if layer_norm == "infrastructure":
        docs_to_read.append("infrastructure.md")

    if "fallback" in desc_lower:
        docs_to_read.append("fallback.md")
        questions.append("O fallback é silencioso? (se sim: PARE.)")
        expected_risks.append("Fallback silencioso mascarando falha de upstream.")
    if "contrato" in desc_lower or "contract" in desc_lower or "api" in desc_lower:
        docs_to_read.append("contracts.md")
        questions.append("Quais consumidores serão impactados?")
        expected_risks.append("Quebra de compatibilidade não detectada em CI.")
    if "auth" in desc_lower or "login" in desc_lower or "permiss" in desc_lower:
        docs_to_read.append("security.md")
        expected_risks.append("Bypass acidental de autenticação ou autorização.")

    return {
        "repository_name": repository_name,
        "task_description": task_description,
        "layer": layer_norm,
        "checklist": pre_checklist,
        "docs_to_read": _dedupe_preserve(docs_to_read),
        "questions_to_answer": _dedupe_preserve(questions),
        "expected_risks": _dedupe_preserve(expected_risks),
    }


def _dedupe_preserve(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            out.append(item)
            seen.add(item)
    return out
