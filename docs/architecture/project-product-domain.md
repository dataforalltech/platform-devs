# Domínio canônico de produtos e projetos

`platform-project-product` é o sistema de registro de produtos, projetos e vínculos provider-neutral com repositórios.

```text
Product 1 ── N Project 1 ── N RepositoryBinding
```

A arquitetura segue Trinity:

```text
platform-api-gateway
  -> FastAPI /api/v1
       -> services -> platform-database-lib ORM -> store canônico por tenant

mcp-gateway -> inner token RS256 -> project-product-mcp
  -> scope + rate limit + platform-governance PEP/HITL
  -> /api/internal/mcp (S2S)
  -> mesmos services/repositories
```

O sidecar MCP não importa banco, não executa SQL e não possui store próprio. Local e remoto usam exatamente o mesmo transporte HTTP e os mesmos 13 contratos. A API passa somente `tenant_id` à biblioteca; endpoints, engine e credenciais do store vêm de `ADMIN_DATAFORALL.PLATFORMS`. O runtime suporta PostgreSQL e MySQL 8.4 sem SQLite; cada deployment declara o engine compatível com os tenants atendidos.

## Ownership

| Dado/ação | Owner | Referência mantida aqui |
|---|---|---|
| produtos, projetos, vínculos | `platform-devs` | entidade canônica |
| usuários | `platform-admin` | `owner_user_refs` e auditoria |
| SCM/conectores | `platform-connectors` | `connector_ref`, `repository_ref`, `provider` |
| políticas/aprovações | `platform-governance` | avaliação online; nenhum snapshot permissivo |
| agenda | `platform-scheduler` | `schedule_ref` |
| comunicação | `platform-communication` | `communication_ref` |
| notificações | `platform-notification` | `notification_ref` |

Nenhuma credencial de SCM ou cópia de perfil de usuário é persistida. GitHub é o provider inicial, mas o contrato usa identificadores opacos e permite qualquer connector registrado.

## Invariantes

- tenant nunca é argumento de tool;
- `id_environment` e `id_owner` estão em toda query e write;
- writes são idempotentes e usam `expected_version` nas mutações;
- produto com projeto ativo e projeto com binding ativo não podem ser removidos;
- deletes/detach são soft-delete; as action classes de alto risco exigem aprovação humana;
- input e output possuem JSON Schema fechado e são validados no sidecar;
- erros externos falham fechados, sem mock ou sucesso genérico;
- migration ocorre somente no release job com advisory lock distribuído.

## Tools

Produtos: `product_create`, `product_get`, `product_list`, `product_update`, `product_delete`.

Projetos: `project_create`, `project_get`, `project_list`, `project_update`, `project_delete`.

Repositórios: `project_repository_attach`, `project_repository_list`, `project_repository_detach`.

O manifesto gera gateway, registry e Compose. Em Swarm o sidecar não publica porta no host; compartilha somente overlays privados com gateway, identity, governance e API adapter.
