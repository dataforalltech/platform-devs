# HANDOFF — Remediação de Segurança + Console de Parceiro (jul/2026)

**Status:** ✅ concluído e validado no HML; tudo mergeado na `develop`. **Registro profundo:** [remediation-2026-07-consolidated](remediation-2026-07-consolidated.md).

---

## Estado atual (o que está pronto)

- **C1 (crítico) corrigido na raiz** (F02): bypass removido, S2S migrado para `/api/internal/*`. Contido no edge (nginx 404) até o deploy pela develop.
- **Tecido S2S de IAM repontado** (auth, notification, analytics, customer-admin, crm, admin self) para `/api/internal[/iam]`.
- **H1** (isolamento por tenant), **RS256** (operador + cliente), **M3** (`partner_id` via `adm_user_external_link`) — todos na develop.
- **Console de Parceiro funcionando** (`/api/v1/partner/dashboard → 200`) — 6 camadas cabeadas (gateway route, M3, provisão, seed, RS256, refresh-proof).
- **Limpeza `node_modules`** no platform-devs (38.396 → 2.103 arquivos rastreados).
- **Imagens canônicas do develop** no ACR (:latest + :sha) e rodando no box: platform-admin(+mcp) `b1400d6`, dataforall-customer-admin `953ba5e`, platform-auth `f8d0057`, platform-notification(+mcp) `3b020ba`/`3917ce5`, **platform-dataforall-admin `6cefacc`** (RS256, redeployado 09-jul).

## Como acessar / operar

- **HML:** EC2 `i-002379444ffb89c10`, **só via AWS SSM** send-command (não há SSH). Payload em base64 + `LC_ALL=C tr -cd '[:print:][:space:]'`; fetch com `PYTHONIOENCODING=utf-8`.
- ⚠️ **Relógio do box adiantado** — use `docker logs --tail N`, não `--since`.
- **Build on-box:** `/opt/dataforall/deploy/build/build-service.sh <img> <repo> <branch>` (clona do GitHub, BuildKit com secret github_token, push ACR :latest+:sha). `admin-mcp` precisa do `platform-admin:dtr-local` primeiro (FROM).
- **Deploy:** composes por-serviço em `/opt/dataforall/deploy/services/<svc>/docker-compose.yml` (não é git checkout; imagem via `${IMAGE_TAG:-latest}`).
- **Seeds:** `deploy/seed/` — inclui `register-partner-gateway-route.sh` (rota /partner) e os seeds de superadmin/tenant.

## Contrato de auth (memorizar)

- **Externo:** `/api/v1/*` + JWT de usuário. **S2S:** `/api/internal/*` + `X-Internal-Token`. **Público:** `V1_PUBLIC_ROUTERS`.
- **Chave RS256:** `jwt-auth.pem` (do platform-auth, `kid=platform-auth-1`) — reusada por admin e customer-admin p/ **assinar**; verificação via JWKS do platform-auth (`/internal/.well-known/jwks.json`, `aud=platform-services`).

## Próximos passos (pendências)

1. **CI da develop está VERMELHO** (pré-existente: lint/security-scan/sast/secret-scan; `test` fica skipped). Bloqueia o pipeline `cd-dev` automático → por isso os deploys foram on-box. **Sanear os scans** pra o pipeline voltar a produzir `:develop-latest` e deployar.
2. **Console de parceiro em outros ambientes:** replicar via o seed (`register-partner-gateway-route.sh`) + rodar as migrations do customer-admin no onboarding de tenant; e a config RS256+chave no compose.
3. **crm** config.py default `/api/v1/iam` (repo não-local) — coberto pelo compose; repontar no repo.
4. **28 E2E do admin_mcp** testam `/mcp/tools/*` mas o servidor serve `/v1/*` (drift) — reconciliar.
5. ✅ **Operador RS256 — resolvido 09-jul:** `platform-dataforall-admin` estava HS256 no deploy (compose+imagem 06-jul) vs código develop RS256 fail-closed. Corrigido: compose→RS256 (`c8db3d6`) + rebuild (`6cefacc`) + redeploy validado (boot RS256 healthy, aud segregada `service-clients`). Detalhe: env-vars §5.1.
6. **RBAC-03** aud-por-serviço (o mesh reusa `aud=platform-services`; operador já é `service-clients`) — diferido.

## Riscos / cuidados

- **Não tocar o platform-auth** para RS256/JWKS (decisão): o customer-admin/admin reusam a chave dele.
- **Deploy ordering:** F02 (o `/api/internal` no platform-admin) precisa vir **antes/junto** dos repoints dos callers, senão 404 no S2S.
- **Não commitar** `deploy/secrets/` nem `*.local.yml` (segredos/overrides locais).
- Stashes preservados nos repos (deploy-wip etc.) — `git stash list` por repo.

## Referências

- [remediation-2026-07-consolidated](remediation-2026-07-consolidated.md) (profundo) · [f02-auth-s2s-remediation](f02-auth-s2s-remediation.md) · [../INDEX.md](../INDEX.md)
- Memória: `pentest-auth-bypass-critical`, `partner-console-wiring`, `dataforall-hardening-policy`, `repo-node-modules-committed`.
