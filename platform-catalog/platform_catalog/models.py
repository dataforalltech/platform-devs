"""Platform Catalog — modelos (envelope ADR-010 + specs ADR-009).

O catálogo é a *source of truth* do domínio (ADR-009). Toda entidade compartilha o
ENVELOPE COMUM do ADR-010 (apiVersion / kind / metadata / spec / relations); o `spec`
varia por `kind`. Fase 1 popula os kinds Core: Operation, Tool (binding) e Provider.

Hierarquia (ADR-009): Domain ⊃ Capability ⊃ Operation ──1..N──▶ Tool ──▶ Provider.
- Operation = contrato de domínio, provider-agnóstico (unidade de política/discovery).
- Tool      = binding técnico (um provider implementando uma Operation).
"""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field

API_VERSION = "catalog.platform.dev/v1"  # apiVersion do meta-modelo (ADR-010 D10.9)


# --- enums (vocabulários fechados) ------------------------------------------
class Kind(str, Enum):
    OPERATION = "Operation"
    TOOL = "Tool"
    PROVIDER = "Provider"


class Lifecycle(str, Enum):  # ADR-010 D10.7 (envelope)
    EXPERIMENTAL = "experimental"
    STABLE = "stable"
    DEPRECATED = "deprecated"
    RETIRED = "retired"


class Capability(str, Enum):  # authz gate (ADR-007) — deny-by-default
    READ = "read"
    WRITE = "write"


class RiskLevel(str, Enum):  # ADR-007 risk tiers
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class BlastRadius(str, Enum):  # ADR-009 D9.4/D9.8
    NONE = "none"
    WORKSPACE = "workspace"
    SERVICE = "service"
    ENVIRONMENT = "environment"
    TENANT = "tenant"
    GLOBAL = "global"


class Approval(str, Enum):  # HILT (ADR-005)
    NONE = "none"
    N1 = "N1"
    N2 = "N2"


class RelationVerb(str, Enum):  # registro de verbos (ADR-010 D10.4)
    IMPLEMENTS = "implements"       # Tool -> Operation
    PROVIDED_BY = "provided-by"     # Tool -> Provider
    ACTS_ON = "acts-on"            # Operation -> Resource
    PART_OF = "part-of"
    DEPENDS_ON = "depends-on"


# --- envelope (ADR-010 D10.1) -----------------------------------------------
class Resource(BaseModel):
    """Recurso sobre o qual a Operation atua (ADR-009 D9.4; hierarquia preparada)."""

    type: str
    parent: str | None = None
    namespace: str | None = None


class Metadata(BaseModel):
    name: str                                   # <namespace>/<name> qualificado
    uid: str                                    # id canônico estável (ADR-010 D10.6)
    domain: str
    title: str = ""
    description: str = ""
    owner: str = "platform"
    tags: list[str] = Field(default_factory=list)
    lifecycle: Lifecycle = Lifecycle.STABLE
    version: str = "1.0.0"                       # SemVer da ENTIDADE (ADR-010; ≠ apiVersion)


class Relation(BaseModel):
    verb: RelationVerb
    target: str                                  # uid de outra entidade


class Risk(BaseModel):  # descritor ortogonal (ADR-009 D9.5/D9.8)
    effects: list[str] = Field(default_factory=list)     # o que FAZ
    requires: list[str] = Field(default_factory=list)    # do que DEPENDE
    blast_radius: BlastRadius = BlastRadius.SERVICE
    default_level: RiskLevel = RiskLevel.MEDIUM
    approval_required: Approval = Approval.NONE


class Execution(BaseModel):  # perfil lido pelo planner (ADR-009 D9.8)
    idempotent: bool = False
    side_effects: bool = True
    is_async: bool = False
    streaming: bool = False
    timeout_s: int = 60
    retry_policy: str = "none"    # none | read-only | backoff(n)


class Contract(BaseModel):
    inputs: dict = Field(default_factory=dict)
    outputs: dict = Field(default_factory=dict)
    preconditions: list[str] = Field(default_factory=list)
    postconditions: list[str] = Field(default_factory=list)
    execution: Execution = Field(default_factory=Execution)


# --- specs por kind ---------------------------------------------------------
class OperationSpec(BaseModel):
    domain: str
    capability: str                              # agrupador dentro do domínio
    resource: Resource
    operation: str                               # o verbo/ação
    authz: Capability = Capability.READ          # gate read|write
    risk: Risk = Field(default_factory=Risk)
    contract: Contract = Field(default_factory=Contract)


class ToolSpec(BaseModel):
    operation_id: str                            # a Operation que implementa
    provider_id: str
    provider_version: str = "1.0.0"
    tool: str                                    # operationId concreto do provider
    endpoint: str = "streamable-http"
    selection: dict = Field(default_factory=dict)  # preference/weight/health (ADR-011 D11.6)


class ProviderSpec(BaseModel):
    server: str
    kind: str = "mcp-server"
    transport: str = "streamable-http"
    version: str = "1.0.0"


# --- entidade (envelope genérico) -------------------------------------------
class Entity(BaseModel):
    apiVersion: str = API_VERSION
    kind: Kind
    metadata: Metadata
    spec: dict = Field(default_factory=dict)     # OperationSpec|ToolSpec|ProviderSpec serializado
    relations: list[Relation] = Field(default_factory=list)

    @property
    def uid(self) -> str:
        return self.metadata.uid
