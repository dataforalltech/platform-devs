# platform-catalog — Capability Registry (Fase 1)

Implementação da **Fase 1** do roadmap de Control Plane: o **Capability Registry** como
*source of truth* do domínio. Concretiza [ADR-009](../ADR-009-CAPABILITY-REGISTRY.md)
(registry), [ADR-010](../ADR-010-PLATFORM-CATALOG.md) (meta-modelo de kinds) e
[ADR-011](../ADR-011-DISCOVERY.md) (Discovery API).

**Ideia:** o platform-dev deixa de ser organizado por MCP server e passa a expor
**capabilities/operations por domínio**. Os MCP servers viram *providers técnicos*.

```
Domain ⊃ Capability ⊃ Operation ──1..N──▶ Tool ──▶ Provider
```

## Conteúdo

| Peça | Papel |
|---|---|
| `seed/tool_inventory.json` | snapshot dos **298 tools** dos 20 MCP servers (da auditoria) — input reproduzível |
| `platform_catalog/models.py` | envelope ADR-010 (apiVersion/kind/metadata/spec/relations) + specs ADR-009 |
| `platform_catalog/derive.py` | derivação **determinística** (server→domínio, verbo→efeitos/risco, capability→authz) |
| `platform_catalog/generate_seed.py` | gera `catalog/` a partir do inventário (merge de Operations por id) |
| `catalog/{operations,tools,providers}/*.yaml` | o catálogo materializado (288 operations · 298 tools · 20 providers) |
| `platform_catalog/registry.py` | `CatalogStore` — carrega o catálogo + Discovery API (ADR-011 D11.2) |
| `platform_catalog/app.py` | serviço HTTP FastAPI (:8000) — substitui o service-discovery do `mcp-registry.py` |

## Uso

```bash
pip install -e ".[dev]"
python -m platform_catalog.generate_seed      # regenera catalog/ do inventário
python -m platform_catalog.app                # sobe a Discovery API em :8000
pytest -q                                     # 12 testes
```

### Discovery API (ADR-011)

```
GET /v1/operations?domain=|resource=|effect=|owner=|risk=|q=
GET /v1/operations/{uid}
GET /v1/operations/{uid}/tools        # bindings (portabilidade: N providers)
GET /v1/operations/{uid}/resolve      # seleção do melhor Tool (D11.6)
GET /v1/providers · /v1/providers/{id}
GET /v1/stats
```

## Qualidade do seed (curadoria incremental — ADR-009 D9.10)

O seed é **derivado por heurística determinística**, não curado à mão: `domain` é preciso
(mapa server→domínio); `resource`/`effects`/`blast_radius`/`risk` são aproximações
transparentes e testáveis, subordinadas a curadoria posterior. O `id` canônico é
`<domínio>.<tool>`; tools iguais de providers diferentes mergeiam numa Operation com N
bindings (ex.: `product.generate_feature_spec` = product-owner + product-manager).

## Próximas fases (ver `MCP_ADR_INDEX.md`)

2. Resource + Effect model como enforcement no PDP · 3. Policy/Risk engine ·
4. Events no Kafka · 5. Asset Catalog · 6. Expansão dos runbooks.
