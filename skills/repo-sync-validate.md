# Skill: Repository Sync & Validate

> **Relocada:** a automação de frota vive em `platform-infra/db/`. GitHub Actions
> está aposentado. Este arquivo apenas aponta para a fonte atual.

Use `platform-infra/db/validate_and_sync_repos.py` e respeite o filtro canônico
`active=true AND allows_automation=true` do ADR-002. Validação read-only é livre;
reconciliação, clone/sync em massa e qualquer efeito externo exigem autorização.

```bash
cd ../platform-infra
python db/validate_and_sync_repos.py --validate --report
python scripts/validate_no_github_actions.py
```

Até existir executor aprovado, a execução é manual/controlada e seus logs devem
ser retidos. Não crie cron, workflow ou automação recorrente sem pedido explícito.
