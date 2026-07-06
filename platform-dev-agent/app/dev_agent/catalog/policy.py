"""Fase 2 — PDP por recurso/efeito + resolver registry-backed.

Duas peças:

- :class:`RegistryCapabilityResolver` — consulta o catálogo (source of truth, ADR-009
  D9.3) para capability/risco; cai na heurística (`CapabilityResolver`) quando o tool
  não está catalogado (migração aditiva, D9.10).
- :class:`PolicyEngine` — decisão de autorização por **effects + blast_radius + domain**
  (ADR-005 PEP/PDP consumindo o metadata do catálogo, ADR-009 D9.5). Deny-by-default.
  O `read/write` do :class:`CapabilityEnforcer` continua sendo o gate grosso; este é o
  refinamento ortogonal que separa `deploy` de `delete_production`.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.dev_agent.capability import CapabilityResolver
from app.dev_agent.catalog.records import (
    CapabilityRecord, CatalogSource, NullCatalogSource, PersonaPolicy,
)
from app.dev_agent.models.plan import Capability, RiskLevel

# Aprovação do catálogo (string) -> RiskLevel só quando não catalogado (fallback).
_APPROVAL_TO_RISK = {"N2": RiskLevel.HIGH, "N1": RiskLevel.MEDIUM, "none": RiskLevel.LOW}


class RegistryCapabilityResolver:
    """Resolve capability/risco preferindo o catálogo; heurística é o fallback."""

    def __init__(self, source: CatalogSource | None = None,
                 heuristic: CapabilityResolver | None = None) -> None:
        self._source = source or NullCatalogSource()
        self._heuristic = heuristic or CapabilityResolver()

    def record(self, tool: str) -> CapabilityRecord | None:
        return self._source.record(tool)

    def resolve(self, tool: str, *, override: str | None = None) -> Capability:
        if override:
            return Capability(override)
        rec = self._source.record(tool)
        if rec is not None:
            return Capability(rec.capability)
        return self._heuristic.resolve(tool)

    def classify_risk(self, tool: str, capability: Capability, *,
                      override: str | None = None) -> RiskLevel:
        if override:
            return RiskLevel(override)
        rec = self._source.record(tool)
        if rec is not None:
            return RiskLevel(rec.risk_level)
        return self._heuristic.classify_risk(tool, capability)


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    approval_required: str = "none"      # none | N1 | N2 (só quando allowed)
    reason: str = ""

    def __bool__(self) -> bool:
        return self.allowed


class PolicyEngine:
    """PDP por recurso/efeito. Deny-by-default; profile ausente = política mínima (só read)."""

    def __init__(self, policies: dict[str, PersonaPolicy] | None = None) -> None:
        self._policies = policies or dict(DEFAULT_POLICIES)
        self._fallback = PersonaPolicy(allowed_effects=frozenset({"read"}), max_blast="none")

    def policy_for(self, profile: str) -> PersonaPolicy:
        # runbook usa "qa-engineer" (hífen); persona id é "qa_engineer" (underscore).
        return self._policies.get(profile.replace("-", "_"), self._fallback)

    def decide(self, *, profile: str, record: CapabilityRecord) -> PolicyDecision:
        pol = self.policy_for(profile)
        # 1) effects ⊆ allowed (a menos que allow_all)
        if not pol.allow_all_effects:
            forbidden = set(record.effects) - set(pol.allowed_effects)
            if forbidden:
                return PolicyDecision(False, reason=(
                    f"profile={profile!r} não permite effect(s) {sorted(forbidden)} "
                    f"(op={record.operation_id!r})"))
        # 2) blast_radius <= teto
        if record.blast_rank > pol.max_blast_rank:
            return PolicyDecision(False, reason=(
                f"profile={profile!r} teto de blast_radius={pol.max_blast!r} < "
                f"{record.blast_radius!r} (op={record.operation_id!r})"))
        # 3) domínio permitido (vazio = todos)
        if pol.allowed_domains and record.domain not in pol.allowed_domains:
            return PolicyDecision(False, reason=(
                f"profile={profile!r} não opera no domínio {record.domain!r}"))
        return PolicyDecision(True, approval_required=record.approval_required,
                              reason="allow")


# Políticas-seed por persona (ADR-009: ajustável; alinhadas às capabilities das 8 personas).
# read-only: security, qa_engineer. gera artefatos (write leve, sem infra): architecture,
# product_owner, product_manager, backend, frontend (teto service). devops: pode deploy (env).
DEFAULT_POLICIES: dict[str, PersonaPolicy] = {
    "security":        PersonaPolicy(frozenset({"read"}), max_blast="none"),
    "qa_engineer":     PersonaPolicy(frozenset({"read"}), max_blast="none"),
    "architecture":    PersonaPolicy(frozenset({"read", "generate", "write"}), max_blast="service"),
    "product_owner":   PersonaPolicy(frozenset({"read", "generate", "write"}), max_blast="service"),
    "product_manager": PersonaPolicy(frozenset({"read", "generate", "write"}), max_blast="service"),
    "backend":         PersonaPolicy(frozenset({"read", "generate", "write"}), max_blast="service"),
    "frontend":        PersonaPolicy(frozenset({"read", "generate", "write"}), max_blast="service"),
    "devops":          PersonaPolicy(
        frozenset({"read", "generate", "write", "deploy", "restart", "build", "execute", "rollback"}),
        max_blast="environment"),
}
