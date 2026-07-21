"""Authenticated Project REST routes."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.core.context import ActorContext, public_actor_context
from app.core.dependencies import get_portfolio_repositories
from app.core.limiter import limiter
from app.core.repositories import PortfolioRepositories
from app.core.security import require_portfolio_access
from app.modules.projects.schemas import (
    DeleteRequest,
    ProjectCreate,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdate,
)
from app.modules.projects.services import ProjectService
from platform_project_product.schemas import ProjectStatus

router = APIRouter(prefix="/projects", tags=["Projects"])


def _service(repos: PortfolioRepositories, actor: ActorContext) -> ProjectService:
    return ProjectService(repos, actor)


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=201,
    operation_id="createProject",
    dependencies=[Depends(require_portfolio_access("write"))],
)
@limiter.limit("60/minute")
async def create_project(
    request: Request,
    body: ProjectCreate,
    repos: PortfolioRepositories = Depends(get_portfolio_repositories),
    actor: ActorContext = Depends(public_actor_context),
):
    return await _service(repos, actor).create(body)


@router.get(
    "/{project_id}",
    response_model=ProjectResponse,
    operation_id="getProject",
    dependencies=[Depends(require_portfolio_access("read"))],
)
@limiter.limit("200/minute")
async def get_project(
    request: Request,
    project_id: UUID,
    repos: PortfolioRepositories = Depends(get_portfolio_repositories),
    actor: ActorContext = Depends(public_actor_context),
):
    return await _service(repos, actor).get(project_id)


@router.get(
    "",
    response_model=ProjectListResponse,
    operation_id="listProjects",
    dependencies=[Depends(require_portfolio_access("read"))],
)
@limiter.limit("200/minute")
async def list_projects(
    request: Request,
    product_id: UUID | None = Query(default=None),
    status_filter: ProjectStatus | None = Query(default=None, alias="status"),
    after_id: UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    repos: PortfolioRepositories = Depends(get_portfolio_repositories),
    actor: ActorContext = Depends(public_actor_context),
):
    items, next_id = await _service(repos, actor).list(
        product_id=product_id, status=status_filter, after_id=after_id, limit=limit
    )
    return ProjectListResponse(items=items, next_after_id=next_id)


@router.patch(
    "/{project_id}",
    response_model=ProjectResponse,
    operation_id="updateProject",
    dependencies=[Depends(require_portfolio_access("write"))],
)
@limiter.limit("60/minute")
async def update_project(
    request: Request,
    project_id: UUID,
    body: ProjectUpdate,
    repos: PortfolioRepositories = Depends(get_portfolio_repositories),
    actor: ActorContext = Depends(public_actor_context),
):
    return await _service(repos, actor).update(project_id, body)


@router.delete(
    "/{project_id}",
    status_code=204,
    operation_id="deleteProject",
    dependencies=[Depends(require_portfolio_access("delete"))],
)
@limiter.limit("30/minute")
async def delete_project(
    request: Request,
    project_id: UUID,
    body: DeleteRequest,
    repos: PortfolioRepositories = Depends(get_portfolio_repositories),
    actor: ActorContext = Depends(public_actor_context),
):
    await _service(repos, actor).delete(
        project_id, expected_version=body.expected_version, idempotency_key=body.idempotency_key
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
