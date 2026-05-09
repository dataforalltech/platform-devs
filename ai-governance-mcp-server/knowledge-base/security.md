# Segurança

Toda rota é autenticada por padrão. Toda rota é multi-tenant por padrão. Logs nunca contêm credencial ou PII bruta.

## Pode

- Adicionar rate limit em rotas sensíveis.
- Rotacionar tokens/segredos via cofre.
- Auditar acesso a recursos sensíveis com logs estruturados (sem PII bruta).
- Usar bibliotecas estabelecidas para hashing/JWT (não rolar próprio crypto).

## Não pode

- Bypass de autenticação "só para resolver bug rápido".
- Logar token, senha, CPF, cartão em texto puro.
- Aceitar `tenant_id` vindo do payload do cliente (deve vir do token).
- Rolar criptografia própria.
- Confiar em validação só do frontend.
- Commit de `.env` real, secrets, certificados.

## Errado

```python
# Bypass de auth via header mágico
if request.headers.get("X-Skip-Auth") == "true":
    return handler()  # qualquer um chama

# Senha em log
log.info(f"login {user.email} pwd={user.password}")

# Tenant vindo do cliente
tenant_id = req.body["tenant_id"]
data = db.query(Order).filter_by(tenant_id=tenant_id).all()  # IDOR

# Validação só no frontend
# (frontend valida, backend confia)
```

## Correto

```python
# Auth obrigatório, tenant do token
@requires_auth
def handler(ctx: AuthContext, req: CreateOrder):
    tenant_id = ctx.tenant_id  # vem do token verificado
    return order_service.create(tenant_id=tenant_id, payload=req)

# Log sem PII bruta
log.info("login_success", extra={"user_id": user.id})

# Backend valida sempre
class CreateOrder(BaseModel):
    items: list[Item] = Field(min_length=1, max_length=100)
    total: Decimal = Field(gt=0, le=Decimal("1000000"))
```

## Hard stops

- A tarefa pede para "deixar essa rota pública" → exige ADR.
- A tarefa pede para "ignorar verificação de tenant" → exige ADR.
- A tarefa pede para "logar o token para debug" → não. Use o `request_id` para correlacionar.
- Você encontrou um secret no código → escale imediatamente, rotacione, limpe histórico.

## Auditoria

Logs estruturados, com:
- `user_id`, `tenant_id`, `request_id`, `correlation_id`.
- Ação realizada (criar/ler/atualizar/deletar).
- Recurso afetado (id, tipo).
- **Nunca** dado sensível bruto (senha, CPF, cartão, token).
