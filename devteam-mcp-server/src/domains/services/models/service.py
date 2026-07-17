"""Entidades canônicas do registry do services-mcp (Pydantic v2).

O modelo `ServiceRow` dirige DUAS camadas do ORM canônico (`platform_database.orm`):

  1. **DDL IR** — `create_table_from_model` gera o `CREATE TABLE` da tabela `services`
     (com as colunas padrão da plataforma injetadas pela `schema.table_factory`).
  2. **Repository** — CRUD tipado (`find`/`insert`/`update_where`/`delete_where`) sobre
     o pool async do tenant.

Convenções (playbook §5):

  * Toda coluna que os reads/writes tocam é declarada; nullable onde uma leitura pode
    não popular (o schema SQLite-flavored legado quase não tinha NOT NULL "de verdade" —
    só defaults, que passam a ser carimbados no store, não na DDL: MySQL não aceita
    literal DEFAULT em coluna TEXT).
  * As colunas de auditoria/controle padrão (``id``, ``id_user_created``,
    ``id_user_modify``, ``create_on``, ``active``, ``excluded``, ``timestamp_refresh``,
    ``scope``) são injetadas pela fábrica de schema / pelas ``EntityConventions`` — NÃO
    são declaradas aqui (seriam ignoradas por colisão).
  * A coluna de **chave natural** ``name`` carrega um ``max_length`` explícito para virar
    ``VARCHAR(255)`` (indexável na UNIQUE) em vez de ``TEXT`` — MySQL não indexa ``TEXT``
    sem prefixo de tamanho. As colunas usadas em filtros ``WHERE`` (``type``/``status``/
    ``environment``/``runtime``/``deploy_mode``) também recebem ``max_length`` (VARCHAR).
  * ``tags``/``metadata`` são JSON serializado como string (TEXT); as coerções ficam em
    ``service_record``.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ServiceType = Literal[
    "docker",
    "process",
    "remote",
    "unknown",
    "mysql",
    "mariadb",
    "postgres",
    "redis",
    "kafka",
    "mongodb",
]
ServiceStatus = Literal["running", "stopped", "unknown"]
EnvironmentName = Literal["local", "dev", "hml", "prod"]


class ServiceRow(BaseModel):
    """Um serviço registrado no registry (chave natural única: ``name``).

    Sem defaults de coluna: os defaults históricos (host='localhost', type='unknown',
    …) são carimbados no `ServiceStore` no path de criação (MySQL rejeita literal
    DEFAULT em coluna TEXT). Só ``name`` é NOT NULL (chave natural VARCHAR indexável).
    """

    model_config = ConfigDict(extra="ignore")

    id: int | None = None
    name: str = Field(max_length=255)  # chave natural única -> VARCHAR(255)
    host: str | None = Field(default=None, max_length=255)
    port: int | None = None
    url: str | None = None
    internal_url: str | None = None
    type: str | None = Field(default=None, max_length=64)
    container_name: str | None = None
    pid: int | None = None
    status: str | None = Field(default=None, max_length=32)
    health_path: str | None = Field(default=None, max_length=255)
    environment: str | None = Field(default=None, max_length=32)
    tags: str | None = None  # JSON serializado (TEXT)
    metadata: str | None = None  # JSON serializado (TEXT)
    registered_at: str | None = None
    last_seen: str | None = None
    last_check_at: str | None = None
    last_check_ok: int | None = None
    # Runtime environment
    runtime: str | None = Field(default=None, max_length=64)
    os_name: str | None = None
    os_release: str | None = None
    hostname: str | None = None
    deploy_mode: str | None = Field(default=None, max_length=32)


def service_record(row: dict) -> dict[str, Any]:
    """Converte row do banco em dict serializavel."""
    return {
        "name": row["name"],
        "host": row["host"],
        "port": row["port"],
        "url": row.get("url"),
        "internal_url": row.get("internal_url"),
        "type": row["type"],
        "container_name": row.get("container_name"),
        "pid": row.get("pid"),
        "status": row["status"],
        "health_path": row.get("health_path"),
        "environment": row["environment"],
        "tags": json.loads(row.get("tags") or "[]"),
        "metadata": json.loads(row.get("metadata") or "{}"),
        # Runtime environment
        "runtime": row.get("runtime") or "unknown",
        "deploy_mode": row.get("deploy_mode") or "unknown",
        "os_name": row.get("os_name"),
        "os_release": row.get("os_release"),
        "hostname": row.get("hostname"),
        # Timestamps
        "registered_at": row.get("registered_at"),
        "last_seen": row.get("last_seen"),
        "last_check_at": row.get("last_check_at"),
        "last_check_ok": bool(row["last_check_ok"]) if row.get("last_check_ok") is not None else None,
    }


__all__ = [
    "ServiceType",
    "ServiceStatus",
    "EnvironmentName",
    "ServiceRow",
    "service_record",
]
