"""Entidades canônicas do store do devops-mcp (Pydantic v2).

Estes modelos dirigem DUAS camadas do ORM canônico (`platform_database.orm`):

  1. **DDL IR** — `create_table_from_model` gera o `CREATE TABLE` (com as colunas
     padrão da plataforma injetadas pela `schema.table_factory`).
  2. **Repository** — CRUD tipado (`find`/`insert`/`update`/`update_where`/`upsert`/
     `delete_where`) sobre o pool async do tenant.

Arquitetura decidida ("o agente gera o conteúdo, a tool persiste"): o persona não
gera mais template fixo — o agente chamador fornece o artefato de infra-as-code
(Dockerfile, pipeline de CI/CD, chart Helm, manifesto k8s, registro de deploy) e a
tool o **persiste** no banco do tenant. Cada entidade é um histórico consultável
(list/get) e mutável (update/soft-delete).

Convenções (playbook §5):

  * Toda coluna que os reads/writes tocam é declarada; opcional onde uma leitura
    pode não popular.
  * As colunas de auditoria/controle padrão (``id``, ``id_user_created``,
    ``id_user_modify``, ``create_on``, ``active``, ``excluded``,
    ``timestamp_refresh``, ``scope``) são injetadas pela fábrica de schema / pelas
    ``EntityConventions`` — NÃO são declaradas aqui (seriam ignoradas por colisão).
  * As colunas **naturais/curtas** (``kind``/``target``/``application``/``service``/
    ``name``/...) carregam um ``max_length`` explícito para virarem ``VARCHAR(n)``
    (indexável/curto) em vez de ``TEXT`` — MySQL não indexa ``TEXT`` sem prefixo de
    tamanho. ``name`` (environment) e ``service`` (service config) são as duas
    **chaves naturais únicas** (registry por nome/serviço → UNIQUE + upsert).
  * Dados estruturados (spec/content/settings/config/meta) são **JSON serializado em
    ``TEXT``** (``str | None``, dual-db safe; não é coluna JSON nativa). Texto/código
    longo livre (``content``/``notes``) também é ``TEXT``.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class DevopsArtifactRow(BaseModel):
    """Um artefato de infra-as-code gerado pelo agente e persistido (histórico, ``id``).

    Substitui as antigas tools ``generate_*`` (dockerfile/github_actions/helm_chart/
    k8s_manifest/...): em vez de template fixo, o agente gera o ``content`` (o arquivo
    IaC) e a tool o persiste, classificado por ``kind`` e ``target``. ``content`` é
    texto livre (o arquivo gerado); ``spec`` é JSON serializado (parâmetros/inputs).
    """

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    # dockerfile|github_actions|gitlab_ci|helm_chart|k8s_manifest|terraform|compose
    kind: str = Field(max_length=40)
    target: str = Field(max_length=300)  # aplicação/serviço/módulo alvo
    tool: str | None = Field(default=None, max_length=40)  # docker/helm/kustomize/...
    content: str | None = None  # o arquivo IaC gerado (TEXT, texto livre)
    spec: str | None = None  # JSON serializado (TEXT): parâmetros/inputs do artefato
    status: str | None = Field(default=None, max_length=20)


class PipelineRow(BaseModel):
    """Uma pipeline de CI/CD persistida (chave surrogate ``id``, histórico por app)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    application: str = Field(max_length=200)  # aplicação alvo -> VARCHAR(200)
    provider: str = Field(max_length=40)  # github_actions/gitlab_ci/jenkins -> VARCHAR(40)
    content: str | None = None  # JSON serializado (TEXT): stages/triggers/jobs
    status: str | None = Field(default=None, max_length=20)


class DeploymentRow(BaseModel):
    """Um registro/evento de deploy persistido (chave surrogate ``id``, histórico)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    application: str = Field(max_length=200)
    environment: str = Field(max_length=40)  # dev/hml/prod -> VARCHAR(40)
    version: str = Field(max_length=100)  # image tag / versão -> VARCHAR(100)
    strategy: str | None = Field(default=None, max_length=40)  # rolling/blue_green/canary/recreate
    notes: str | None = None  # texto livre (TEXT)
    meta: str | None = None  # JSON serializado (TEXT)
    status: str | None = Field(default=None, max_length=20)


class EnvironmentRow(BaseModel):
    """Um ambiente/cluster registrado (chave natural única: ``name`` → upsert)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    name: str = Field(max_length=200)  # chave natural única -> VARCHAR(200)
    kind: str = Field(max_length=40)  # kubernetes/vm/serverless -> VARCHAR(40)
    region: str | None = Field(default=None, max_length=80)
    config: str | None = None  # JSON serializado (TEXT): cluster/namespace/limites
    status: str | None = Field(default=None, max_length=20)


class ServiceConfigRow(BaseModel):
    """Config de devops por serviço (chave natural única: ``service`` → upsert)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    service: str = Field(max_length=200)  # chave natural única -> VARCHAR(200)
    settings: str | None = None  # JSON serializado (TEXT): replicas/resources/env
    status: str | None = Field(default=None, max_length=20)


__all__ = [
    "DevopsArtifactRow",
    "PipelineRow",
    "DeploymentRow",
    "EnvironmentRow",
    "ServiceConfigRow",
]
