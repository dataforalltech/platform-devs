"""Fase 2 — consumo do Capability Registry (Fase 1) + PDP por recurso/efeito."""

from app.dev_agent.catalog.policy import (
    DEFAULT_POLICIES, PolicyDecision, PolicyEngine, RegistryCapabilityResolver,
)
from app.dev_agent.catalog.records import (
    CapabilityRecord, CatalogSource, DirCatalogSource, InMemoryCatalogSource,
    NullCatalogSource, PersonaPolicy,
)

__all__ = [
    "CapabilityRecord", "CatalogSource", "DirCatalogSource", "InMemoryCatalogSource",
    "NullCatalogSource", "PersonaPolicy", "RegistryCapabilityResolver", "PolicyEngine",
    "PolicyDecision", "DEFAULT_POLICIES",
]
