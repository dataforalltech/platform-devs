# Runbook — {{service_name}}

## Overview

Procedimentos operacionais para o serviço `{{service_name}}`.
Este documento descreve como operar, monitorar e fazer troubleshooting do serviço em produção.

## Prerequisites

- Acesso ao cluster Kubernetes / Docker Swarm
- Credenciais de produção configuradas localmente
- `kubectl` ou `docker` instalado e configurado
- Acesso ao canal de on-call: #{{slack_channel}}

## Health Check

```bash
curl http://{{host}}:{{port}}/health
```

Resposta esperada: `{"status": "ok", "version": "1.0.0"}`

Verificar métricas no Grafana: `https://grafana.internal/d/{{service_name}}`

## Steps

### Deploy

```bash
# via workflow GitHub Actions (recomendado)
gh workflow run cd-prod.yml -f tag=v{{version}}

# verificar status do deploy
gh run list --workflow=cd-prod.yml --limit=5
```

### Restart

```bash
# Docker
docker restart {{container_name}}

# Kubernetes
kubectl rollout restart deployment/{{service_name}} -n production
kubectl rollout status deployment/{{service_name}} -n production
```

### Ver Logs

```bash
# Docker
docker logs -f {{container_name}} --tail 100

# Kubernetes
kubectl logs -f deployment/{{service_name}} -n production --tail 100

# Filtrar por nível de log
kubectl logs deployment/{{service_name}} -n production | grep ERROR
```

### Escalar Réplicas

```bash
kubectl scale deployment/{{service_name}} --replicas=3 -n production
```

## Rollback

```bash
# Reverter para versão anterior via workflow
gh workflow run cd-prod.yml -f tag=v{{previous_version}}

# Ou rollback direto no Kubernetes
kubectl rollout undo deployment/{{service_name}} -n production
```

## Troubleshooting

| Sintoma | Causa provável | Ação |
|---------|---------------|------|
| 500 errors | Banco indisponível | Verificar conexão DB, checar logs |
| Timeout nas respostas | Alta carga | Escalar réplicas |
| 401 errors | Token expirado | Renovar credenciais no Vault |
| Pod em CrashLoopBackOff | Erro na inicialização | `kubectl describe pod` + logs |
| Alto uso de memória | Memory leak | Restart + abrir issue |

## Contatos de Emergência

- On-call: @{{oncall}}
- Canal: #{{slack_channel}}
- PagerDuty: `{{pagerduty_service}}`
- Escalação: @{{owner}}
