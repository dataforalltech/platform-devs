#!/usr/bin/env python3
"""
Valida saúde de todos os repositórios elegíveis para automação.

Verifica para cada repo (active=true AND allows_automation=true — ADR-002):
  1. Último CI workflow run (status: success / failing / no_runs / in_progress)
  2. Imagem Docker no ACR (d4all.azurecr.io/dataforall/3.0/<repo>)

Usage:
    python3 validate_repos_health.py               # relatório completo
    python3 validate_repos_health.py --ci-only     # só CI, sem ACR
    python3 validate_repos_health.py --failing     # só repos com problema
    python3 validate_repos_health.py --json        # output JSON para automação
    python3 validate_repos_health.py --fix         # dispara workflows para repos sem CI run
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime

import psycopg2

# ── Configuração ─────────────────────────────────────────────────────────────

ORG = "dataforalltech"
ACR_REGISTRY = os.getenv("DEPLOY_ACR_REGISTRY", "d4all.azurecr.io")
ACR_NAMESPACE = os.getenv("DEPLOY_ACR_NAMESPACE", "dataforall/3.0")
ACR_USERNAME = os.getenv("DEPLOY_ACR_USERNAME", "")
ACR_PASSWORD = os.getenv("DEPLOY_ACR_PASSWORD", "")

POSTGRES_CONFIG = {
    "host": os.getenv("POSTGRES_HOST", "claude-dev"),
    "port": int(os.getenv("POSTGRES_PORT", "5432")),
    "user": os.getenv("POSTGRES_USER", "postgres"),
    "password": os.getenv("POSTGRES_PASSWORD", "postgres_password_local_dev"),
    "database": os.getenv("POSTGRES_DB", "app"),
}

CI_WORKFLOW = "ci.yml"
CD_WORKFLOW = "cd-dev.yml"
REF = "develop"

# ── Helpers ──────────────────────────────────────────────────────────────────

def get_eligible_repos() -> list[dict]:
    """Retorna repos com active=true AND allows_automation=true (ADR-002)."""
    conn = psycopg2.connect(**POSTGRES_CONFIG)
    cur = conn.cursor()
    cur.execute("""
        SELECT name, repo_type, repo_scope
        FROM repositories
        WHERE active = true AND allows_automation = true
        ORDER BY repo_type, name
    """)
    repos = [{"name": r[0], "type": r[1], "scope": r[2]} for r in cur.fetchall()]
    conn.close()
    return repos


def gh_workflow_runs(repo: str, workflow: str, limit: int = 1) -> list[dict]:
    """Retorna últimos runs de um workflow via gh CLI."""
    try:
        result = subprocess.run(
            [
                "gh", "run", "list",
                "--repo", f"{ORG}/{repo}",
                "--workflow", workflow,
                "--limit", str(limit),
                "--json", "status,conclusion,createdAt,url,databaseId",
            ],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return []
        return json.loads(result.stdout or "[]")
    except Exception:
        return []


def gh_workflow_exists(repo: str, workflow: str) -> bool:
    """Verifica se o arquivo de workflow existe no repo."""
    try:
        result = subprocess.run(
            ["gh", "api", f"repos/{ORG}/{repo}/contents/.github/workflows/{workflow}"],
            capture_output=True, text=True, timeout=10,
        )
        return result.returncode == 0
    except Exception:
        return False


def acr_image_exists(repo: str) -> dict:
    """Verifica se existe imagem no ACR para o repo."""
    if not ACR_USERNAME or not ACR_PASSWORD:
        return {"status": "skipped", "reason": "ACR credentials not set (DEPLOY_ACR_USERNAME/PASSWORD)"}

    image = f"{ACR_NAMESPACE}/{repo}"
    url = f"https://{ACR_REGISTRY}/v2/{image}/tags/list"
    try:
        result = subprocess.run(
            ["curl", "-s", "-u", f"{ACR_USERNAME}:{ACR_PASSWORD}", url],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return {"status": "error", "reason": "curl failed"}
        data = json.loads(result.stdout)
        tags = data.get("tags") or []
        if tags:
            return {"status": "present", "tag_count": len(tags), "latest": tags[-1]}
        return {"status": "missing"}
    except Exception as exc:
        return {"status": "error", "reason": str(exc)}


def check_ci_status(repo: str) -> dict:
    """Verifica status do CI para um repo."""
    if not gh_workflow_exists(repo, CI_WORKFLOW):
        return {"status": "no_workflow", "conclusion": None, "url": None}

    runs = gh_workflow_runs(repo, CI_WORKFLOW, limit=1)
    if not runs:
        return {"status": "no_runs", "conclusion": None, "url": None}

    run = runs[0]
    status = run.get("status", "")
    conclusion = run.get("conclusion") or ""

    if status in ("in_progress", "queued", "waiting"):
        return {"status": "in_progress", "conclusion": None, "url": run.get("url"), "id": run.get("databaseId")}
    if conclusion == "success":
        return {"status": "success", "conclusion": "success", "url": run.get("url"), "created_at": run.get("createdAt")}
    return {"status": "failing", "conclusion": conclusion, "url": run.get("url"), "created_at": run.get("createdAt")}


def trigger_workflow(repo: str, workflow: str, ref: str = REF) -> bool:
    """Dispara um workflow via gh CLI."""
    try:
        result = subprocess.run(
            ["gh", "workflow", "run", workflow, "--repo", f"{ORG}/{repo}", "--ref", ref],
            capture_output=True, text=True, timeout=15,
        )
        return result.returncode == 0
    except Exception:
        return False


def scaffold_and_trigger(repo: str) -> str:
    """Scaffolda CI via deploy-mcp e dispara. Retorna 'ok' ou mensagem de erro."""
    # Tenta disparar via gh workflow run (workflow pode não existir ainda)
    ok = trigger_workflow(repo, CI_WORKFLOW, REF)
    return "triggered" if ok else "trigger_failed"


# ── Relatório ─────────────────────────────────────────────────────────────────

def classify(ci: dict, acr: dict) -> str:
    ci_ok = ci["status"] == "success"
    acr_ok = acr["status"] == "present"
    if ci_ok and acr_ok:
        return "HEALTHY"
    if not ci_ok and acr_ok:
        return "CI_FAILING"
    if ci_ok and not acr_ok:
        return "ACR_MISSING"
    return "CI_FAILING_AND_ACR_MISSING"


STATUS_ICON = {
    "HEALTHY": "✅",
    "CI_FAILING": "❌",
    "ACR_MISSING": "⚠️ ",
    "CI_FAILING_AND_ACR_MISSING": "🔴",
}

CI_ICON = {
    "success": "✅",
    "failing": "❌",
    "no_workflow": "🚫",
    "no_runs": "🕐",
    "in_progress": "🔄",
}

ACR_ICON = {
    "present": "✅",
    "missing": "❌",
    "skipped": "⏭️ ",
    "error": "⚠️ ",
}


def run(args) -> int:
    repos = get_eligible_repos()
    total = len(repos)

    print(f"\n{'='*90}")
    print(f"  🏥  Repository Health Check — {ORG}")
    print(f"  📅  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}   |   Repos elegíveis: {total}  (ADR-002)")
    print(f"{'='*90}\n")

    results = []

    for i, repo in enumerate(repos, 1):
        name = repo["name"]
        rtype = repo["type"]

        ci = check_ci_status(name)
        acr = acr_image_exists(name) if not args.ci_only else {"status": "skipped"}
        health = classify(ci, acr)

        results.append({
            "name": name,
            "type": rtype,
            "health": health,
            "ci": ci,
            "acr": acr,
        })

        if args.failing and health == "HEALTHY":
            continue

        ci_icon = CI_ICON.get(ci["status"], "?")
        acr_icon = ACR_ICON.get(acr["status"], "?")
        health_icon = STATUS_ICON.get(health, "?")

        ci_detail = ""
        if ci["status"] == "failing":
            ci_detail = f" ({ci.get('conclusion', '')})"
        elif ci["status"] == "success":
            ts = ci.get("created_at", "")[:10]
            ci_detail = f" ({ts})" if ts else ""

        acr_detail = ""
        if acr["status"] == "present":
            acr_detail = f" ({acr.get('latest', '')})"

        print(
            f"  {health_icon} {name:<45}  [{rtype:<8}]"
            f"  CI:{ci_icon}{ci_detail:<20}  ACR:{acr_icon}{acr_detail}"
        )

        # --fix: dispara CI para repos sem run ou sem workflow
        if args.fix and ci["status"] in ("no_runs", "no_workflow", "failing"):
            ok = trigger_workflow(name, CI_WORKFLOW, REF)
            status_str = "triggered ✅" if ok else "trigger failed ❌"
            print(f"       └─ Remediação CI: {status_str}")

    # ── Summary ──────────────────────────────────────────────────────────────
    healthy = sum(1 for r in results if r["health"] == "HEALTHY")
    ci_fail = sum(1 for r in results if r["ci"]["status"] not in ("success", "in_progress", "skipped"))
    acr_miss = sum(1 for r in results if r["acr"]["status"] == "missing")
    no_wf = sum(1 for r in results if r["ci"]["status"] == "no_workflow")
    in_prog = sum(1 for r in results if r["ci"]["status"] == "in_progress")

    print(f"\n{'─'*90}")
    print(f"  SUMMARY")
    print(f"{'─'*90}")
    print(f"  ✅  Healthy (CI ok + ACR ok):      {healthy:>3} / {total}")
    print(f"  ❌  CI failing/missing:             {ci_fail:>3}")
    print(f"  🚫  Sem workflow (ci.yml ausente):  {no_wf:>3}")
    print(f"  🔄  CI in progress:                 {in_prog:>3}")
    print(f"  ⚠️   ACR image ausente:              {acr_miss:>3}")
    print(f"{'─'*90}\n")

    # Listar repos que precisam de atenção
    problems = [r for r in results if r["health"] != "HEALTHY"]
    if problems:
        print(f"  🔧  REPOS QUE PRECISAM DE ATENÇÃO ({len(problems)}):")
        for r in problems:
            ci_s = r["ci"]["status"]
            acr_s = r["acr"]["status"]
            url = r["ci"].get("url", "")
            print(f"     • {r['name']:<45}  CI:{ci_s}  ACR:{acr_s}")
            if url:
                print(f"       └─ {url}")
        print()

    if args.json:
        output = {
            "timestamp": datetime.now().isoformat(),
            "org": ORG,
            "filter": "active=true AND allows_automation=true",
            "summary": {
                "total": total,
                "healthy": healthy,
                "ci_failing": ci_fail,
                "no_workflow": no_wf,
                "in_progress": in_prog,
                "acr_missing": acr_miss,
            },
            "repos": results,
        }
        print(json.dumps(output, indent=2, default=str))

    # Exit code não-zero se há problemas (útil em CI/CD)
    return 0 if healthy == total else 1


def main():
    parser = argparse.ArgumentParser(description="Valida saúde de CI e ACR dos repos elegíveis")
    parser.add_argument("--ci-only", action="store_true", help="Verificar apenas CI (sem ACR)")
    parser.add_argument("--failing", action="store_true", help="Mostrar apenas repos com problema")
    parser.add_argument("--json", action="store_true", help="Output JSON para automação")
    parser.add_argument("--fix", action="store_true", help="Disparar CI para repos sem run")
    args = parser.parse_args()
    sys.exit(run(args))


if __name__ == "__main__":
    main()
