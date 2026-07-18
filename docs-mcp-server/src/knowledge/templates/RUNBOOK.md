# Runbook — {{service_name}}

## Escopo

Operação do serviço `{{service_name}}` no Docker Swarm. Kubernetes é experimental
e GitHub Actions está aposentado. Substitua todos os placeholders e registre as
evidências reais; este template não comprova o ambiente.

## Pré-requisitos

- autorização e change/ticket;
- acesso de menor privilégio ao manager Swarm;
- digest aprovado da imagem e digest anterior para rollback;
- referências de secrets no Vault, sem copiar valores para este documento;
- dashboards, logs e contato on-call: `{{oncall}}` / `#{{slack_channel}}`.

## Health e observabilidade

```bash
curl --fail --silent http://{{host}}:{{port}}/health
docker service ps {{service_name}} --no-trunc
docker service logs {{service_name}} --since 15m
```

Grafana: `https://grafana.internal/d/{{service_name}}`.

## Deploy controlado

GitHub Actions não executa este fluxo. O operador promove o mesmo digest aprovado:

```bash
IMAGE={{registry}}/{{image_name}}@sha256:{{digest}}
docker service update --image "$IMAGE" {{service_name}}
docker service ps {{service_name}} --no-trunc
```

Após convergência, execute health, smoke pelo gateway e verifique erro, latência e
traces. Registre commit, digest, operador, aprovador, horário e resultado.

## Escala

A escala é estática e exige autorização:

```bash
docker service scale {{service_name}}={{replicas}}
```

## Rollback

```bash
docker service rollback {{service_name}}
# ou repointe explicitamente o digest anterior aprovado
docker service update --image {{registry}}/{{image_name}}@sha256:{{previous_digest}} {{service_name}}
```

Comprove nova convergência, health, smoke e observabilidade e registre o incidente.

## Troubleshooting

| Sintoma | Verificação | Ação segura |
|---|---|---|
| Erros 5xx | logs, dependências, pool e traces | interromper promoção; rollback se regressão |
| Timeout | latência, saturação, DB e downstream | mitigar conforme runbook; escala só com autorização |
| Erros 401/403 | issuer, audience, JWKS e policy | corrigir configuração; não desabilitar auth |
| Task reiniciando | `docker service ps --no-trunc` e logs | corrigir causa ou rollback |

## Contatos

- Owner: `{{owner}}`
- On-call: `{{oncall}}`
- Canal: `#{{slack_channel}}`
- PagerDuty: `{{pagerduty_service}}`
