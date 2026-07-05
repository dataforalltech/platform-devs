# Convenção de Nomes e Tags (AWS) — controle e custo

Padrão único aplicado nos dois Terraforms (`terraform/` e `terraform-lean/`) para
**cost allocation**, filtragem e governança.

## Nomes dos recursos

Padrão: **`<projeto>-<ambiente>-<componente>[-<detalhe>]`** — minúsculo, kebab-case.

| Recurso | Nome (exemplo) |
|---|---|
| VPC | `dataforall-hml-vpc` |
| Subnet | `dataforall-hml-subnet-public` |
| Route table | `dataforall-hml-rt-public` |
| Security group | `dataforall-hml-host-sg` |
| EC2 (enxuto) | `dataforall-hml-host` |
| EC2 (completo) | `dataforall-prod-swarm-manager-0`, `dataforall-prod-data-mysql-admin` |
| Volume EBS | `dataforall-hml-data-vol` |
| KMS | `dataforall-hml-kms` (alias `alias/dataforall-hml`) |
| S3 | `dataforall-hml-backups-<account>` |
| ECR | `dataforall/3.0/<serviço>` |

## Tags padrão (em TODOS os recursos — `default_tags`)

| Tag | Valor | Uso |
|---|---|---|
| `Project` | `dataforall` | agrupamento |
| `Environment` | `hml` \| `prod` | separar ambientes no custo |
| `Stack` | `dataforall-lean` \| `dataforall-platform` | qual desenho |
| `ManagedBy` | `terraform` | origem |
| `Owner` | `platform-team` (var `owner`) | responsável |
| `CostCenter` | `platform` (var `cost_center`) | **cost allocation** |

## Tags por recurso (além das padrão)

| Tag | Valores |
|---|---|
| `Name` | nome objetivo (tabela acima) |
| `Component` | `network` \| `compute` \| `data` \| `storage` \| `security` \| `dns` \| `iam` \| `observability` |
| `Tier` | `app` \| `data` \| `edge` \| `app+data` (enxuto) |
| `Role` | específico (`host`, `vault`, `swarm-manager`, `mysql-admin`, …) |
| `Backup` | `true` nos volumes que o DLM snapshota |

## Como usar para controle de custo

1. **Ativar como cost allocation tags** (uma vez, no console de Billing →
   *Cost allocation tags*): marcar `Project`, `Environment`, `Owner`,
   `CostCenter`, `Component`. (Só recursos criados **após** a ativação entram nos
   relatórios por tag.)
2. **Cost Explorer**: filtrar/agrupar por `Environment` (hml vs prod), `Component`
   (compute vs data vs network) e `CostCenter`.
3. **Budgets**: criar um AWS Budget por `Environment` ou `CostCenter` com alerta.
4. **Governança**: `Owner` e `ManagedBy` deixam claro responsável e origem
   (evita recurso órfão criado à mão).

## Onde ajustar
`owner` e `cost_center` são variáveis (`terraform.tfvars`). O resto é derivado de
`project` + `environment` no `local.common_tags` (provider `default_tags`).
