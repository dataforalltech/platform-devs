"""Modelos para políticas (camada, fallback, contrato, ações proibidas)."""

from __future__ import annotations

from pydantic import BaseModel, Field


class LayerPolicy(BaseModel):
    """Política de uma camada específica."""

    layer: str
    responsibilities: list[str] = Field(default_factory=list)
    can_do: list[str] = Field(default_factory=list)
    cannot_do: list[str] = Field(default_factory=list)
    wrong_examples: list[str] = Field(default_factory=list)
    correct_examples: list[str] = Field(default_factory=list)
    source: str


class FallbackPolicy(BaseModel):
    """Política para o uso de fallback em um cenário."""

    scenario: str
    service_name: str | None = None
    fallback_allowed: bool
    mandatory_conditions: list[str] = Field(default_factory=list)
    required_logs_metrics: list[str] = Field(default_factory=list)
    required_tests: list[str] = Field(default_factory=list)
    required_documentation: list[str] = Field(default_factory=list)
    forbidden_cases: list[str] = Field(default_factory=list)
    rationale: str = ""


class ContractPolicy(BaseModel):
    """Política para alteração de contrato entre serviços."""

    provider_service: str
    consumer_services: list[str] = Field(default_factory=list)
    contract_type: str
    proposed_change: str
    compatibility_rules: list[str] = Field(default_factory=list)
    expected_impacts: list[str] = Field(default_factory=list)
    update_checklist: list[str] = Field(default_factory=list)
    mandatory_tests: list[str] = Field(default_factory=list)
    mandatory_documentation: list[str] = Field(default_factory=list)
    risk_level: str = "medium"


class ForbiddenAction(BaseModel):
    """Uma ação proibida com motivo e alternativa correta."""

    id: str
    action: str
    reason: str
    correct_alternative: str
    applies_to: list[str] = Field(default_factory=list)
