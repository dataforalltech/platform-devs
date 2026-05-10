"""
Deploy-MCP HTTP Endpoints — GitHub + ACR Integration.

Endpoints para gerenciar repositórios, workflows e imagens Docker.
"""

from typing import Dict, Any, Optional, List
import logging
from datetime import datetime

logger = logging.getLogger(__name__)


class DeployHTTPEndpoints:
    """HTTP endpoints para deploy-mcp com sync PostgreSQL."""

    def __init__(self, postgres_sync):
        """
        Initialize endpoints.

        Args:
            postgres_sync: DeployPostgresSync instance
        """
        self.postgres_sync = postgres_sync

    # ========== GET /repositories ==========

    def get_repositories(self, organization: Optional[str] = None,
                         status: Optional[str] = None) -> Dict[str, Any]:
        """
        GET /repositories

        Lista repositórios registrados com filtros opcionais.

        Query params:
            - organization: Filter by GitHub organization
            - status: active, archived, deprecated

        Response (200):
            {
                "repositories": [
                    {
                        "id": 1,
                        "name": "platform-service-template",
                        "owner": "dataforalltech",
                        "url": "https://github.com/dataforalltech/platform-service-template",
                        "status": "active",
                        "base_branch": "develop",
                        "main_branch": "main",
                        "last_commit_at": "2026-05-10T10:30:45Z",
                        "created_at": "2026-05-01T...",
                        "updated_at": "2026-05-10T..."
                    }
                ],
                "total": 18
            }
        """
        try:
            repositories = self.postgres_sync.list_repositories(
                organization=organization,
                status=status
            )

            if repositories is None:
                return {
                    'status': 500,
                    'error': 'database_error'
                }

            return {
                'status': 200,
                'repositories': [dict(r) for r in repositories],
                'total': len(repositories)
            }

        except Exception as e:
            logger.error(f"Error in GET /repositories: {e}")
            return {
                'status': 500,
                'error': 'internal_error'
            }

    # ========== GET /repositories/:name ==========

    def get_repository(self, name: str) -> Dict[str, Any]:
        """
        GET /repositories/{name}

        Retorna detalhes de um repositório.

        Response (200):
            {
                "id": 1,
                "name": "platform-service-template",
                "owner": "dataforalltech",
                "url": "https://github.com/dataforalltech/platform-service-template",
                "description": "Template para novos serviços",
                "status": "active",
                "base_branch": "develop",
                "main_branch": "main",
                "default_branch": "develop",
                "language": "python",
                "topics": ["platform", "template"],
                "last_commit_at": "2026-05-10T10:30:45Z",
                "last_commit_sha": "a1b2c3d4",
                "last_commit_message": "docs: Update README",
                "created_at": "2026-05-01T...",
                "updated_at": "2026-05-10T..."
            }

        Response (404):
            {
                "error": "repository_not_found"
            }
        """
        try:
            repository = self.postgres_sync.get_repository(name)

            if repository is None:
                return {
                    'status': 404,
                    'error': 'repository_not_found'
                }

            return {
                'status': 200,
                **repository  # Spread repository dict
            }

        except Exception as e:
            logger.error(f"Error in GET /repositories/{name}: {e}")
            return {
                'status': 500,
                'error': 'internal_error'
            }

    # ========== POST /repositories ==========

    def post_repositories(self, name: str, owner: str, url: str,
                         **kwargs) -> Dict[str, Any]:
        """
        POST /repositories

        Registra novo repositório.

        Request:
            {
                "name": "platform-ml",
                "owner": "dataforalltech",
                "url": "https://github.com/dataforalltech/platform-ml",
                "description": "Machine Learning service",
                "base_branch": "develop",
                "main_branch": "main",
                "language": "python"
            }

        Response (201):
            {
                "id": 19,
                "name": "platform-ml",
                "status": "active",
                "created_at": "2026-05-10T10:30:45Z"
            }

        Response (409):
            {
                "error": "repository_already_exists"
            }
        """
        try:
            # Step 1: Check if already exists
            existing = self.postgres_sync.get_repository(name)
            if existing:
                return {
                    'status': 409,
                    'error': 'repository_already_exists'
                }

            # Step 2: Register in PostgreSQL
            repo_data = {
                'name': name,
                'owner': owner,
                'url': url,
                'description': kwargs.get('description'),
                'base_branch': kwargs.get('base_branch', 'develop'),
                'main_branch': kwargs.get('main_branch', 'main'),
                'language': kwargs.get('language'),
                'topics': kwargs.get('topics', []),
            }

            self.postgres_sync.sync_repository_registered(repo_data)

            # Step 3: Log audit trail
            self.postgres_sync.log_action(
                action='register',
                repository_name=name,
                details=repo_data
            )

            logger.info(f"✅ Repository registered: {name}")

            return {
                'status': 201,
                'id': None,  # Would be returned from PostgreSQL insert
                'name': name,
                'status': 'active',
                'created_at': datetime.utcnow().isoformat() + 'Z'
            }

        except Exception as e:
            logger.error(f"Error in POST /repositories: {e}")
            return {
                'status': 500,
                'error': 'internal_error'
            }

    # ========== GET /repositories/:name/branches ==========

    def get_repository_branches(self, name: str) -> Dict[str, Any]:
        """
        GET /repositories/{name}/branches

        Lista branches do repositório.

        Response (200):
            {
                "repository": "platform-service-template",
                "branches": [
                    {
                        "name": "develop",
                        "protected": true,
                        "last_commit_sha": "a1b2c3d4",
                        "last_commit_at": "2026-05-10T10:30:45Z"
                    },
                    {
                        "name": "main",
                        "protected": true,
                        "last_commit_sha": "e5f6g7h8",
                        "last_commit_at": "2026-05-09T15:20:30Z"
                    }
                ],
                "total": 2
            }
        """
        try:
            branches = self.postgres_sync.list_branches(name)

            if branches is None:
                return {
                    'status': 404,
                    'error': 'repository_not_found'
                }

            return {
                'status': 200,
                'repository': name,
                'branches': [dict(b) for b in branches],
                'total': len(branches)
            }

        except Exception as e:
            logger.error(f"Error in GET /repositories/{name}/branches: {e}")
            return {
                'status': 500,
                'error': 'internal_error'
            }

    # ========== GET /repositories/:name/workflows ==========

    def get_repository_workflows(self, name: str) -> Dict[str, Any]:
        """
        GET /repositories/{name}/workflows

        Lista workflows (CI/CD) do repositório.

        Response (200):
            {
                "repository": "platform-service-template",
                "workflows": [
                    {
                        "id": "ci.yml",
                        "name": "CI",
                        "state": "active",
                        "created_at": "2026-05-01T..."
                    },
                    {
                        "id": "deploy.yml",
                        "name": "Deploy",
                        "state": "active",
                        "created_at": "2026-05-01T..."
                    }
                ],
                "total": 2
            }
        """
        try:
            workflows = self.postgres_sync.list_workflows(name)

            if workflows is None:
                return {
                    'status': 404,
                    'error': 'repository_not_found'
                }

            return {
                'status': 200,
                'repository': name,
                'workflows': [dict(w) for w in workflows],
                'total': len(workflows)
            }

        except Exception as e:
            logger.error(f"Error in GET /repositories/{name}/workflows: {e}")
            return {
                'status': 500,
                'error': 'internal_error'
            }

    # ========== GET /repositories/:name/acr-images ==========

    def get_repository_acr_images(self, name: str, limit: int = 20) -> Dict[str, Any]:
        """
        GET /repositories/{name}/acr-images

        Lista imagens Docker publicadas no ACR.

        Query params:
            - limit: Maximum images to return (default: 20)

        Response (200):
            {
                "repository": "platform-service-template",
                "images": [
                    {
                        "name": "platform-service-template",
                        "latest_tag": "v3.20260510-a1b2c3d4",
                        "tags": ["v3.20260510-a1b2c3d4", "latest"],
                        "pushed_at": "2026-05-10T10:30:45Z"
                    }
                ],
                "total": 1
            }
        """
        try:
            images = self.postgres_sync.list_acr_images(name, limit=limit)

            if images is None:
                return {
                    'status': 404,
                    'error': 'repository_not_found'
                }

            return {
                'status': 200,
                'repository': name,
                'images': [dict(img) for img in images],
                'total': len(images)
            }

        except Exception as e:
            logger.error(f"Error in GET /repositories/{name}/acr-images: {e}")
            return {
                'status': 500,
                'error': 'internal_error'
            }

    # ========== POST /repositories/:name/workflow-run ==========

    def post_repository_workflow_run(self, name: str, workflow_id: str,
                                      ref: str, **inputs) -> Dict[str, Any]:
        """
        POST /repositories/{name}/workflow-run

        Dispara execução de workflow (CI/CD).

        Request:
            {
                "workflow_id": "deploy.yml",
                "ref": "develop",
                "inputs": {
                    "environment": "dev",
                    "version": "1.0.0"
                }
            }

        Response (202):
            {
                "triggered": true,
                "workflow_id": "deploy.yml",
                "run_id": 123456,
                "branch": "develop",
                "triggered_at": "2026-05-10T10:30:45Z"
            }

        Security:
            - ✅ Logs all workflow triggers in audit_log
            - ✅ Records run_id for tracking
        """
        try:
            repository = self.postgres_sync.get_repository(name)
            if repository is None:
                return {
                    'status': 404,
                    'error': 'repository_not_found'
                }

            # Step 1: Trigger workflow (GitHub)
            run_id = self._trigger_workflow(name, workflow_id, ref, inputs)

            # Step 2: Log in PostgreSQL
            self.postgres_sync.sync_workflow_triggered(
                repository_name=name,
                workflow_id=workflow_id,
                run_id=run_id,
                branch=ref,
                inputs=inputs
            )

            # Step 3: Audit trail
            self.postgres_sync.log_action(
                action='workflow_triggered',
                repository_name=name,
                details={
                    'workflow_id': workflow_id,
                    'run_id': run_id,
                    'branch': ref,
                    'inputs': inputs
                }
            )

            logger.info(f"✅ Workflow triggered: {name}#{workflow_id} (run #{run_id})")

            return {
                'status': 202,
                'triggered': True,
                'workflow_id': workflow_id,
                'run_id': run_id,
                'branch': ref,
                'triggered_at': datetime.utcnow().isoformat() + 'Z'
            }

        except Exception as e:
            logger.error(f"Error in POST /repositories/{name}/workflow-run: {e}")
            return {
                'status': 500,
                'error': 'internal_error'
            }

    # ========== GET /repositories/:name/pull-requests ==========

    def get_repository_pull_requests(self, name: str, state: str = "open") -> Dict[str, Any]:
        """
        GET /repositories/{name}/pull-requests

        Lista Pull Requests do repositório.

        Query params:
            - state: open, closed, all (default: open)

        Response (200):
            {
                "repository": "platform-service-template",
                "pull_requests": [
                    {
                        "number": 123,
                        "title": "feat: Add PostgreSQL integration",
                        "state": "open",
                        "branch": "feature/postgres-integration",
                        "author": "caiog",
                        "created_at": "2026-05-08T...",
                        "updated_at": "2026-05-10T..."
                    }
                ],
                "total": 1
            }
        """
        try:
            prs = self.postgres_sync.list_pull_requests(name, state=state)

            if prs is None:
                return {
                    'status': 404,
                    'error': 'repository_not_found'
                }

            return {
                'status': 200,
                'repository': name,
                'pull_requests': [dict(pr) for pr in prs],
                'total': len(prs)
            }

        except Exception as e:
            logger.error(f"Error in GET /repositories/{name}/pull-requests: {e}")
            return {
                'status': 500,
                'error': 'internal_error'
            }

    # ========== Private Helpers ==========

    def _trigger_workflow(self, repo: str, workflow_id: str, ref: str,
                         inputs: Dict[str, str]) -> int:
        """Trigger GitHub workflow and return run_id."""
        # TODO: Implement actual GitHub workflow trigger
        # Returns mock run_id for now
        return 123456
