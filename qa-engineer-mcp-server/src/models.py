"""Entidades canônicas do store do qa-engineer-mcp (Pydantic v2).

Estes modelos dirigem DUAS camadas do ORM canônico (`platform_database.orm`):

  1. **DDL IR** — `create_table_from_model` gera o `CREATE TABLE` (com as colunas
     padrão da plataforma injetadas pela `schema.table_factory`).
  2. **Repository** — CRUD tipado (`find`/`insert`/`update`/`update_where`/`upsert`/
     `delete_where`) sobre o pool async do tenant.

Arquitetura decidida ("o agente gera o conteúdo, a tool persiste"): o persona não
gera mais template fixo — o agente chamador fornece o artefato (plano, caso, bug,
código de teste) e a tool o **persiste** no banco do tenant. Cada entidade é um
histórico consultável (list/get) e mutável (update/soft-delete).

Convenções (playbook §5):

  * Toda coluna que os reads/writes tocam é declarada; opcional onde uma leitura
    pode não popular.
  * As colunas de auditoria/controle padrão (``id``, ``id_user_created``,
    ``id_user_modify``, ``create_on``, ``active``, ``excluded``,
    ``timestamp_refresh``, ``scope``) são injetadas pela fábrica de schema / pelas
    ``EntityConventions`` — NÃO são declaradas aqui (seriam ignoradas por colisão).
  * As colunas **naturais/curtas** (``feature``/``title``/``service``/...) carregam um
    ``max_length`` explícito para virarem ``VARCHAR(n)`` (indexável/curto) em vez de
    ``TEXT`` — MySQL não indexa ``TEXT`` sem prefixo de tamanho. ``service`` é a única
    **chave natural única** (quality gate por serviço → UNIQUE + upsert).
  * Dados estruturados (objectives/steps/thresholds/meta) são **JSON serializado em
    ``TEXT``** (``str | None``, dual-db safe; não é coluna JSON nativa). Texto longo
    livre (``content``/``description``/``expected_result``) também é ``TEXT``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class TestPlanRow(BaseModel):
    """Um plano de teste persistido (chave surrogate ``id``)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    feature: str = Field(max_length=200)  # funcionalidade alvo -> VARCHAR(200)
    scope: str = Field(max_length=40)  # full/partial/... -> VARCHAR(40)
    team: str | None = Field(default=None, max_length=120)
    content: str | None = None  # JSON serializado (TEXT): objectives/levels/environments/schedule
    status: str | None = Field(default=None, max_length=20)


class TestCaseRow(BaseModel):
    """Um caso de teste persistido (chave surrogate ``id``)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    feature: str = Field(max_length=200)
    title: str = Field(max_length=300)
    test_type: str = Field(max_length=40)  # functional/e2e/api/... -> VARCHAR(40)
    priority: str = Field(max_length=20)  # high/medium/low -> VARCHAR(20)
    preconditions: str | None = None  # JSON serializado (TEXT)
    steps: str | None = None  # JSON serializado (TEXT)
    expected_result: str | None = None  # texto livre (TEXT)
    test_data: str | None = None  # JSON serializado (TEXT)
    status: str | None = Field(default=None, max_length=20)


class BugReportRow(BaseModel):
    """Um bug report persistido (chave surrogate ``id``)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    title: str = Field(max_length=300)
    severity: str = Field(max_length=10)  # P1-P4 -> VARCHAR(10)
    impact: str = Field(max_length=20)  # critical/high/medium/low -> VARCHAR(20)
    frequency: str = Field(max_length=20)  # always/often/sometimes/rarely -> VARCHAR(20)
    steps: str | None = None  # JSON serializado (TEXT)
    description: str | None = None  # texto livre (TEXT)
    status: str | None = Field(default=None, max_length=20)
    score: float | None = None  # score determinístico (impact×frequency), CVSS-ish


class QualityGateRow(BaseModel):
    """Um quality gate por serviço (chave natural única: ``service`` → upsert)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    service: str = Field(max_length=200)  # chave natural única -> VARCHAR(200)
    thresholds: str | None = None  # JSON serializado (TEXT)
    status: str | None = Field(default=None, max_length=20)


class QaArtifactRow(BaseModel):
    """Um artefato de QA gerado pelo agente e persistido (histórico append-only, ``id``).

    ``content`` guarda o código/cenário que o agente gerou (Playwright, k6, Gherkin,
    coleção Postman, etc.) — texto livre, não JSON. ``meta`` é JSON serializado.
    """

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    # e2e|api|unit|gherkin|playwright|cypress|postman|k6|regression|smoke|uat|coverage|analysis|testability
    kind: str = Field(max_length=40)
    target: str = Field(max_length=300)  # feature/module/endpoint/service
    framework: str | None = Field(default=None, max_length=40)
    content: str | None = None  # o código/cenário gerado (TEXT, texto livre)
    meta: str | None = None  # JSON serializado (TEXT)


__all__ = [
    "TestPlanRow",
    "TestCaseRow",
    "BugReportRow",
    "QualityGateRow",
    "QaArtifactRow",
]
