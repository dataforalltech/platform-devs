"""Modelos para sugestões cross-repo.

Uma Suggestion é uma proposta que um agente faz **para outro serviço/repo**
quando, no curso da sua tarefa, percebe algo que melhoraria por lá. Outros
agentes (e humanos) listam, triam, aceitam, rejeitam.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

# Categorias canônicas — fechadas para evitar drift de taxonomia.
SuggestionCategory = Literal[
    "bug",
    "improvement",
    "refactor",
    "security",
    "performance",
    "docs",
    "test",
    "contract",
    "observability",
]

SuggestionSeverity = Literal["low", "medium", "high", "critical"]

SuggestionStatus = Literal[
    "pending",       # acabou de chegar
    "acknowledged",  # alguém viu, ainda não decidiu
    "accepted",      # vai virar trabalho
    "rejected",      # não vai acontecer (com motivo)
    "done",          # implementada
    "duplicate",     # já existe outra sugestão com mesmo conteúdo
]


class StatusChange(BaseModel):
    """Entrada no histórico de status de uma sugestão."""

    ts: str = Field(description="ISO 8601 UTC do momento da mudança.")
    status: SuggestionStatus
    note: str | None = None
    by: str | None = Field(
        default=None, description="Quem mudou — agent id, user, etc."
    )


class Suggestion(BaseModel):
    """Sugestão de correção/melhoria que um agente faz para outro repo.

    Não é um bug-tracker — é o canal para o agente de IA registrar 'enquanto
    eu trabalhava em X, vi que Y precisa disso'. Pode virar issue/PR depois,
    mas não é obrigatório.
    """

    id: str = Field(description="`YYYYMMDDTHHMMSSffffff-XXXXXXXX` (sortable).")
    created_at: str = Field(description="ISO 8601 UTC.")
    source_agent: str = Field(
        description="Identificador do agente que abriu a sugestão (ex.: 'claude-code', 'cursor:caiog')."
    )
    source_repo: str | None = Field(
        default=None,
        description="Repositório onde o agente estava trabalhando quando teve a percepção.",
    )
    target_repo: str = Field(description="Repositório destinatário da sugestão (id canônico do grafo).")
    target_repo_canonical: str | None = Field(
        default=None,
        description="Se o target_repo informado era alias/deprecated, este é o canônico resolvido.",
    )
    category: SuggestionCategory
    severity: SuggestionSeverity
    title: str = Field(description="Linha curta. Imperativa: 'Adicionar timeout em provider X'.")
    description: str = Field(description="Markdown ok. Inclua contexto, evidência, alternativas.")
    related_files: list[str] = Field(
        default_factory=list,
        description="Caminhos relativos no target_repo (ex.: 'app/services/payment.py').",
    )
    references: list[str] = Field(
        default_factory=list,
        description="Links/IDs externos: PR, issue, ADR, commit.",
    )
    status: SuggestionStatus = "pending"
    status_history: list[StatusChange] = Field(default_factory=list)


class SuggestionFilters(BaseModel):
    """Filtros aceitos por list_suggestions."""

    target_repo: str | None = None
    status: SuggestionStatus | None = None
    category: SuggestionCategory | None = None
    severity: SuggestionSeverity | None = None
    source_agent: str | None = None
    limit: int = Field(default=20, ge=1, le=200)
