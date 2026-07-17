"""Bootstrap de schema por-tenant via DDL IR canônico (`platform_database.orm.ddl`).

Nada de `CREATE TABLE` escrito à mão: a tabela é um `CreateTable` derivado do modelo
Pydantic (`create_table_from_model`, que injeta as colunas padrão da plataforma) e é
renderizada como `CREATE TABLE IF NOT EXISTS` — portanto idempotente no re-run.

O `test_runs` é um **log append-only** (Create + Read; sem UPDATE/UPSERT/DELETE, sem
chave natural). Logo, ao contrário do pipeline-mcp:

  * NÃO há `UniqueConstraintSpec` (não há chave natural; múltiplas linhas por
    (repo_path, run_type) são o histórico esperado).
  * NÃO se emite um `CREATE INDEX` separado. O índice de leitura original
    (repo_path, run_type, started_at DESC) era pura otimização de read-path e é
    **incompatível com um bootstrap idempotente dual-db**: o MySQL não suporta
    `CREATE INDEX IF NOT EXISTS`, então um `CreateIndex` avulso quebraria no 2º boot de
    um tenant já existente (o `CreateTable` folda só UNIQUE/CHECK, não índices
    secundários). A ordenação/filtro do `list_runs` é servida nativamente pelo
    Repository (`find(where=..., order_by=..., limit=...)`), sem depender do índice.

Idempotente e multi-engine: `emit_ddl(script, engine)` compila para o dialeto do tenant
(mysql/postgresql), então o MESMO bootstrap serve o dual-db.
"""

from __future__ import annotations

from typing import Any

from platform_database.orm.ddl import (
    MigrationScript,
    create_table_from_model,
    emit_ddl,
)

from ..models import TestRunRow

# Nome físico da tabela (table-case "lower" por padrão — tenants novos).
TEST_RUNS_TABLE = "test_runs"


def build_migration() -> MigrationScript:
    """A migração de criação da tabela de histórico (up-only, idempotente)."""
    return MigrationScript(up=[create_table_from_model(TestRunRow, table_name=TEST_RUNS_TABLE)])


async def ensure_schema(pool: Any, *, engine: str) -> None:
    """Cria a tabela no banco do tenant (idempotente `IF NOT EXISTS`).

    ``engine`` é o motor real do tenant (derivado do dialeto do pool), para o DDL IR
    compilar o SQL correto (mysql/postgresql) — é o ponto do dual-db.
    """
    for statement in emit_ddl(build_migration(), engine):
        await pool.execute(statement)


__all__ = ["TEST_RUNS_TABLE", "build_migration", "ensure_schema"]
