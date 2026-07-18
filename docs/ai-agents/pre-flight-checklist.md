# Pre-flight checklist para agentes

Antes de alterar o ecossistema:

1. registre ou retome a sessão via `session-mcp`;
2. leia `AGENTS.md`, `README.md` e as decisões relevantes;
3. descreva o problema em uma frase e identifique a camada responsável;
4. procure implementação equivalente antes de criar abstração;
5. liste contratos e consumidores afetados;
6. avalie segurança, migração e rollback;
7. limite o diff aos arquivos necessários;
8. defina testes, documentação e configuração que precisam acompanhar a mudança;
9. pare se faltar autorização, ownership ou coordenação entre repositórios;
10. execute validações locais sem GitHub Actions e registre o resultado na sessão.
