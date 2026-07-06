# Migração segura dos volumes MySQL (persistência de PATs/twins)

> Objetivo: mover os dados dos MySQL para volumes nomeados sob o projeto correto
> (`dataforall-infra`), eliminando o risco de wipe acidental. **Copia (não move) — reversível.**
> Nada aqui foi aplicado.

## Problema

- Containers `dataforall-admin-mysql` / `dataforall-tenant-mysql` definidos em
  `platform-devs/deploy/docker-compose.infra.yml` (projeto `dataforall-infra`), com volumes
  **sem `name:` explícito** (`admin-mysql-data`, `tenant-mysql-data`).
- Mas os volumes que RODAM pertencem ao projeto `platform-service-template`:
  `platform-service-template_mysql-admin-dev-data` e `platform-service-template_mysql-local-data`.
  Os containers foram subidos por um compose (`platform-service-template/infra/docker-compose-infra-local.yml`)
  que **foi DELETADO** — metadata órfã.
- **Dados críticos** nesses volumes: `ADMIN_DATAFORALL` (PLATFORMS, GATEWAY_MAPPING) e os DBs de
  tenant (`PLATFORM_DEV_30` etc. com PATs/twins).
- Um `docker compose down -v` no projeto errado zera tudo → foi o que apagou os PATs antes.

## Onde vivem os dados (mapa)

| Container | Host port | Conteúdo | Volume atual |
|---|---|---|---|
| `dataforall-admin-mysql` | 53306 | `ADMIN_DATAFORALL` (registro de tenants + GATEWAY_MAPPING) | `platform-service-template_mysql-admin-dev-data` |
| `dataforall-tenant-mysql` | 3306 | DBs por-tenant (`PLATFORM_DEV_30` = **PATs/twins**) — root com senha própria | `platform-service-template_mysql-local-data` |
| `dataforall-tenant-postgres` | — | governança/agentes | `dataforall-infra_tenant-postgres-data` (já correto) |

## Runbook (a stack está parada → bom momento)

Use as senhas root reais (admin normalmente `root`; tenant tem senha própria — `TENANT_MYSQL_PW`).

### 1. Backup ANTES (dois métodos, faça pelo menos um)
```bash
mkdir -p "$HOME/backups-mysql-migration" && cd "$_"
# a) tar dos volumes (não precisa de senha)
docker run --rm -v platform-service-template_mysql-admin-dev-data:/data alpine tar czf - -C /data . > admin-vol.tgz
docker run --rm -v platform-service-template_mysql-local-data:/data alpine tar czf - -C /data . > tenant-vol.tgz
# b) dump lógico (se os containers estiverem de pé) — usa dev_db_backup.py do scratchpad
```

### 2. Garantir containers parados
```bash
docker stop dataforall-admin-mysql dataforall-tenant-mysql 2>/dev/null; echo ok
```

### 3. Criar volumes nomeados de destino
```bash
docker volume create dataforall-infra_admin-mysql-data
docker volume create dataforall-infra_tenant-mysql-data
```

### 4. Copiar dados (preserva permissões)
```bash
docker run --rm -v platform-service-template_mysql-admin-dev-data:/from -v dataforall-infra_admin-mysql-data:/to alpine sh -c 'cp -a /from/. /to/'
docker run --rm -v platform-service-template_mysql-local-data:/from  -v dataforall-infra_tenant-mysql-data:/to  alpine sh -c 'cp -a /from/. /to/'
# validar
docker run --rm -v dataforall-infra_tenant-mysql-data:/data alpine ls /data | head
```

### 5. Diff no compose (2 linhas)
`platform-devs/deploy/docker-compose.infra.yml`, bloco `volumes:`:
```diff
 volumes:
-  admin-mysql-data:
-  tenant-mysql-data:
+  admin-mysql-data:
+    name: dataforall-infra_admin-mysql-data
+  tenant-mysql-data:
+    name: dataforall-infra_tenant-mysql-data
   tenant-postgres-data:
   ...
```
(As referências `admin-mysql-data:/var/lib/mysql` nos serviços continuam iguais.)

### 6. Subir pelo projeto correto + validar
```bash
cd C:/Users/caiog/Documents/repositorios/platform-devs
docker compose -f deploy/docker-compose.infra.yml up -d
# validar (senha real do tenant):
docker exec dataforall-tenant-mysql mysql -uroot -p"$TENANT_MYSQL_PW" -e "SHOW DATABASES LIKE 'PLATFORM%';"
docker exec dataforall-admin-mysql mysql -uroot -proot ADMIN_DATAFORALL -e "SELECT COUNT(*) FROM PLATFORMS;"
```

### 7. Só após validar 100%
Manter os volumes antigos como backup (recomendado) ou remover:
```bash
# docker volume rm platform-service-template_mysql-admin-dev-data platform-service-template_mysql-local-data
```

## Higiene: warnings de `down -v`
Adicionar aviso nos docs que usam `down -v` (ex.: `deploy/keycloak/README.md`,
`platform-service-template/docs/runbooks/local-stack-issues.md`): **nunca `down -v` no projeto
que hospeda os MySQL compartilhados**; use `stop`/`down` (sem `-v`), e limpe volumes só com backup.
