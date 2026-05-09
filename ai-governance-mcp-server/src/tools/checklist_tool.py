"""Tools de checklist final / template de resposta de agente."""

from __future__ import annotations

from ..knowledge.governance_repository import GovernanceRepository
from ..utils.validators import normalize_task_type

_BASE_SECTIONS = [
    "what_changed",
    "why",
    "files_modified",
    "risks",
    "tests_executed",
    "tests_skipped_and_why",
    "impact_on_other_services",
    "pending_items",
]


def get_final_response_template(
    repo: GovernanceRepository,
    task_type: str | None = None,
) -> dict:
    """Devolve o template obrigatório de resposta final do agente."""
    task_norm = normalize_task_type(task_type)

    sections = [
        {
            "key": "what_changed",
            "label": "O que foi alterado",
            "required": True,
            "guidance": (
                "Descrição objetiva do que mudou. Evitar 'refatorei várias coisas'. "
                "Liste os comportamentos novos/alterados em bullets curtos."
            ),
        },
        {
            "key": "why",
            "label": "Por que foi alterado",
            "required": True,
            "guidance": "Motivação: bug, requisito, ADR, ticket. Cite a fonte (issue/ADR/conversa).",
        },
        {
            "key": "files_modified",
            "label": "Arquivos modificados",
            "required": True,
            "guidance": "Lista exata. Sem 'tudo em src/'. Cada arquivo com 1 linha do que mudou nele.",
        },
        {
            "key": "risks",
            "label": "Riscos",
            "required": True,
            "guidance": (
                "Riscos conhecidos (regressão potencial, breaking change, performance, segurança). "
                "Se nenhum, escrever 'nenhum identificado' explicitamente."
            ),
        },
        {
            "key": "tests_executed",
            "label": "Testes executados",
            "required": True,
            "guidance": "Comandos rodados e resultado (passed/failed). Inclui unit + integration + lint/types.",
        },
        {
            "key": "tests_skipped_and_why",
            "label": "Testes não executados e motivo",
            "required": True,
            "guidance": (
                "Liste cada teste/etapa não executada e o motivo (faltou ambiente, dado, "
                "tempo, etc). 'Nenhum' é resposta válida — mas só se for verdade."
            ),
        },
        {
            "key": "impact_on_other_services",
            "label": "Impacto em outros serviços",
            "required": True,
            "guidance": (
                "Quais serviços/repositórios são afetados? Contratos quebrados? "
                "Consumidores que precisam atualizar? 'Nenhum' é válido se justificado."
            ),
        },
        {
            "key": "pending_items",
            "label": "Pendências",
            "required": True,
            "guidance": (
                "O que ficou para depois e por quê. Inclui: deploy manual, comunicação a "
                "outros times, ADR pendente, testes manuais a fazer."
            ),
        },
    ]

    if task_norm == "bugfix":
        sections.append(
            {
                "key": "regression_test",
                "label": "Teste de regressão",
                "required": True,
                "guidance": "Aponte o teste que falharia antes do fix. Bugfix sem regressão é incompleto.",
            }
        )
    if task_norm == "migration":
        sections.append(
            {
                "key": "rollback_plan",
                "label": "Plano de rollback",
                "required": True,
                "guidance": "Como reverter a migration se der ruim. Comando exato.",
            }
        )
    if task_norm == "refactor":
        sections.append(
            {
                "key": "behavior_unchanged",
                "label": "Comportamento inalterado",
                "required": True,
                "guidance": (
                    "Refactor não muda comportamento observável. Liste o que foi feito para "
                    "garantir isso (mesmos testes passando, snapshot, etc.)."
                ),
            }
        )

    template_markdown = _render_markdown_template(sections)

    return {
        "task_type": task_norm,
        "section_order": [s["key"] for s in sections],
        "sections": sections,
        "template_markdown": template_markdown,
    }


def _render_markdown_template(sections: list[dict]) -> str:
    lines = ["## Resposta final do agente", ""]
    for section in sections:
        lines.append(f"### {section['label']}")
        lines.append(f"<!-- {section['guidance']} -->")
        lines.append("")
        lines.append("- ...")
        lines.append("")
    return "\n".join(lines).strip() + "\n"
