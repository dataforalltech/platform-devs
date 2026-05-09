# Camada Frontend

O frontend é **consumidor** dos contratos definidos pelo backend. Ele não inventa regra de negócio.

## Pode

- Consumir contratos REST/WebSocket/GraphQL definidos pelo backend.
- Renderizar estados explícitos: loading, erro, vazio, sucesso.
- Validar entrada localmente para UX (feedback rápido) — mas backend valida sempre.
- Cache local seguindo o padrão do projeto (SWR, React Query, etc.).

## Não pode

- Inventar regra de negócio (cálculo de imposto, permissão, desconto).
- Esconder erro de API com `try/catch` que devolve estado falso.
- Manter cópia local de dado que pertence ao backend, fora do padrão de cache.
- Hardcoded de URL de API, tenant_id, feature flag, token.

## Errado

```typescript
// Esconder erro do backend no frontend
try {
  const order = await api.createOrder(payload);
  return order;
} catch {
  return { id: -1, status: "pending" };  // estado falso, esconde falha real
}
```

```typescript
// URL hardcoded
const API_URL = "https://prod.example.com/api";
```

```tsx
// Calculando imposto no frontend
const total = items.reduce((s, i) => s + i.price, 0);
const tax = total * 0.18; // imposto é regra de negócio do backend
```

## Correto

```typescript
// Propagar erro com contexto, deixar UI tratar
try {
  return await api.createOrder(payload);
} catch (err) {
  throw new OrderCreationError(err.message, { cause: err });
}
```

```typescript
// URL via configuração injetada
const API_URL = config.apiBaseUrl;
```

```tsx
// Pedir o total ao backend; frontend só renderiza
const { data } = useQuery(["order-total", orderId], () => api.getOrderTotal(orderId));
```

## Sinais de cross-layer fix (proibido)

- "Esconder erro 500 do backend mostrando dado mockado."
- "Aplicar regra de validação que devia estar na API."
- "Refatorar payload no frontend porque a API está em formato ruim" (corrija a API).
