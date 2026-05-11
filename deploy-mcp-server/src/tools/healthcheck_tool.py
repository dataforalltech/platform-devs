"""Skill: ensure_all_repos_healthy

Verifica e garante que todos os repositórios elegíveis para automação
(active=true AND allows_automation=true) tenham:

  1. CI workflow passando (último run = success)
  2. Imagem Docker publicada no ACR

Para repos com problemas, executa remediação automática:
  - CI falhando / ausente → scaffold ci+cd-dev → trigger ci.yml
  - ACR ausente → setup_repo (injeta secrets) → trigger cd-dev.yml

Filtro de repos: obrigatoriamente via AUTOMATION_FILTER_SQL (ADR-002).
"""

from __future__ import annotations

import time
from typing import Any

from ..config.settings import DeploySettings
from ..knowledge.github_client import GitHubClient, GitHubClientError
from .acr_tool import list_acr_images, setup_repo
from .pipeline_tool import scaffold_pipeline
from .workflow_tool import list_workflow_runs, trigger_workflow

# Statuses que indicam CI passou
_CI_SUCCESS = {"success"}
# Statuses que indicam CI ainda está rodando
_CI_IN_PROGRESS = {"queued", "in_progress", "waiting"}


def _ci_status(client: GitHubClient, repo: str, workflow_id: str, ref: str) -> dict[str, Any]:
    """Retorna status do último run do CI para o repo.

    Returns dict com:
      status: "success" | "failing" | "no_runs" | "no_workflow" | "in_progress"
      run_id, conclusion, html_url (quando disponível)
    """
    try:
        runs = client.list_workflow_runs(repo, workflow_id=workflow_id, branch=ref, limit=1)
    except GitHubClientError:
        return {"status": "no_workflow"}

    if not runs:
        # Workflow existe mas nunca rodou na branch
        runs_any = client.list_workflow_runs(repo, workflow_id=workflow_id, limit=1)
        if not runs_any:
            return {"status": "no_runs"}
        run = runs_any[0]
    else:
        run = runs[0]

    conclusion = run.get("conclusion") or ""
    run_status = run.get("status") or ""

    if run_status in _CI_IN_PROGRESS:
        return {"status": "in_progress", "run_id": run.get("id"), "url": run.get("html_url")}
    if conclusion in _CI_SUCCESS:
        return {"status": "success", "run_id": run.get("id"), "url": run.get("html_url")}
    return {
        "status": "failing",
        "conclusion": conclusion,
        "run_id": run.get("id"),
        "url": run.get("html_url"),
    }


def _acr_status(
    client: GitHubClient, settings: DeploySettings, repo_name: str
) -> dict[str, Any]:
    """Verifica se existe imagem no ACR para o repo."""
    result = list_acr_images(client, settings, service_name=repo_name, limit=1)
    if "error" in result:
        return {"status": "error", "detail": result.get("details", result["error"])}
    tags = result.get("tags", [])
    if tags:
        return {"status": "present", "latest_tag": tags[0].get("name", tags[0])}
    return {"status": "missing"}


def _wait_for_ci(
    client: GitHubClient,
    repo: str,
    workflow_id: str,
    ref: str,
    wait_seconds: int,
    poll_interval: int = 30,
) -> str:
    """Polling do CI até completar ou timeout. Retorna 'success', 'failing' ou 'timeout'."""
    deadline = time.time() + wait_seconds
    # Pequena espera inicial para o run aparecer na API após dispatch
    time.sleep(10)
    while time.time() < deadline:
        result = _ci_status(client, repo, workflow_id, ref)
        s = result["status"]
        if s == "success":
            return "success"
        if s == "failing":
            return "failing"
        # in_progress / no_runs → continua polling
        time.sleep(poll_interval)
    return "timeout"


