# Contratos e APIs

Contrato é qualquer interface que outros consomem: REST, evento Kafka, mensagem WebSocket, schema de DB compartilhado, função pública de lib compartilhada.

## Compatibilidade

| Mudança | Compatível? |
|---|---|
| Adicionar campo opcional | ✅ Sim |
| Adicionar endpoint novo | ✅ Sim |
| Tornar campo opcional (antes obrigatório) | ✅ Sim |
| Remover campo | ❌ Breaking |
| Renomear campo | ❌ Breaking |
| Mudar tipo de campo | ❌ Breaking |
| Tornar campo obrigatório (antes opcional) | ❌ Breaking |
| Mudar semântica (mesmo tipo, novo significado) | ❌ Breaking |
| Mudar código de status HTTP retornado | ❌ Breaking |
| Mudar formato de evento | ❌ Breaking |

## Versionamento

- **API REST**: versionar por path (`/v1`, `/v2`) ou header. Manter `v1` em paralelo durante deprecation.
- **Eventos**: versionar por nome do tópico (`orders.created.v1`, `orders.created.v2`).
- **DB compartilhada**: renomear em duas etapas (add+backfill+swap+remove).
- **Lib compartilhada**: semver. Breaking change → major bump.

## Errado

```python
# Removendo campo de evento sem versionar
event = OrderCreated(order_id=..., total=...)  # antes tinha 'customer_email'
publish("orders.created", event)  # consumidor v1 quebra
```

```python
# Tornando campo obrigatório silenciosamente
class CreateOrder(BaseModel):
    items: list[Item]
    customer_id: str  # antes era Optional[str]
```

## Correto

```python
# Versionar o evento
event_v2 = OrderCreatedV2(order_id=..., total=..., currency="BRL")
publish("orders.created.v2", event_v2)
# Continuar publicando v1 durante a janela de deprecation
publish("orders.created.v1", legacy_view(event_v2))
```

```python
# Manter compatibilidade durante migração
class CreateOrder(BaseModel):
    items: list[Item]
    customer_id: str | None = None  # opcional até consumidores migrarem

    @model_validator(mode="after")
    def _warn_missing(self):
        if self.customer_id is None:
            log.warning("create_order.missing_customer_id_deprecated")
        return self
```

## Checklist obrigatório de mudança de contrato

- [ ] Identificar **todos** os consumidores (grep no monorepo + lista de serviços).
- [ ] Determinar se é breaking (tabela acima).
- [ ] Se breaking: ADR com plano de migração + janela de deprecation.
- [ ] Atualizar schema (OpenAPI / AsyncAPI / DB migration).
- [ ] Comunicar consumidores via canal de coordenação.
- [ ] Atualizar libs cliente (se houver).
- [ ] Escrever teste de contrato no provider.
- [ ] Escrever teste de integração com pelo menos um consumidor.
- [ ] Atualizar README + changelog com semver bump correto.

## Hard stop

Se você não consegue listar os consumidores, **pare**. "Não tem consumidor" é
quase sempre falso — significa que você não procurou direito. Peça ajuda
humana antes de quebrar produção.
