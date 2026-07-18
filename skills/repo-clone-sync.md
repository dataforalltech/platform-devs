# Skill: Clone & Sync Repositories

> **Relocada:** scripts e governança de frota vivem em `platform-infra/db/`.
> GitHub Actions está aposentado.

Antes de operar, consulte o ADR-002 do `platform-infra` e filtre somente
repositórios `active=true AND allows_automation=true`.

```bash
cd ../platform-infra
python db/clone_and_sync_repos.py --status
```

Clone, fetch, checkout, pull e prune em massa alteram estado local e podem
sobrescrever o contexto de trabalho do usuário; exigem autorização explícita.
Não agende cron nem crie workflow automaticamente.