def ensure_all_repos_healthy(
    client: GitHubClient,
    settings: DeploySettings,
    org: str = "dataforalltech",
    workflow_id: str = "ci.yml",
    cd_workflow_id: str = "cd-dev.yml",
    ref: str = "develop",
    wait_minutes: int = 10,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Verifica e garante que todos os repos elegíveis tenham CI passando e imagem no ACR.

    Filtro obrigatório (ADR-002): active=true AND allows_automation=true.

    Fluxo por repo:
      1. Verifica status do último CI run (workflow_id em ref)
      2. Verifica presença de imagem no ACR
      3. Classifica: HEALTHY | CI_FAILING | ACR_MISSING | CI_FAILING_AND_ACR_MISSING
      4. Se dry_run=False: remedia falhas automaticamente

    Remediação CI:
      - Se workflow ausente: scaffold_pipeline(ci, cd-dev) → trigger ci.yml
      - Se CI falhando: trigger ci.yml → polling wait_minutes

    Remediação ACR:
      - setup_repo (injeta ACR_USERNAME, ACR_PASSWORD, IMAGE_NAME) → trigger cd-dev.yml
      - CD não é aguardado (pode demorar) — marcado como ACR_TRIGGERED

    Args:
        org: Organização GitHub. Default: dataforalltech.
        workflow_id: Arquivo do workflow CI. Default: ci.yml.
        cd_workflow_id: Arquivo do workflow CD. Default: cd-dev.yml.
        ref: Branch para verificar e disparar workflows. Default: develop.
        wait_minutes: Tempo máximo aguardando CI após remediação. Default: 10.
        dry_run: Se True, apenas reporta sem executar remediações. Default: False.
    """
    repos_raw = client.list_repos(org=org, include_archived=False)
    repo_names = [r["name"] for r in repos_raw]

    wait_seconds = wait_minutes * 60
    actions_taken: list[dict] = []

    repos_report: list[dict] = []

    # ── Fase 1+2: inventário ────────────────────────────────────────────────── #
    for name in repo_names:
        ci = _ci_status(client, name, workflow_id, ref)
        acr = _acr_status(client, settings, name)

        ci_ok = ci["status"] == "success"
        acr_ok = acr["status"] == "present"

        if ci_ok and acr_ok:
            health = "HEALTHY"
        elif not ci_ok and not acr_ok:
            health = "CI_FAILING_AND_ACR_MISSING"
        elif not ci_ok:
            health = "CI_FAILING"
        else:
            health = "ACR_MISSING"

        repos_report.append({
            "name": name,
            "ci_status": ci["status"],
            "ci_conclusion": ci.get("conclusion"),
            "ci_run_url": ci.get("url"),
            "acr_status": acr["status"],
            "acr_latest_tag": acr.get("latest_tag"),
            "health": health,
            "remediation": None,
        })

    # ── Fase 3: remediação ──────────────────────────────────────────────────── #
    if not dry_run:
        for repo in repos_report:
            if repo["health"] == "HEALTHY":
                continue

            name = repo["name"]
            needs_ci = repo["health"] in ("CI_FAILING", "CI_FAILING_AND_ACR_MISSING")
            needs_acr = repo["health"] in ("ACR_MISSING", "CI_FAILING_AND_ACR_MISSING")

            # ── remediar CI ─────────────────────────────────────────────────── #
            if needs_ci:
                # Se workflow não existe: scaffoldar
                if repo["ci_status"] in ("no_workflow", "no_runs"):
                    scaffold_result = scaffold_pipeline(
                        client, name, templates=["ci", "cd-dev"], branch=ref
                    )
                    actions_taken.append({
                        "repo": name,
                        "action": "scaffold_pipeline",
                        "templates": ["ci", "cd-dev"],
                        "result": "ok" if scaffold_result.get("committed") else scaffold_result.get("error", "error"),
                    })
                    time.sleep(5)  # aguarda propagação do commit

                # Disparar CI
                trigger_result = trigger_workflow(client, name, workflow_id, ref)
                actions_taken.append({
                    "repo": name,
                    "action": "trigger_ci",
                    "workflow": workflow_id,
                    "ref": ref,
                    "result": "dispatched" if not trigger_result.get("error") else trigger_result.get("error"),
                })

                # Aguardar resultado
                final_status = _wait_for_ci(client, name, workflow_id, ref, wait_seconds)
                repo["ci_status"] = final_status
                repo["remediation"] = f"ci_{final_status}"

                if final_status == "success":
                    actions_taken.append({"repo": name, "action": "ci_result", "result": "success"})
                    # Se ACR era o único problema, o CD vai rodar via workflow_run trigger
                    # do ci.yml — não precisamos disparar manualmente
                    if repo["health"] == "CI_FAILING_AND_ACR_MISSING":
                        repo["acr_status"] = "triggered_via_ci"
                        needs_acr = False
                else:
                    actions_taken.append({
                        "repo": name,
                        "action": "ci_result",
                        "result": final_status,
                        "note": "Remediation failed — check workflow logs",
                    })
                    needs_acr = False  # não tenta ACR se CI ainda está falhando

            # ── remediar ACR ────────────────────────────────────────────────── #
            if needs_acr:
                setup_result = setup_repo(client, settings, name, image_name=name)
                actions_taken.append({
                    "repo": name,
                    "action": "setup_repo",
                    "result": "ok" if setup_result.get("success") else setup_result.get("errors"),
                })

                cd_result = trigger_workflow(client, name, cd_workflow_id, ref)
                actions_taken.append({
                    "repo": name,
                    "action": "trigger_cd",
                    "workflow": cd_workflow_id,
                    "ref": ref,
                    "result": "dispatched" if not cd_result.get("error") else cd_result.get("error"),
                })
                repo["acr_status"] = "triggered"
                repo["remediation"] = (repo["remediation"] or "") + "_acr_triggered"

    # ── Fase 4: summary ─────────────────────────────────────────────────────── #
    healthy = sum(1 for r in repos_report if r["health"] == "HEALTHY" or r.get("remediation") == "ci_success")
    ci_failing = sum(1 for r in repos_report if r["ci_status"] in ("failing", "no_workflow", "no_runs", "timeout"))
    acr_missing = sum(1 for r in repos_report if r["acr_status"] in ("missing", "error"))
    remediated = sum(1 for r in repos_report if r.get("remediation") and "success" in (r.get("remediation") or ""))
    remediation_failed = sum(1 for r in repos_report if r.get("remediation") and "timeout" in (r.get("remediation") or ""))

    return {
        "summary": {
            "total": len(repos_report),
            "healthy": healthy,
            "ci_failing": ci_failing,
            "acr_missing": acr_missing,
            "remediated": remediated,
            "remediation_failed": remediation_failed,
        },
        "repos": repos_report,
        "actions_taken": actions_taken,
        "dry_run": dry_run,
        "filter": "active=true AND allows_automation=true (ADR-002)",
        "org": org,
        "workflow_id": workflow_id,
        "ref": ref,
    }
