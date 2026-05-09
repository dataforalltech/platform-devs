"""deploy-mcp-server — exportações de todas as 19 tools."""

from __future__ import annotations

from .acr_tool import acr_build, list_acr_images, setup_repo
from .deploy_tool import deploy, get_deploy_status
from .git_tool import commit_files, create_branch, list_branches, list_repos
from .pipeline_tool import get_pipeline_templates, scaffold_pipeline
from .pr_tool import create_pr, get_pr, list_prs, merge_pr
from .workflow_tool import (
    cancel_workflow_run,
    get_workflow_run,
    list_workflow_runs,
    trigger_workflow,
)

__all__ = [
    # git
    "list_repos",
    "create_branch",
    "list_branches",
    "commit_files",
    # pr
    "create_pr",
    "get_pr",
    "merge_pr",
    "list_prs",
    # workflow
    "trigger_workflow",
    "list_workflow_runs",
    "get_workflow_run",
    "cancel_workflow_run",
    # deploy
    "deploy",
    "get_deploy_status",
    # pipeline
    "scaffold_pipeline",
    "get_pipeline_templates",
    # acr
    "setup_repo",
    "acr_build",
    "list_acr_images",
]
