# Política operacional — infra-mcp-server

> **Phase 1 (este release)**: operações **read-only** de inspeção/validação
> (terraform plan/validate/fmt/show, checkov, infracost). Mutação direta
> (apply/destroy/state) **proibida** nessa fase.
>
> **Phase 2 (próximo)**: VM allocator. Agentes solicitam capacidade; o servidor
> orquestra share-or-provision. Phase 1 vira primitiva interna. Provisionamento
> só dentro de specs pré-aprovadas + dentro de budget. Detalhes em ADR-0001.

## 1. Princípio fundamental

**Phase 1**: agentes **planejam, validam, estimam**; humano aplica.

**Phase 2**: agentes **solicitam recursos** via `request_vm(...)`; servidor
decide aproveitar VM existente (compartilhamento, otimização de custo) ou
provisionar uma nova (dentro de budget e specs aprovadas). Agentes **nunca**
rodam `terraform apply` por conta própria — o allocator é o único caminho.

Em ambas fases: **mudança em rede, IAM, DNS, certificados continua sendo
operação humana** com runbook + revisão.

## 2. Toolchain consumida

| Tool MCP | CLI subjacente | O que retorna |
|---|---|---|
| `terraform_validate` | `terraform validate -json` | Diagnostics estruturados |
| `terraform_fmt_check` | `terraform fmt -check -diff -recursive` | Lista de arquivos não-formatados + diff |
| `terraform_plan` | `terraform plan -no-color -out -detailed-exitcode` | Resumo (add/change/destroy) + path .tfplan |
| `terraform_show_plan` | `terraform show -json <plan>` | Plan estruturado (recursos por ação) |
| `policy_scan_checkov` | `checkov -d <path> -o json --soft-fail` | Findings por severity, hard_stop=True se HIGH/CRITICAL |
| `cost_estimate_infracost` | `infracost diff --path <tfplan> --format json` | Delta $ + breakdown, hard_stop por threshold |

## 3. HARD STOPS aplicáveis (do `ai-governance/cicd-deploy.md`)

Antes de propor qualquer aplicação ao humano, valide que NENHUM destes está
ativo no plan:

1. **HIGH/CRITICAL em checkov ou tfsec** → `policy_scan_checkov.hard_stop=True` aborta o fluxo.
2. **delta de custo > threshold** → `cost_estimate_infracost.hard_stop=True` exige aprovação humana.
3. **`terraform_plan` mostrando `destroy` em recurso com `lifecycle.prevent_destroy = true`** → ADR explícito obrigatório.
4. **Mudança em namespace `kube-system`, `cert-manager`, ingress controllers** → revisão SRE.
5. **Image manifest com tag mutável (`:latest`, `:dev`, `:main`) em prod** → substituir por digest.
6. **Mudança em `tfstate` direta** → não cabe nesse servidor; runbook humano.
7. **`terraform destroy` em qualquer ambiente** → fora do escopo deste servidor (Phase 1).

## 4. Fluxo recomendado para o agente

```
1. terraform_fmt_check         (estilo)
2. terraform_validate          (sintaxe + tipo)
3. terraform_plan              (gera .tfplan binário)
4. terraform_show_plan         (lê o plan estruturado)
5. policy_scan_checkov         (hard_stop em HIGH/CRITICAL)
6. cost_estimate_infracost     (hard_stop por threshold)
7. Se tudo verde → propor PR ao humano com plan + scan + cost anexados.
   Se algum hard_stop → relatar ao humano, NÃO continuar.
```

## 5. Observabilidade

Cada chamada emite log JSON em stderr com:

- nome da tool
- `args_keys` (não os valores — defesa contra leak)
- duração ms
- exit code do subprocess
- truncamento aplicado (se output > limit)

Stderr de subprocesso é parcialmente redacted (heurística simples regex
sobre `token|secret|password|key|credential`).

## 6. Não é objetivo

### Fora desta versão (Phase 1)

- `terraform apply` / `destroy` direto pelo agente.
- Lifecycle de VM (`request_vm`, etc.).

### Fora permanente (mesmo Phase 2+)

- Edição de tfstate (`state rm`, `state push`).
- Provisionamento de credenciais (criação de SP, role assignments, KeyVault writes).
- Modificação de network ACL, NSG, firewall, DNS, certificados.
- Leitura de **valor** bruto de segredo (Phase 3 entrega só metadata: id + version, nunca o valor).
- Provisionamento de redes (VNet, subnet) — humano em runbook.

## 7. Phase 2 — allocator (preview)

Quando o allocator estiver implementado, esta seção vira a referência
operacional. Conceitos chave:

- **VMSpec catalog**: `cpu-small`, `cpu-medium`, `gpu-a100`, `high-mem`. Specs novas exigem ADR + aprovação.
- **VMLease**: cada slot tem TTL absoluto (default 24h, máx 72h com renovação). Após TTL → auto-release + GC se VM ficou órfã.
- **Sharing**: agentes que pedem `exclusive=false` competem por slots em VMs já provisionadas. Compatibilidade definida por imagem base + isolamento (cgroup/namespace) — não compartilha workloads sensíveis sem revisão.
- **Cost cap**: budget por agente (ex.: $5/hora) + total/dia ($50/dia). Allocator nega request que furaria o cap; humano libera quota out-of-band.
- **Audit trail**: cada `request_vm` / `release_lease` é evento JSONL persistido (tipo `audit_store` do `ai-governance-mcp-server`). Operations team pode auditar quem alocou o quê.

## 7. Pré-requisitos no host

| Binário | Min version | Tool dependente |
|---|---|---|
| `terraform` | 1.5+ | terraform_validate, fmt_check, plan, show_plan |
| `checkov` | 3.0+ | policy_scan_checkov |
| `infracost` | 0.10+ | cost_estimate_infracost |

Sem o binário → tool retorna `{"error": "binary_not_found", ...}`.
Sessão segue funcionando para outras tools.
