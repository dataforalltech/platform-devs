# Política de fallback

Fallback é aceitável **somente** quando atende aos 4 critérios:

1. **Explícito** — nomeado, no caller, não escondido em camada baixa.
2. **Observável** — log + métrica + alerta.
3. **Testado** — happy path e fallback path.
4. **Documentado** — seção "Comportamento em falha" no README do serviço.

Tudo que não cumpre os 4 cai como **fallback silencioso** e é proibido.

## Casos em que fallback é proibido

- Fluxo financeiro/transacional sem ADR explícito.
- Quando o caller depende do resultado real para decisão crítica (ex.: cobrança, autorização, pagamento).
- Sem observabilidade (log + métrica + alerta).
- Quando o "fallback" mente para o caller (retorna `status: ok` sem ter feito a operação).

## Errado

```python
# Fallback silencioso — proibido
try:
    return payment.process(order)
except Exception:
    return {"status": "ok"}  # MENTIRA: pagamento não aconteceu
```

```python
# Try/except absorvendo tudo
try:
    return integration.call()
except:
    pass
```

```typescript
// Frontend escondendo erro
try {
  return await api.create(payload);
} catch {
  return { id: 0, ok: true };  // estado falso
}
```

## Correto

```python
# Fallback explícito + observável + testado
def fetch_user_profile(user_id: str) -> Profile:
    try:
        return external_provider.get(user_id)
    except ProviderTimeout:
        log.warning(
            "fallback_triggered",
            extra={"reason": "provider_timeout", "user_id": user_id, "fallback": "cache"},
        )
        metrics.inc("user_profile.fallback")
        cached = cache.get(user_id)
        if cached is None:
            raise UserProfileUnavailable(user_id)  # falha visível se cache vazio
        return cached
```

Esse fallback é permitido porque:

- A intenção está nomeada (`fallback`).
- Há log com motivo.
- Há métrica.
- Quando o cache também não tem o dado, a falha é propagada, não escondida.

## Alerta obrigatório

```yaml
# Exemplo de alerta de taxa de fallback
- alert: HighFallbackRate
  expr: rate(user_profile_fallback[5m]) / rate(user_profile_total[5m]) > 0.05
  for: 5m
  labels: {severity: warning}
  annotations:
    runbook: docs/runbooks/user-profile-fallback.md
```

## Checklist quando você adiciona um fallback

- [ ] É no caller, não em uma camada profunda.
- [ ] Log com `reason`, `service`, `correlation_id`.
- [ ] Métrica `<service>.fallback.count`.
- [ ] Alerta com runbook.
- [ ] Teste do happy path.
- [ ] Teste do fallback path.
- [ ] README do serviço documenta o comportamento em falha.
- [ ] Se for fluxo financeiro: ADR aprovado.
