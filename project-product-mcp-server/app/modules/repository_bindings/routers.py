"""Authenticated provider-neutral repository-binding routes."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.core.context import ActorContext, public_actor_context
from app.core.dependencies import get_portfolio_repositories
from app.core.limiter import limiter
from app.core.repositories import PortfolioRepositories
from app.core.security import require_portfolio_access
from app.modules.repository_bindings.schemas import (
    DetachRequest,
    RepositoryBindingCreate,
    RepositoryBindingListResponse,
    RepositoryBindingResponse,
    RepositoryRole,
)
from app.modules.repository_bindings.services import RepositoryBindingService

router = APIRouter(prefix="/projects/{project_id}/repositories", tags=["Project repositories"])


def _service(repos: PortfolioRepositories, actor: ActorContext) -> RepositoryBindingService:
    return RepositoryBindingService(repos, actor)


@router.post(
    "",
    response_model=RepositoryBindingResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="attachProjectRepository",
    dependencies=[Depends(require_portfolio_access("write"))],
)
@limiter.limit("60/minute")
async def attach_repository(
    request: Request,
    project_id: UUID,
    body: RepositoryBindingCreate,
    repos: PortfolioRepositories = Depends(get_portfolio_repositories),
    actor: ActorContext = Depends(public_actor_context),
):
    return await _service(repos, actor).attach(project_id, body)


@router.get(
    "",
    response_model=RepositoryBindingListResponse,
    operation_id="listProjectRepositories",
    dependencies=[Depends(require_portfolio_access("read"))],
)
@limiter.limit("200/minute")
async def list_repositories(
    request: Request,
    project_id: UUID,
    provider: str | None = Query(default=None),
    role: RepositoryRole | None = Query(default=None),
    repos: PortfolioRepositories = Depends(get_portfolio_repositories),
    actor: ActorContext = Depends(public_actor_context),
):
    items = await _service(repos, actor).list(project_id, provider=provider, role=role)
    return RepositoryBindingListResponse(items=items)


@router.delete(
    "/{binding_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="detachProjectRepository",
    dependencies=[Depends(require_portfolio_access("delete"))],
)
@limiter.limit("30/minute")
async def detach_repository(
    request: Request,
    project_id: UUID,
    binding_id: UUID,
    body: DetachRequest,
    repos: PortfolioRepositories = Depends(get_portfolio_repositories),
    actor: ActorContext = Depends(public_actor_context),
):
    await _service(repos, actor).detach(
        project_id,
        binding_id,
        expected_version=body.expected_version,
        idempotency_key=body.idempotency_key,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
