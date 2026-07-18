"""Exports das tools ativas do deploy-mcp.

GitHub Actions, scaffold de pipeline e deploy por workflow foram aposentados em
2026-07-15. O ledger mantém consultas históricas em modo read-only.
"""

from __future__ import annotations

from .acr_tool import acr_build, list_acr_images
from .git_tool import commit_files, create_branch, list_branches, list_repos
from .ledger_tool import (
    get_deployment,
    list_deploy_events,
    list_deployments,
    list_pr_history,
    list_registered_repos,
    list_workflow_history,
)
from .local_tool import clone_repo, get_repos_root, list_local_repos, set_repos_root
from .pr_tool import create_pr, get_pr, list_prs, merge_pr

__all__ = [
    "list_repos",
    "create_branch",
    "list_branches",
    "commit_files",
    "create_pr",
    "get_pr",
    "merge_pr",
    "list_prs",
    "acr_build",
    "list_acr_images",
    "get_repos_root",
    "set_repos_root",
    "list_local_repos",
    "clone_repo",
    "list_deployments",
    "get_deployment",
    "list_deploy_events",
    "list_pr_history",
    "list_workflow_history",
    "list_registered_repos",
]
