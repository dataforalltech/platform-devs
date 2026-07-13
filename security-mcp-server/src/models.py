"""Entidades canônicas do store do security-mcp (Pydantic v2).

Estes modelos dirigem DUAS camadas do ORM canônico (`platform_database.orm`):

  1. **DDL IR** — `create_table_from_model` gera o `CREATE TABLE` (com as colunas
     padrão da plataforma injetadas pela `schema.table_factory`).
  2. **Repository** — CRUD tipado (`find`/`insert`/`update`/`update_where`/`upsert`/
     `delete_where`) sobre o pool async do tenant.

Arquitetura decidida ("o agente gera o conteúdo, a tool PERSISTE"): o persona não
gera mais template fixo — o agente chamador fornece o artefato de segurança (modelo
de ameaças, controle, avaliação CVSS, plano/scan) e a tool o **persiste** no banco do
tenant. Cada entidade é um histórico consultável (list/get) e mutável (update/soft-
delete).

Convenções (playbook §5):

  * Toda coluna que os reads/writes tocam é declarada; opcional onde uma leitura
    pode não popular.
  * As colunas de auditoria/controle padrão (``id``, ``id_user_created``,
    ``id_user_modify``, ``create_on``, ``active``, ``excluded``,
    ``timestamp_refresh``, ``scope``) são injetadas pela fábrica de schema / pelas
    ``EntityConventions`` — NÃO são declaradas aqui (seriam ignoradas por colisão).
  * As colunas **naturais/curtas** (``system_name``/``control_key``/``vector``/``kind``/...)
    carregam um ``max_length`` explícito para virarem ``VARCHAR(n)`` (indexável/curto)
    em vez de ``TEXT`` — MySQL não indexa ``TEXT`` sem prefixo de tamanho.
    ``(system_name, control_key)`` é a única **chave natural única** (um controle por chave
    por sistema → UNIQUE + upsert). ``system_name`` (não ``system``, palavra reservada
    do MySQL 8) porque o ORM canônico emite identificadores UNQUOTED.
  * Dados estruturados (components/threats/details/metrics/meta) são **JSON serializado
    em ``TEXT``** (``str | None``, dual-db safe; não é coluna JSON nativa). Texto longo
    livre (``summary``/``content``) também é ``TEXT``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ThreatModelRow(BaseModel):
    """Um modelo de ameaças persistido (chave surrogate ``id``)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    system_name: str = Field(max_length=200)  # sistema alvo -> VARCHAR(200)
    methodology: str = Field(max_length=40)  # STRIDE/PASTA/... -> VARCHAR(40)
    title: str | None = Field(default=None, max_length=300)
    components: str | None = None  # JSON serializado (TEXT): lista de componentes
    threats: str | None = None  # JSON serializado (TEXT): lista de ameaças do agente
    summary: str | None = None  # texto livre (TEXT)
    status: str | None = Field(default=None, max_length=20)


class SecurityControlRow(BaseModel):
    """Um controle de segurança (chave natural única: ``system_name+control_key`` → upsert)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    system_name: str = Field(max_length=200)  # parte da chave natural -> VARCHAR(200)
    control_key: str = Field(max_length=100)  # parte da chave natural -> VARCHAR(100)
    name: str | None = Field(default=None, max_length=300)
    control_type: str | None = Field(default=None, max_length=40)  # technical/operational
    framework_ref: str | None = Field(default=None, max_length=80)  # nist_csf/iso/...
    details: str | None = None  # JSON serializado (TEXT)
    status: str | None = Field(default=None, max_length=20)


class CvssAssessmentRow(BaseModel):
    """Uma avaliação CVSS persistida (chave surrogate ``id``).

    ``base_score``/``severity``/``metrics`` podem ser calculados deterministicamente do
    ``vector`` (CVSS v3.1) no save quando o agente não os fornece.
    """

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    label: str | None = Field(default=None, max_length=200)  # CVE/nome da vuln
    vector: str = Field(max_length=120)  # vetor CVSS 3.1 -> VARCHAR(120)
    base_score: float | None = None
    severity: str | None = Field(default=None, max_length=20)  # None/Low/Medium/High/Critical
    metrics: str | None = None  # JSON serializado (TEXT): métricas do vetor
    status: str | None = Field(default=None, max_length=20)


class SecurityArtifactRow(BaseModel):
    """Um artefato de segurança gerado pelo agente e persistido (histórico, ``id``).

    ``content`` guarda o texto/relatório que o agente gerou (plano de IR, scan de
    segredos, revisão de código, mapeamento de superfície, etc.) — texto livre, não
    JSON. ``meta`` é JSON serializado.
    """

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    # incident_plan|attack_surface|compliance|code_review|dep_risk|secrets_scan|headers|password_policy
    kind: str = Field(max_length=40)
    target: str = Field(max_length=300)  # sistema/serviço/endpoint/arquivo
    content: str | None = None  # o relatório/texto gerado (TEXT, texto livre)
    meta: str | None = None  # JSON serializado (TEXT)


__all__ = [
    "ThreatModelRow",
    "SecurityControlRow",
    "CvssAssessmentRow",
    "SecurityArtifactRow",
]
