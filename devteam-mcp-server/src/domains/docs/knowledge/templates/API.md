# API Reference — {{service_name}}

**Base URL:** `{{base_url}}`
**Versão:** `{{version}}`
**Formato:** JSON

## Authentication

Todas as requisições devem incluir o header de autorização:

```
Authorization: Bearer <token>
```

Tokens são obtidos via endpoint de autenticação ou gerados no painel administrativo.
Tokens expiram após 24 horas. Use o endpoint de refresh para renovar sem novo login.

## Endpoints

### GET /health

Verifica o status do serviço. Não requer autenticação.

**Response 200:**

```json
{
  "status": "ok",
  "version": "1.0.0",
  "uptime_seconds": 3600
}
```

### GET /api/v1/resource

Lista recursos com paginação.

**Query params:**

| Param | Tipo | Descrição | Default |
|-------|------|-----------|---------|
| `page` | int | Número da página | `1` |
| `limit` | int | Itens por página (máx 100) | `20` |
| `sort` | string | Campo para ordenação | `created_at` |
| `order` | string | `asc` ou `desc` | `desc` |

**Response 200:**

```json
{
  "items": [],
  "total": 0,
  "page": 1,
  "limit": 20,
  "pages": 0
}
```

### GET /api/v1/resource/{id}

Retorna um recurso pelo ID.

**Path params:**

| Param | Tipo | Descrição |
|-------|------|-----------|
| `id` | uuid | ID do recurso |

**Response 200:**

```json
{
  "id": "uuid",
  "name": "string",
  "description": "string",
  "created_at": "ISO8601",
  "updated_at": "ISO8601"
}
```

### POST /api/v1/resource

Cria um novo recurso.

**Request body:**

```json
{
  "name": "string",
  "description": "string"
}
```

**Response 201:**

```json
{
  "id": "uuid",
  "name": "string",
  "description": "string",
  "created_at": "ISO8601"
}
```

### PUT /api/v1/resource/{id}

Atualiza um recurso existente.

**Request body:** mesmo formato do POST (todos os campos opcionais).

**Response 200:** recurso atualizado.

### DELETE /api/v1/resource/{id}

Remove um recurso.

**Response 204:** sem corpo.

## Error Codes

| Code | Descrição |
|------|-----------|
| 400 | Bad Request — payload inválido ou parâmetros faltando |
| 401 | Unauthorized — token ausente ou inválido |
| 403 | Forbidden — sem permissão para o recurso |
| 404 | Not Found — recurso não encontrado |
| 409 | Conflict — recurso já existe |
| 422 | Unprocessable Entity — validação de schema falhou |
| 429 | Too Many Requests — rate limit excedido |
| 500 | Internal Server Error — erro interno do servidor |

## Examples

### Listar recursos com filtro

```bash
curl -H "Authorization: Bearer $TOKEN" \
  "{{base_url}}/api/v1/resource?limit=10&sort=name&order=asc"
```

### Criar recurso

```bash
curl -X POST \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"name": "meu-recurso", "description": "Descrição"}' \
  "{{base_url}}/api/v1/resource"
```
