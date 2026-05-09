# Camada Backend

O backend é **autoridade** sobre os contratos. Ele define, valida e versiona.

## Pode

- Definir e versionar contratos (REST/eventos).
- Validar entrada (autoritativo) e aplicar regras de negócio.
- Garantir observabilidade: logs estruturados + métricas.
- Emitir eventos de domínio com schema versionado.
- Retornar erros estruturados com código + mensagem genérica para tela.

## Não pode

- Vazar UX para a API (texto formatado para tela, traduções, cores, ícones).
- Fallback silencioso convertendo erro 500 em 200.
- Misturar lógica de transporte com lógica de negócio.
- Aceitar input do cliente como tenant_id (deve vir do token).
- Engolir erro de integração com `try/except` genérico.

## Errado

```python
# Fallback silencioso
try:
    return process_order(req)
except Exception:
    return {"status": "ok"}  # mente para o cliente
```

```python
# Mensagem de UX no backend
raise HTTPException(500, "Ocorreu um erro, tente novamente em alguns minutos")
```

```python
# Tenant vindo do payload do cliente (vulnerável)
tenant_id = req.body.get("tenant_id")
```

## Correto

```python
# Falha visível, log estruturado, exceção tipada
try:
    return process_order(req)
except ProviderError as e:
    log.exception("provider_failed", extra={"order_id": req.order_id})
    metrics.inc("provider.fail")
    raise HTTPException(502, detail={"code": "provider_unavailable"})
```

```python
# Erro estruturado, sem texto de UI
raise HTTPException(
    409,
    detail={"code": "order_already_paid", "message": "Order is already paid"},
)
```

```python
# Tenant vem do token autenticado
tenant_id = ctx.tenant_id  # populado pelo middleware de auth
```

## Padrões de observabilidade

- Toda rota: `request_id`, `tenant_id`, `user_id` em todos os logs.
- Toda integração externa: timeout, retry exponencial, log de tentativa, métrica.
- Erros de domínio: log em `INFO`/`WARNING`. Erros inesperados: `log.exception`.

---

## Padrões de WebSocket

### Autenticação JWT

Usar `decode_token` (API pública de `platform_auth.jwt_manager`), **nunca** `_verify_token` diretamente:

```python
# Correto — API pública, respeita AUTH_DEV_BYPASS
from platform_auth.jwt_manager import decode_token

def _decode(token: str | None) -> dict:
    if not token:
        return {}
    try:
        return decode_token(token)
    except Exception:
        return {}
```

`decode_token` e `_verify_token` têm comportamento idêntico — o primeiro é alias público do segundo.  
Com `AUTH_DEV_BYPASS=true` + `ENVIRONMENT=development`: assinatura não é verificada (útil em dev local).

### Middleware vs WebSocket

`BaseHTTPMiddleware` (TenantMiddleware, RequestLogging, etc.) **ignora escopos WebSocket** — só processa `http`.  
Auth de WS deve ser feita no handler da rota, não em middleware.

### `close()` antes de `accept()`

Chamar `websocket.close(code=X)` **antes** de `websocket.accept()` faz o uvicorn converter em HTTP 403  
durante o handshake. Sempre chamar `accept()` primeiro, depois `close()` se necessário:

```python
await websocket.accept()   # ← primeiro
await websocket.close(code=4001)  # ← depois, se autenticação falhar
```

### Reconnect storm

Causado quando `onopen` reseta `retryCount = 0` e `onclose` dispara reconexão imediata.  
O contador sempre fica em 0, gerando "reconnect #1" infinito enquanto o problema persistir.  
Resolver o problema no servidor (auth, serviço offline) — não no cliente.

### platform-ws-lib vs handler manual

- Usar `WSRouter` da `platform-ws-lib` para novos canais: cuida de auth, session tracking, displacement.
- Handler manual (como em `platform-analytics/routers_ws.py`): necessário para canais com lógica específica  
  de broadcast (snapshot-on-connect, ping loop, hub interno).
