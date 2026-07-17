# Camada Integrations

Toda chamada a sistema externo precisa de **timeout, retry, log e métrica**. Sem exceção.

## Pode

- Encapsular comunicação com sistema externo em cliente dedicado.
- Aplicar retry exponencial em erros transitórios (5xx, timeout).
- Aplicar circuit breaker para parceiro instável.
- Cache curto em integrações idempotentes.

## Não pode

- Chamar parceiro externo sem timeout.
- Engolir erro do parceiro com `try/except` genérico.
- Fallback para mock/dado fake em produção sem flag explícita + alerta.
- Reusar conexão sem health-check entre tenants/contextos.

## Errado

```python
# Sem timeout, sem retry, sem log
response = requests.get(url)
```

```python
# Engolindo o erro do parceiro
try:
    provider.charge(amount)
except Exception:
    pass  # silencioso
```

```python
# Mock em código produtivo
if env.PARTNER_DOWN:
    return {"status": "approved"}  # mente para o resto do sistema
```

## Correto

```python
import httpx

with httpx.Client(timeout=5.0) as client:
    log.info("provider_call_start", extra={"correlation_id": cid, "endpoint": url})
    try:
        resp = client.get(url)
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        log.warning("provider_call_failed", extra={"status": e.response.status_code})
        metrics.inc("provider.fail", labels={"status": e.response.status_code})
        raise
    finally:
        metrics.observe("provider.latency_ms", value=...)
```

```python
# Circuit breaker explícito
breaker = CircuitBreaker(fail_threshold=5, recovery_timeout=30)
with breaker:
    return provider.charge(amount)
```

## Checklist por integração

- [ ] Timeout definido (≤ 5s default; documentar se maior).
- [ ] Retry exponencial em erros transitórios.
- [ ] Log estruturado de start, success, failure.
- [ ] Métrica de latência + métrica de erro.
- [ ] Comportamento em falha documentado (`fallback.md`).
- [ ] Teste de timeout e teste de erro 5xx do parceiro.
