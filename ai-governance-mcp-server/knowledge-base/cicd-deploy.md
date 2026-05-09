# Diretrizes de Deploy / CI/CD

> **Documento canônico** para qualquer agente de IA atuando em IaC, deploy,
> mudança de infraestrutura ou alteração de pipeline no ecossistema
> `dataforalltech`.
>
> Cobre: estágios obrigatórios, MCP tools requeridos por estágio, HARD STOPS
> antes de operar em produção, política de rollback.

---

## 1. Princípio fundamental

> **Nenhum agente de IA aplica mudanças em produção sem (a) plan revisado,
> (b) policy scan verde, (c) estimativa de custo dentro do threshold,
> (d) aprovação humana registrada em PR.**

Qualquer atalho que pule um desses 4 itens é violação direta de governança
(§15 HARD STOPS de AGENTS.md).

---

## 2. MCP tools por estágio do deploy

Cada estágio do pipeline exige um conjunto mínimo de MCP tools disponíveis
para o agente. **Operação sem o tier obrigatório é HARD STOP.**

### 2.1 Tier 1 — Obrigatórias (sem estes, agente NÃO opera)

| MCP Tool | Quando exigido | Por quê |
|---|---|---|
| `mcp-filesystem` | sempre | Ler/escrever `.tf`, `.tfvars`, planos, configs sem depender só de bash |
| `mcp-git` | sempre | Commitar IaC, verificar diff antes de apply, checar histórico de state |
| `mcp-github` | sempre | Abrir PRs de mudança de infra, verificar aprovações, bloquear sem review em prod |
| `mcp-shell` (ou `bash`) | sempre | Executar `terraform`, `az`, `kubectl`, `helm` com output capturado e auditável |

**HARD STOP**: se qualquer Tier 1 estiver indisponível, abortar e reportar.
Nunca tentar contornar com workarounds (ex.: editar arquivo via heredoc em
shell quando filesystem MCP está caído).

### 2.2 Tier 2 — Fortemente recomendadas

| MCP Tool | Quando exigido | Por quê |
|---|---|---|
| `mcp-azure` | tarefas Azure (ACR, AKS, Storage, KeyVault) | Introspecção do estado real antes de planejar mudança — não confiar só em `az` CLI |
| `mcp-kubernetes` | tarefas em clusters | Inspecionar pods, deployments, services após apply |
| `mcp-fetch` | qualquer deploy de serviço HTTP | Health check do endpoint depois do apply |
| `mcp-docker` | imagens publicadas/referenciadas | Verificar digest antes de referenciar em manifests (evita pull mutável `:latest`) |
| `mcp-slack` | operações críticas | Notificar canal SRE em apply prod, destroy, rollback |

**Comportamento sem Tier 2**: agente continua, mas deve registrar nas notas
de pendência da resposta final (formato §13 AGENTS.md) que a verificação foi
manual em vez de automatizada.

### 2.3 Tier 3 — Governança e segurança

| MCP Tool | Quando exigido | Por quê |
|---|---|---|
| `mcp-checkov` ou `mcp-tfsec` | qualquer `terraform plan` | Scan de policy-as-code antes do plan — **HARD STOP se falhar** |
| `mcp-vault` | qualquer leitura de segredo | Ler do HashiCorp Vault sem nunca expor em logs ou state |
| `mcp-infracost` | qualquer apply em prod | Estimativa de custo antes do apply — **agente NÃO aplica se delta > threshold** (default: +US$ 100/mês ou +20% do custo atual, o que for menor) |

**HARD STOP**: Tier 3 em apply prod é não-negociável. Plan ok mas checkov
falha → não aplica. Infracost > threshold → escalar para humano antes de
prosseguir.

### 2.4 Tier 4 — Observabilidade pós-deploy

| MCP Tool | Quando exigido | Por quê |
|---|---|---|
| `mcp-prometheus` | depois de qualquer apply em prod | Verificar métricas de saúde — error rate, latência p95, saturação |
| `mcp-grafana` | depois de mudança que afeta SLO | Confirmar que dashboards de SLO não degradaram dentro de 5min após apply |

**Comportamento sem Tier 4**: rollback é mais arriscado porque o agente
não sabe medir o efeito real da mudança. Documentar como pendência.

---

## 3. Estágios canônicos do pipeline

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Stage 1: Mudança proposta                                              │
│    Tools: filesystem, git, github                                       │
│    Saída: PR aberto com diff de IaC                                     │
└─────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────┐
│  Stage 2: Plan + scan estático                                          │
│    Tools: shell (terraform plan), checkov/tfsec, infracost              │
│    HARD STOP: checkov fail OR infracost > threshold OR plan == empty   │
│    Saída: plan output + scan report + cost estimate anexados ao PR      │
└─────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────┐
│  Stage 3: Review humano                                                 │
│    Tools: github (verificar aprovações)                                 │
│    HARD STOP: sem aprovação humana = sem apply em prod                  │
│    Saída: PR aprovado e merged                                          │
└─────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────┐
│  Stage 4: Apply                                                         │
│    Tools: shell (terraform apply), vault (segredos), azure/k8s          │
│    Notificação: slack (canal SRE em ops críticas)                       │
│    Saída: state atualizado + commit em repo de state                    │
└─────────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────────┐
│  Stage 5: Validação pós-apply                                           │
│    Tools: fetch (health check), kubernetes (pod state), prometheus      │
│            (métricas), grafana (SLO dashboard)                          │
│    HARD STOP: error rate > 5x baseline OR p95 > 2x baseline             │
│    Saída: confirmação ou rollback                                       │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 4. HARD STOPS específicos de CI/CD

