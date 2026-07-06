"""Fase 2 — o agente consome o Capability Registry (Fase 1) como source of truth.

Um :class:`CapabilityRecord` é a projeção, para o runtime, de uma Operation do
catálogo: capability (read/write), risco, **effects**, **blast_radius** e
**approval_required**. As fontes (:class:`CatalogSource`) entregam esse record por
tool (``<provider>.<operationId>``); quando o tool não está no catálogo, o resolver
cai na heurística (migração aditiva — ADR-009 D9.10).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol, runtime_checkable

_BLAST_RANK = {"none": 0, "workspace": 1, "service": 2, "environment": 3, "tenant": 4, "global": 5}


@dataclass(frozen=True)
class CapabilityRecord:
    """Projeção de uma Operation do catálogo para decisões do runtime."""

    tool: str                       # "<provider>.<operationId>"
    operation_id: str               # uid da Operation (ex.: "delivery.deploy")
    domain: str
    capability: str                 # read | write
    risk_level: str                 # low | medium | high | critical
    effects: tuple[str, ...] = ()
    blast_radius: str = "service"
    approval_required: str = "none"  # none | N1 | N2
    resource: str = "generic"

    @property
    def blast_rank(self) -> int:
        return _BLAST_RANK.get(self.blast_radius, 2)


@runtime_checkable
class CatalogSource(Protocol):
    """Fonte de records por tool/Operation. Retorna ``None`` se não catalogado."""

    def record(self, tool: str) -> CapabilityRecord | None: ...

    def record_for_operation(self, operation_id: str) -> CapabilityRecord | None:
        """Record da Operation (capability/risco idênticos entre seus bindings)."""
        ...

    def tool_for_operation(self, operation_id: str) -> str | None:
        """Tool key concreta (``<provider>.<op>``) que implementa a Operation.

        Escolha DETERMINÍSTICA (``min()`` das candidatas) para estabilidade.
        """
        ...


class InMemoryCatalogSource:
    """Fonte para testes / composição direta."""

    def __init__(self, records: dict[str, CapabilityRecord] | None = None) -> None:
        self._by_tool = dict(records or {})

    def add(self, rec: CapabilityRecord) -> None:
        self._by_tool[rec.tool] = rec

    def record(self, tool: str) -> CapabilityRecord | None:
        return self._by_tool.get(tool)

    def record_for_operation(self, operation_id: str) -> CapabilityRecord | None:
        # capability/risco são idênticos entre bindings de uma Operation; devolve
        # o record da tool determinística (min) para consistência com o pick.
        tool = self.tool_for_operation(operation_id)
        return self._by_tool.get(tool) if tool is not None else None

    def tool_for_operation(self, operation_id: str) -> str | None:
        candidates = [k for k, r in self._by_tool.items() if r.operation_id == operation_id]
        return min(candidates) if candidates else None


class NullCatalogSource:
    """Catálogo vazio → tudo cai na heurística (default seguro se o registry não existe)."""

    def record(self, tool: str) -> CapabilityRecord | None:  # noqa: ARG002
        return None

    def record_for_operation(self, operation_id: str) -> CapabilityRecord | None:  # noqa: ARG002
        return None

    def tool_for_operation(self, operation_id: str) -> str | None:  # noqa: ARG002
        return None


class DirCatalogSource:
    """Lê o catálogo YAML da Fase 1 (``platform-catalog/catalog/``) e indexa por
    ``<provider>.<operationId>`` casando Tool bindings com suas Operations.

    Caminho: ``DEV_CATALOG_DIR`` ou, por padrão, ``<repo>/platform-catalog/catalog``.
    Se o diretório não existir, comporta-se como catálogo vazio (fallback).
    """

    def __init__(self, catalog_dir: str | os.PathLike | None = None) -> None:
        self._dir = Path(catalog_dir) if catalog_dir else self._default_dir()
        self._by_tool: dict[str, CapabilityRecord] = {}
        self._by_operation: dict[str, CapabilityRecord] = {}
        self._tool_for_operation: dict[str, str] = {}
        self._loaded = False

    @staticmethod
    def _default_dir() -> Path:
        env = os.getenv("DEV_CATALOG_DIR")
        if env:
            return Path(env)
        # app/dev_agent/catalog/records.py -> parents[4] = repo root
        return Path(__file__).resolve().parents[4] / "platform-catalog" / "catalog"

    def _load(self) -> None:
        import yaml  # dep local (pyyaml)

        self._loaded = True
        ops_dir, tools_dir = self._dir / "operations", self._dir / "tools"
        if not ops_dir.exists() or not tools_dir.exists():
            return
        # owned + external (Fase 1.1) — tools federadas resolvem igual às próprias.
        op_files = list(ops_dir.glob("*.yaml")) + list((self._dir / "external" / "operations").glob("*.yaml"))
        tool_files = list(tools_dir.glob("*.yaml")) + list((self._dir / "external" / "tools").glob("*.yaml"))
        ops = {}
        for f in op_files:
            e = yaml.safe_load(f.read_text(encoding="utf-8"))
            ops[e["metadata"]["uid"]] = e
        for f in tool_files:
            t = yaml.safe_load(f.read_text(encoding="utf-8"))
            spec = t["spec"]
            op = ops.get(spec["operation_id"])
            if op is None:
                continue
            os_ = op["spec"]
            key = f"{spec['provider_id']}.{spec['tool']}"
            rec = CapabilityRecord(
                tool=key, operation_id=spec["operation_id"], domain=os_["domain"],
                capability=os_["authz"], risk_level=os_["risk"]["default_level"],
                effects=tuple(os_["risk"]["effects"]), blast_radius=os_["risk"]["blast_radius"],
                approval_required=os_["risk"]["approval_required"], resource=os_["resource"]["type"],
            )
            self._by_tool[key] = rec
            # Operation-first (ADR-009): capability/risco são idênticos entre os
            # bindings de uma mesma Operation; a tool concreta é escolhida
            # deterministicamente (min das candidatas) para estabilidade.
            op_id = spec["operation_id"]
            prev = self._tool_for_operation.get(op_id)
            if prev is None or key < prev:
                self._tool_for_operation[op_id] = key
                self._by_operation[op_id] = rec

    def record(self, tool: str) -> CapabilityRecord | None:
        if not self._loaded:
            self._load()
        return self._by_tool.get(tool)

    def record_for_operation(self, operation_id: str) -> CapabilityRecord | None:
        if not self._loaded:
            self._load()
        return self._by_operation.get(operation_id)

    def tool_for_operation(self, operation_id: str) -> str | None:
        if not self._loaded:
            self._load()
        return self._tool_for_operation.get(operation_id)


@dataclass
class PersonaPolicy:
    """Política de uma persona para o PDP por recurso/efeito (deny-by-default)."""

    allowed_effects: frozenset[str]         # efeitos permitidos ("*" via allow_all)
    max_blast: str = "service"              # teto de blast_radius
    allowed_domains: frozenset[str] = field(default_factory=frozenset)  # vazio = todos
    allow_all_effects: bool = False

    @property
    def max_blast_rank(self) -> int:
        return _BLAST_RANK.get(self.max_blast, 2)
