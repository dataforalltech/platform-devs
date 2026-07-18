# Descoberta e configuração de MCPs

**Status:** ativo
**Última revisão:** 2026-07-18

## Visão geral

A descoberta tem duas superfícies distintas:

1. o `platform-tunnel` conecta clientes locais ao gateway MCP real;
2. o `mcp-registry` expõe uma projeção somente leitura dos manifests ativos.

O inventário operacional não é mantido manualmente em código. Ele é gerado a partir de
`manifests/mcps/*.yaml` e `contracts/tools/*.yaml`.

## Uso local com platform-tunnel

Com o `dftunnel` instalado e o perfil local autenticado:

```powershell
dftunnel mcp check
```

Esse comando inicializa a ponte, executa `tools/list` no gateway e mostra as tools
realmente disponíveis. A autenticação e a seleção do endpoint pertencem ao
`platform-tunnel`; este repositório não copia tokens nem URLs para `.mcp.json`.

O `.mcp.json` deste projeto é uma projeção exclusiva de provedores stdio diretos ativos.
No estado atual ele não contém servidores: `devteam-mcp` é gateway-only e recusa execução
stdio sem tenant verificado. Um arquivo vazio é, portanto, resultado válido e esperado.

## Registry HTTP

O registry lê somente `generated/mcp-runtime-registry.json`.

| Endpoint | Uso |
|---|---|
| `GET /v1/health/live` | liveness do processo |
| `GET /v1/health/ready` | valida registry e configuração dos provedores ativos |
| `GET /services` | lista provedores manifestados e sua disponibilidade |
| `GET /services/{name}` | consulta um provedor |

Não existem endpoints de mutação, auto-registro ou fallback hardcoded.

## Estados de ciclo de vida

| Estado | Runtime gerado | Regra |
|---|---:|---|
| `active` | sim | implementação, segurança e configuração comprovadas |
| `experimental` | não | integração real identificada, ainda sem promoção operacional |
| `planned` | não | catálogo de produto; sem tools, CI, gateway ou registry |
| `deprecated` | não | mantido apenas para migração |
| `disabled` | não | bloqueado por segurança ou ausência de contrato executável |

Somente `active` entra em `.mcp.json`, compose e runtime registry.

## Alterando o catálogo

1. edite ou crie o manifest canônico;
2. adicione contratos para tools de alto risco;
3. valide paths, portas, dependências e ciclo de vida;
4. regenere as projeções;
5. verifique que não existe drift.

```powershell
python scripts/validate_mcp_manifests.py
python scripts/audit_mcp_inventory.py
python scripts/generate_mcp_artifacts.py
python scripts/generate_mcp_artifacts.py --check
```

Não registre uma implementação apenas em compose, `.mcp.json` ou dicionário Python. O
validador de inventário falha quando encontra um diretório `*-mcp-server` sem cobertura
por manifest.
