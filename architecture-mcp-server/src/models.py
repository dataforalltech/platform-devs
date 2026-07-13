"""Entidades canônicas do store do architecture-mcp (Pydantic v2).

Estes modelos dirigem DUAS camadas do ORM canônico (`platform_database.orm`):

  1. **DDL IR** — `create_table_from_model` gera o `CREATE TABLE` (com as colunas
     padrão da plataforma injetadas pela `schema.table_factory`).
  2. **Repository** — CRUD tipado (`find`/`insert`/`update`/`update_where`/`upsert`/
     `delete_where`) sobre o pool async do tenant.

Arquitetura decidida ("o agente gera o conteúdo, a tool persiste"): o persona não
gera mais template fixo — o agente chamador fornece o artefato (proposta de
arquitetura, modelo C4, blueprint de solução) e a tool o **persiste** no banco do
tenant. As antigas tools `generate_*` viram *builders* determinísticos (heurísticas
de palavra-chave transparentes) que continuam reais, mas o foco passa a ser a
persistência: cada entidade é um histórico consultável (list/get) e mutável
(update/soft-delete).

Convenções (playbook §5):

  * Toda coluna que os reads/writes tocam é declarada; opcional onde uma leitura
    pode não popular.
  * As colunas de auditoria/controle padrão (``id``, ``id_user_created``,
    ``id_user_modify``, ``create_on``, ``active``, ``excluded``,
    ``timestamp_refresh``, ``scope``) são injetadas pela fábrica de schema / pelas
    ``EntityConventions`` — NÃO são declaradas aqui (seriam ignoradas por colisão).
  * As colunas **naturais/curtas** (``name``/``domain``/``system_name``/...) carregam
    um ``max_length`` explícito para virarem ``VARCHAR(n)`` (indexável/curto) em vez
    de ``TEXT`` — MySQL não indexa ``TEXT`` sem prefixo de tamanho. ``system_name`` é
    a única **chave natural única** (um modelo C4 canônico por sistema → UNIQUE +
    upsert).
  * Dados estruturados (constraints/quality_attributes/model/content/meta) são **JSON
    serializado em ``TEXT``** (``str | None``, dual-db safe; não é coluna JSON nativa).
    Texto longo livre (``requirements``/``context``) também é ``TEXT``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class ArchitectureBlueprintRow(BaseModel):
    """Uma proposta de arquitetura persistida (chave surrogate ``id``)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    name: str = Field(max_length=200)  # nome da arquitetura -> VARCHAR(200)
    domain: str = Field(max_length=200)  # domínio/negócio alvo -> VARCHAR(200)
    style: str | None = Field(default=None, max_length=120)  # estilo proposto -> VARCHAR(120)
    constraints: str | None = None  # JSON serializado (TEXT): lista de restrições
    quality_attributes: str | None = None  # JSON serializado (TEXT): lista de NFRs
    content: str | None = None  # JSON serializado (TEXT): proposta completa (rationale/tactics/...)
    status: str | None = Field(default=None, max_length=20)


class C4DiagramRow(BaseModel):
    """Um modelo C4 por sistema (chave natural única: ``system_name`` → upsert)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    system_name: str = Field(max_length=200)  # chave natural única -> VARCHAR(200)
    title: str | None = Field(default=None, max_length=300)
    model: str | None = None  # JSON serializado (TEXT): modelo C4 completo (levels/actors/...)
    status: str | None = Field(default=None, max_length=20)


class SolutionBlueprintRow(BaseModel):
    """Um blueprint de solução persistido (chave surrogate ``id``)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    solution_name: str = Field(max_length=200)  # nome da solução -> VARCHAR(200)
    context: str | None = None  # contexto livre (TEXT)
    requirements: str | None = None  # requisitos livres (TEXT)
    content: str | None = None  # JSON serializado (TEXT): blueprint completo (layers/components/...)
    status: str | None = Field(default=None, max_length=20)


class ArchitectureArtifactRow(BaseModel):
    """Um artefato de arquitetura gerado pelo agente e persistido (histórico, ``id``).

    ``content`` guarda o texto/código que o agente gerou (Mermaid, PlantUML, ADR,
    markdown, etc.) — texto livre, não JSON. ``meta`` é JSON serializado.
    """

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    # adr|c4|diagram|blueprint|proposal|decision|mermaid|plantuml|markdown|note
    kind: str = Field(max_length=40)
    target: str = Field(max_length=300)  # sistema/domínio/serviço alvo
    format: str | None = Field(default=None, max_length=40)  # mermaid|plantuml|markdown|json
    content: str | None = None  # o texto/código gerado (TEXT, texto livre)
    meta: str | None = None  # JSON serializado (TEXT)


__all__ = [
    "ArchitectureBlueprintRow",
    "C4DiagramRow",
    "SolutionBlueprintRow",
    "ArchitectureArtifactRow",
]