Em adição aos §2 / §15 de AGENTS.md, o agente **PARA imediatamente** se:

| # | Situação | Ação |
|---|---|---|
| 1 | Qualquer Tier 1 indisponível durante operação | Reportar erro, abortar, escalar |
| 2 | `terraform plan` produz mudança em recurso `lifecycle.prevent_destroy = true` | Abortar, requer ADR explícito |
| 3 | `checkov` ou `tfsec` retornam HIGH/CRITICAL findings | Abortar, abrir issue, não aplicar |
| 4 | `infracost` estima delta > threshold (default +US$ 100/mês ou +20%) | Pausar, notificar canal Slack, aguardar aprovação humana |
| 5 | Mudança em namespace `kube-system`, `cert-manager`, ingress controllers | Requer ADR + aprovação SRE explícita no PR |
| 6 | `terraform destroy` em qualquer ambiente | Apenas com flag `--target` específica + confirmação humana no terminal |
| 7 | Edição direta de tfstate (`terraform state rm`, `terraform state push`) | Proibido em automação. Apenas humano em runbook |
| 8 | Apply em prod sem PR merged (estado direto no working tree) | Proibido. Sempre via merge → CI runner |
| 9 | Imagem Docker referenciada por tag mutável (`:latest`, `:dev`, `:main`) em manifests de prod | Substituir por digest SHA256 antes de aplicar |
| 10 | Segredo aparente em log do plan/apply (string base64, padrão de chave) | Abortar, rotacionar, escalar segurança |

---

## 5. Política de aprovação por ambiente

| Ambiente | Aprovação mínima | Tool obrigatório no apply |
|---|---|---|
| `local-dev` | nenhuma (auto) | shell |
| `cloud-dev` | 1 review de qualquer humano do time | shell + checkov |
| `cloud-hml` | 1 review do owner do serviço afetado | shell + checkov + infracost |
| `cloud-prod` | 1 review do owner + 1 SRE/platform-team | shell + checkov + infracost + vault + observabilidade pós-apply |

(Convenção de perfis canônica em AGENTS.md §48.)

---

## 6. Errado vs Correto

### Errado

```bash
# Aplicar sem plan revisado
terraform apply -auto-approve
```

```bash
# Pular checkov com flag para passar build
terraform plan && terraform apply  # checkov skipped via env var
```

```yaml
# Manifest com tag mutável em prod
spec:
  containers:
    - image: registry/app:latest   # ❌ não-determinístico
```

```python
# Agente lendo segredo direto do tfstate
state = subprocess.run(["terraform", "state", "show", "vault.password"])
print(state.stdout)  # ❌ leak em log
```

### Correto

```bash
# Plan → review → apply
terraform plan -out=tfplan
# (plan anexado ao PR, checkov + infracost executados como CI)
# (humano aprova PR)
terraform apply tfplan
```

```yaml
# Manifest com digest imutável
spec:
  containers:
    - image: registry/app@sha256:abc123def...   # ✅ pinned
```

```python
# Agente lê via Vault MCP (nunca toca state)
secret = mcp_vault.read("secret/data/app/password")  # nunca aparece em log
```

---

## 7. Resposta final do agente em tarefa de CI/CD

Além das seções padrão (§13 AGENTS.md), tarefa de CI/CD deve incluir:

```markdown
### Plan output
- terraform plan: <N> to add, <M> to change, <K> to destroy
- Recursos afetados: ...

### Policy scan
- checkov: PASS (<N> rules) | FAIL (<N> rules) — output anexado
- tfsec: PASS | FAIL — output anexado

### Cost estimate
- infracost diff: <±US$ X/mês> (<+Y%>)
- Threshold: +US$ 100/mês ou +20%, o que for menor
- Status: dentro / fora do threshold

### Observabilidade pós-apply
- Health check do endpoint: <status>
- prometheus error_rate: <baseline → atual>
- prometheus latency_p95: <baseline → atual>
- grafana SLO dashboards: <link> — sem regressão / regressão detectada

### Rollback plan
- Comando: ...
- Tempo estimado: ...
- Quem pode acionar: ...
```

---

## 8. Validação automatizada via `validate_agent_decision`

Agentes devem chamar `validate_agent_decision` antes de qualquer apply,
declarando explicitamente:

- `affected_layers: ["infrastructure"]`
- `modifies_security: true` se toca em RBAC, RLS, segredos, IAM
- `proposed_change`: incluindo "terraform plan output" ou similar

O validator marca `risk_level=critical` (bloqueia) se:

- Detecta `terraform apply` sem `-target` em descrição que menciona produção
- Detecta `kubectl apply` em namespace de sistema sem ADR
- Detecta tag mutável em image manifest de prod
- Detecta `state rm` ou `state push`

---

## 9. Referências

- AGENTS.md §2 (proibições explícitas)
- AGENTS.md §11 (segurança)
- AGENTS.md §15 (HARD STOPS universais)
- AGENTS.md §48 (perfis de ambiente)
- DEVOPS_STANDARDS.md (padrões operacionais completos)
- `forbidden-actions.md` (catálogo canônico de ações proibidas)
- `infrastructure.md` (responsabilidades da camada de infra)
- `observability.md` (métricas e logs estruturados)
