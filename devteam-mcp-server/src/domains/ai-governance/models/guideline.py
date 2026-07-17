"""Modelos relacionados a diretrizes (guidelines)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class Guideline(BaseModel):
    """Uma diretriz individual."""

    id: str = Field(description="Identificador estável da diretriz, ex.: 'no-silent-fallback'.")
    title: str
    summary: str
    severity: str = Field(default="must", description="must | should | nice-to-have")
    layers: list[str] = Field(default_factory=list)
    source: str = Field(description="Caminho do arquivo de origem na knowledge-base.")


class GuidelineSet(BaseModel):
    """Conjunto de diretrizes retornado por get_agent_guidelines."""

    repository_name: str | None = None
    task_type: str | None = None
    layer: str | None = None
    mandatory_rules: list[str] = Field(default_factory=list)
    forbidden_actions: list[str] = Field(default_factory=list)
    recommended_checklist: list[str] = Field(default_factory=list)
    references: list[str] = Field(default_factory=list)
