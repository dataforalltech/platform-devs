"""Modelos de resposta das tools MCP."""

from __future__ import annotations

from pydantic import BaseModel, Field

RISK_LEVELS = ("low", "medium", "high", "critical")


class DecisionValidation(BaseModel):
    """Resultado da tool validate_agent_decision."""

    approved: bool
    risk_level: str = Field(description="low | medium | high | critical")
    violations: list[str] = Field(default_factory=list)
    required_actions: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class SearchHit(BaseModel):
    """Um resultado individual de busca textual."""

    source: str = Field(description="Arquivo de origem na knowledge-base.")
    section: str | None = Field(default=None, description="Heading mais próximo, se existir.")
    snippet: str
    score: float = Field(ge=0.0)
    related_rules: list[str] = Field(default_factory=list)


class SearchResponse(BaseModel):
    """Resposta da tool search_governance_knowledge."""

    query: str
    total: int
    hits: list[SearchHit] = Field(default_factory=list)


class ToolErrorResponse(BaseModel):
    """Resposta padrão para erros de validação ou execução."""

    error: str
    details: str | None = None
    tool: str | None = None
