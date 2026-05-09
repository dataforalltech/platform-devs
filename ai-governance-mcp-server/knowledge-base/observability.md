# Observabilidade

Toda integração crítica precisa de **log + métrica + alerta**. Sem exceção.

## Padrões de log

Logs são **estruturados** (JSON), não livres. Campos obrigatórios:

- `request_id` (gerado no edge, propagado).
- `tenant_id` (quando aplicável).
- `user_id` (quando aplicável).
- `correlation_id` (quando há fluxo cross-service).
- `service`, `event` (nome curto do evento, snake_case).
- Nunca: token, senha, cartão, CPF, payload bruto com PII.

## Errado

```python
# Engolindo exceção
try:
    do_thing()
except Exception:
    pass

# Métrica sem unidade clara
metrics.timer("latency").observe(t)  # ms? s?

# Log sem contexto
log.info(f"Erro ao processar")
```

## Correto

```python
# Log + métrica + propagação
try:
    do_thing()
except ProviderError:
    log.exception(
        "provider_failed",
        extra={"correlation_id": cid, "provider": "x"},
    )
    metrics.inc("provider.fail", labels={"provider": "x"})
    raise

# Métrica com unidade no nome
metrics.histogram("provider_latency_ms", value=t_ms)

# Log com evento + extras
log.info("order_created", extra={"order_id": order.id, "tenant_id": tenant_id})
```

## Métricas obrigatórias por integração

- `<service>.calls.total` — counter de chamadas.
- `<service>.errors.total{type}` — counter de erros por tipo.
- `<service>.latency_ms` — histograma.
- `<service>.fallback.total` — quando aplicável.

## Alertas obrigatórios

Toda integração crítica precisa de alerta com **runbook**:

```yaml
- alert: ProviderHighErrorRate
  expr: rate(provider_errors_total[5m]) / rate(provider_calls_total[5m]) > 0.05
  for: 5m
  labels: {severity: warning}
  annotations:
    runbook: docs/runbooks/provider-errors.md
```

Alerta sem runbook é alerta inútil.

## Tracing

Quando há fluxo cross-service:

- Propagar `traceparent` (W3C Trace Context).
- Span por chamada externa.
- Atributos: `service.name`, `tenant.id`, `user.id`.
