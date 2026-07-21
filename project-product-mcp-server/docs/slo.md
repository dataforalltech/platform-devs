# SLO

- Disponibilidade mensal API: 99,9%.
- Disponibilidade mensal MCP: 99,9% excluindo decisões `deny`/`pending` válidas.
- p95 API read: 300 ms; p95 write: 600 ms, sem incluir espera por aprovação humana.
- Error budget e alertas são segmentados por tenant sem incluir identificadores sensíveis.
