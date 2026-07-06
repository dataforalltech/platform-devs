"""Backup/restore lógico dos MySQL de dev da plataforma (PATs, twins, tenants, admin).

Protege contra o wipe que zera PATs/twins/agentes (um `docker compose down -v` no
projeto errado — ver docs/runbooks/mysql-volume-migration.md). Dump de TODOS os
schemas de usuário dos dois MySQL:

  - dataforall-admin-mysql   -> ADMIN_DATAFORALL (PLATFORMS, GATEWAY_MAPPING, config)
  - dataforall-tenant-mysql  -> DBs por-tenant (PLATFORM_DEV_30 etc.) — PATs/twins vivem AQUI

NOTA: agentes vivem no DB do platform-governance (Postgres, à parte) — este script
NÃO cobre isso; use o dump nativo do governance se precisar.

Senhas root via env que VOCÊ fornece (sem harvesting): o admin-mysql costuma ser
`root`; o tenant-mysql tem senha PRÓPRIA — passe em TENANT_MYSQL_PW.

Uso:
  TENANT_MYSQL_PW=<senha> python dev_db_backup.py backup   # backups/<timestamp>/{admin,tenant}.sql
  python dev_db_backup.py restore <dir>                    # restaura ambos a partir de <dir>
  python dev_db_backup.py list-dbs                         # lista os schemas de cada instância
"""
from __future__ import annotations

import datetime
import os
import subprocess
import sys
from pathlib import Path

INSTANCES = {
    "admin": "dataforall-admin-mysql",   # ADMIN_DATAFORALL (registro de tenants, GATEWAY_MAPPING)
    "tenant": "dataforall-tenant-mysql",  # DBs por-tenant (PLATFORM_DEV_30 etc.) — PATs/twins vivem AQUI
}
_SYSTEM_DBS = {"information_schema", "mysql", "performance_schema", "sys"}
BACKUP_ROOT = Path(__file__).resolve().parent / "backups"

# Senha root por instância, via env que VOCÊ fornece (sem harvesting). O admin-mysql
# costuma ser "root"; o tenant-mysql tem senha própria — passe em TENANT_MYSQL_PW.
_PW_BY_LABEL = {
    "admin": os.getenv("ADMIN_MYSQL_PW", "root"),
    "tenant": os.getenv("TENANT_MYSQL_PW", "root"),
}


def _root_pw(container: str) -> str:
    label = next((lbl for lbl, c in INSTANCES.items() if c == container), "")
    return _PW_BY_LABEL.get(label, "root")


def _mysql(container: str, sql: str) -> str:
    r = subprocess.run(
        ["docker", "exec", container, "mysql", "-uroot", f"-p{_root_pw(container)}",
         "-N", "-B", "-e", sql],
        capture_output=True, text=True, timeout=60,
    )
    return "\n".join(l for l in r.stdout.splitlines() if l.strip() and "Warning" not in l)


def _user_dbs(container: str) -> list[str]:
    out = _mysql(container, "SHOW DATABASES;")
    return [d for d in out.splitlines() if d.strip() and d.strip() not in _SYSTEM_DBS]


def _container_up(container: str) -> bool:
    r = subprocess.run(["docker", "ps", "--filter", f"name={container}", "--format", "{{.Names}}"],
                       capture_output=True, text=True, timeout=30)
    return container in r.stdout


def cmd_list_dbs() -> int:
    for label, container in INSTANCES.items():
        if not _container_up(container):
            print(f"[{label}] {container}: NÃO está de pé"); continue
        dbs = _user_dbs(container)
        print(f"[{label}] {container}: {dbs}")
    return 0


def cmd_backup() -> int:
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = BACKUP_ROOT / stamp
    dest.mkdir(parents=True, exist_ok=True)
    manifest = [f"# dev DB backup {stamp}", ""]
    for label, container in INSTANCES.items():
        if not _container_up(container):
            print(f"[{label}] {container} fora — pulando"); manifest.append(f"{label}: SKIPPED (down)"); continue
        dbs = _user_dbs(container)
        if not dbs:
            print(f"[{label}] sem schemas de usuário (senha errada? passe {label.upper()}_MYSQL_PW) — pulando")
            continue
        out_file = dest / f"{label}.sql"
        with out_file.open("wb") as fh:
            p = subprocess.run(
                ["docker", "exec", container, "mysqldump", "-uroot", f"-p{_root_pw(container)}",
                 "--single-transaction", "--databases", *dbs],
                stdout=fh, stderr=subprocess.PIPE, timeout=300,
            )
        if p.returncode != 0:
            print(f"[{label}] FALHOU: {p.stderr.decode(errors='replace')[:200]}"); return 3
        size = out_file.stat().st_size
        print(f"[{label}] {container}: dump de {dbs} -> {out_file.name} ({size} bytes)")
        manifest.append(f"{label}: {container} -> {out_file.name} :: {dbs}")
    (dest / "MANIFEST.txt").write_text("\n".join(manifest), encoding="utf-8")
    print(f"\nOK -> {dest}")
    print(f"restaurar com: python {Path(__file__).name} restore \"{dest}\"")
    return 0


def cmd_restore(dir_arg: str) -> int:
    src = Path(dir_arg)
    if not src.is_dir():
        print(f"FAIL: {src} não é um diretório"); return 2
    for label, container in INSTANCES.items():
        sql = src / f"{label}.sql"
        if not sql.exists():
            print(f"[{label}] sem {sql.name} — pulando"); continue
        if not _container_up(container):
            print(f"[{label}] {container} fora — não dá pra restaurar"); return 3
        with sql.open("rb") as fh:
            p = subprocess.run(
                ["docker", "exec", "-i", container, "mysql", "-uroot", f"-p{_root_pw(container)}"],
                stdin=fh, capture_output=True, timeout=300,
            )
        if p.returncode != 0:
            print(f"[{label}] FALHOU: {p.stderr.decode(errors='replace')[:200]}"); return 3
        print(f"[{label}] {container}: restaurado de {sql.name}")
    print("OK — restauração concluída.")
    return 0


def main(argv: list[str]) -> int:
    cmd = argv[1] if len(argv) > 1 else "backup"
    if cmd == "backup":
        return cmd_backup()
    if cmd == "restore":
        if len(argv) < 3:
            print("uso: python dev_db_backup.py restore <dir>"); return 2
        return cmd_restore(argv[2])
    if cmd == "list-dbs":
        return cmd_list_dbs()
    print(__doc__); return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
