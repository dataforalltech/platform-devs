# Camada Database

Banco é estado durável. Cada mudança é versionada e reversível.

## Pode

- Criar tabela/coluna via migration reversível (Alembic, Flyway, etc.).
- Renomear coluna em duas etapas (add → backfill → swap → remove).
- Adicionar `NOT NULL` em coluna existente **com backfill prévio**.
- Adicionar índice em janela de baixo tráfego (concurrent quando suportado).

## Não pode

- Rodar `DROP`/`TRUNCATE`/`DELETE FROM` em código de aplicação.
- Adicionar `NOT NULL` em coluna existente sem backfill.
- Migrar dados em hotpath de request HTTP.
- Misturar mudança de schema com mudança de dado em uma migration.
- Editar migrations já aplicadas em produção (criar uma nova).

## Errado

```sql
-- NOT NULL sem backfill em tabela grande
ALTER TABLE orders ALTER COLUMN customer_id SET NOT NULL;
```

```python
# DROP em código de app
session.execute(text("DROP TABLE legacy_orders"))
```

```python
# Migração de dados em request HTTP
@router.post("/orders")
def create_order(...):
    backfill_old_orders()  # mata o request
    ...
```

## Correto

Migration em duas (ou três) etapas:

```python
# 1) Adicionar coluna nullable
op.add_column("orders", sa.Column("customer_id", sa.String, nullable=True))

# 2) Backfill em batch (job separado, não em hotpath)
# UPDATE orders SET customer_id = ... WHERE customer_id IS NULL;

# 3) Após backfill 100%: adicionar NOT NULL
op.alter_column("orders", "customer_id", nullable=False)
```

## Convenções (repos do ecossistema)

- Migrations versionadas, com `downgrade()` implementado quando possível.
- Nomes em `snake_case`. Tabelas no plural. Colunas no singular.
- Foreign keys nomeadas explicitamente (`fk_<tabela>_<coluna>`).
- Índices nomeados explicitamente (`ix_<tabela>_<coluna>`).
- Operações destrutivas vão em runbook controlado, não em código de app.
