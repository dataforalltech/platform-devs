"""Entidades canônicas do LEDGER do deploy-mcp (Pydantic v2).

deploy-mcp é COMPUTE + STATEFUL: as tools continuam FAZENDO a ação real (git,
GitHub, deploy, ACR, CI) via o ``GitHubClient`` e, DEPOIS do sucesso, **registram a
operação num ledger persistido** (dual-db, tenant-scoped, credencial-zero). Estes
modelos dirigem DUAS camadas do ORM canônico (``platform_database.orm``):

  1. **DDL IR** — ``create_table_from_model`` gera o ``CREATE TABLE`` (com as colunas
     padrão da plataforma injetadas pela ``schema.table_factory``).
  2. **Repository** — CRUD tipado (``find``/``insert``/``update``/``upsert``/
     ``delete_where``) sobre o pool async do tenant.

Convenções (playbook §5):

  * As colunas de auditoria/controle padrão (``id``, ``id_user_created``,
    ``id_user_modify``, ``create_on``, ``active``, ``excluded``,
    ``timestamp_refresh``, ``scope``) são injetadas pela fábrica de schema — NÃO são
    declaradas aqui (seriam ignoradas por colisão). Por isso NENHUM modelo declara
    uma coluna chamada ``scope`` (colidiria com a padrão).
  * As colunas **naturais/curtas** carregam um ``max_length`` explícito para virarem
    ``VARCHAR(n)`` (indexável) em vez de ``TEXT`` — MySQL não indexa ``TEXT`` sem
    prefixo. As chaves naturais (upsert) são justamente VARCHAR/INT.
  * ``run_id`` é ``str`` (não ``int``): o run_id do GitHub Actions já ultrapassa o
    range de ``INT`` (MySQL mapeia ``int`` → ``INT`` 32-bit) — guardar como
    ``VARCHAR`` evita overflow e mantém a chave natural (repo, run_id) estável.
  * Dados estruturados (``detail``/``config``) são **JSON serializado em ``TEXT``**
    (``str | None``, dual-db safe; não é coluna JSON nativa). ``url`` livre é ``TEXT``.
  * ⚠️ Reserved words do MySQL: o ORM emite identificadores **unquoted**; NENHUMA
    coluna abaixo é palavra reservada do MySQL 8.0 (confirmado via ``emit_ddl mysql``).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class DeploymentRow(BaseModel):
    """Um deploy disparado (histórico append-only, chave surrogate ``id``)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    service: str = Field(max_length=200)  # serviço alvo -> VARCHAR(200)
    environment: str = Field(max_length=40)  # dev/hml/prod -> VARCHAR(40)
    status: str = Field(max_length=40)  # dispatched/... -> VARCHAR(40)
    ref: str | None = Field(default=None, max_length=300)  # branch/tag/SHA
    repo: str | None = Field(default=None, max_length=200)
    workflow: str | None = Field(default=None, max_length=200)  # arquivo do workflow
    run_id: str | None = Field(default=None, max_length=64)  # id do run (VARCHAR: cabe BIGINT)
    detail: str | None = None  # JSON serializado (TEXT): resultado bruto do dispatch


class PullRequestRow(BaseModel):
    """Um Pull Request (chave natural única ``(repo, number)`` → upsert)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    repo: str = Field(max_length=200)  # parte 1 da chave natural
    number: int  # parte 2 da chave natural (PR number cabe em INT)
    title: str | None = Field(default=None, max_length=500)
    base: str | None = Field(default=None, max_length=200)
    head: str | None = Field(default=None, max_length=200)
    url: str | None = None  # URL livre (TEXT)
    state: str | None = Field(default=None, max_length=40)  # open/closed/merged


class BranchRow(BaseModel):
    """Uma branch criada (chave natural única ``(repo, branch)`` → upsert)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    repo: str = Field(max_length=200)  # parte 1 da chave natural
    branch: str = Field(max_length=255)  # parte 2 da chave natural
    from_ref: str | None = Field(default=None, max_length=255)
    status: str | None = Field(default=None, max_length=40)


class WorkflowRunRow(BaseModel):
    """Um workflow run observado (chave natural única ``(repo, run_id)`` → upsert)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    repo: str = Field(max_length=200)  # parte 1 da chave natural
    run_id: str = Field(max_length=64)  # parte 2 (VARCHAR: run_id do GH > INT range)
    workflow: str | None = Field(default=None, max_length=200)  # nome do workflow
    status: str | None = Field(default=None, max_length=40)  # queued/in_progress/completed
    conclusion: str | None = Field(default=None, max_length=40)  # success/failure/cancelled
    detail: str | None = None  # JSON serializado (TEXT): run bruto


class RepoRow(BaseModel):
    """Um repositório registrado para automação (chave natural única ``repo`` → upsert)."""

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    repo: str = Field(max_length=200)  # chave natural única
    config: str | None = None  # JSON serializado (TEXT): image_name/registry/secrets configurados
    status: str | None = Field(default=None, max_length=40)  # configured/partial


class DeployEventRow(BaseModel):
    """Evento genérico do ledger (histórico append-only, chave surrogate ``id``).

    ``kind`` ∈ {clone, commit, acr_build, cancel_run, scaffold_pipeline,
    trigger_workflow, ...}. ``target`` é o alvo do evento (repo, imagem, run) e
    ``detail`` é o resultado bruto da ação (JSON serializado em TEXT).
    """

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    kind: str = Field(max_length=40)  # tipo do evento -> VARCHAR(40)
    target: str | None = Field(default=None, max_length=300)
    status: str | None = Field(default=None, max_length=40)
    detail: str | None = None  # JSON serializado (TEXT)


__all__ = [
    "DeploymentRow",
    "PullRequestRow",
    "BranchRow",
    "WorkflowRunRow",
    "RepoRow",
    "DeployEventRow",
]
