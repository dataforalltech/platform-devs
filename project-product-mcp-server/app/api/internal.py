"""Private MCP adapter reachable only from the sidecar network."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Query, status

from app.core.context import ActorContext, internal_actor_context
from app.core.dependencies import get_portfolio_repositories
from app.core.repositories import PortfolioRepositories
from app.core.security import require_internal_token
from app.modules.products.schemas import DeleteRequest as ProductDeleteRequest
from app.modules.products.schemas import (
    ProductCreate,
    ProductListResponse,
    ProductResponse,
    ProductUpdate,
)
from app.modules.products.services import ProductService
from app.modules.projects.schemas import DeleteRequest as ProjectDeleteRequest
from app.modules.projects.schemas import (
    ProjectCreate,
    ProjectListResponse,
    ProjectResponse,
    ProjectUpdate,
)
from app.modules.projects.services import ProjectService
from app.modules.repository_bindings.schemas import (
    DetachRequest,
    RepositoryBindingCreate,
    RepositoryBindingListResponse,
    RepositoryBindingResponse,
    RepositoryRole,
)
from app.modules.repository_bindings.services import RepositoryBindingService
from platform_project_product.schemas import ProductStatus, ProjectStatus

router = APIRouter(
    prefix="/internal/mcp",
    tags=["MCP private adapter"],
    dependencies=[Depends(require_internal_token)],
    include_in_schema=False,
)


def _products(repos: PortfolioRepositories, actor: ActorContext) -> ProductService:
    return ProductService(repos, actor)


def _projects(repos: PortfolioRepositories, actor: ActorContext) -> ProjectService:
    return ProjectService(repos, actor)


def _bindings(repos: PortfolioRepositories, actor: ActorContext) -> RepositoryBindingService:
    return RepositoryBindingService(repos, actor)


@router.post("/products", response_model=ProductResponse, status_code=status.HTTP_201_CREATED)
async def create_product(
    body: ProductCreate,
    repos: PortfolioRepositories = Depends(get_portfolio_repositories),
    actor: ActorContext = Depends(internal_actor_context),
):
    return await _products(repos, actor).create(body)


@router.get("/products/{product_id}", response_model=ProductResponse)
async def get_product(
    product_id: UUID,
    repos: PortfolioRepositories = Depends(get_portfolio_repositories),
    actor: ActorContext = Depends(internal_actor_context),
):
    return await _products(repos, actor).get(product_id)


@router.get("/products", response_model=ProductListResponse)
async def list_products(
    status_filter: ProductStatus | None = Query(default=None, alias="status"),
    after_id: UUID | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    repos: PortfolioRepositories = Depends(get_portfolio_repositories),
    actor: ActorContext = Depends(internal_actor_context),
):
    items, next_id = await _products(repos, actor).list(
        status=status_filter, after_id=after_id, limit=limit
    )
    return ProductListResponse(items=items, next_after_id=next_id)


@router.patch("/products/{product_id}", response_model=ProductResponse)
async def update_product(
    product_id: UUID,
    body: ProductUpdate,
    repos: PortfolioRepositories = Depends(get_portfolio_repositories),
    actor: ActorContext = Depends(internal_actor_context),
):
    return await _products(repos, actor).update(product_id, body)


@router.delete("/products/{product_id}")
async def delete_product(
    product_id: UUID,
    body: ProductDeleteRequest,
    repos: PortfolioRepositories = Depends(get_portfolio_repositories),
    actor: ActorContext = Depends(internal_actor_context),
):
    await _products(repos, actor).delete(
        product_id, expected_version=body.expected_version, idempotency_key=body.idempotency_key
    )
    return {"product_id": str(product_id), "deleted": True}


@router.post("/projects", response_model=ProjectResponse, status_code=status.HTTP_201_CREATED)
async def create_project(
    body: ProjectCreate,
    repos: PortfolioRepositories = Depends(get_portfolio_repositories),
    actor: ActorContext = Depends(internal_actor_context),
):
    return await _projects(repos, actor).create(body)


@router.get("/projects/{project_id}", response_model=ProjectResponse)
async def get_project(
    project_id: UUID,
    repos: PortfolioRepositories = Depends(get_portfolio_repositories),
    actor: ActorContext = Depends(internal_actor_context),
):
    return await _projects(repos, actor).get(project_id)


@router.get("/projects", response_model=ProjectListResponse)
async def list_projects(
    product_id: UUID | None = None,
    status_filter: ProjectStatus | None = Query(default=None, alias="status"),
    after_id: UUID | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    repos: PortfolioRepositories = Depends(get_portfolio_repositories),
    actor: ActorContext = Depends(internal_actor_context),
):
    items, next_id = await _projects(repos, actor).list(
        product_id=product_id, status=status_filter, after_id=after_id, limit=limit
    )
    return ProjectListResponse(items=items, next_after_id=next_id)


@router.patch("/projects/{project_id}", response_model=ProjectResponse)
async def update_project(
    project_id: UUID,
    body: ProjectUpdate,
    repos: PortfolioRepositories = Depends(get_portfolio_repositories),
    actor: ActorContext = Depends(internal_actor_context),
):
    return await _projects(repos, actor).update(project_id, body)


@router.delete("/projects/{project_id}")
async def delete_project(
    project_id: UUID,
    body: ProjectDeleteRequest,
    repos: PortfolioRepositories = Depends(get_portfolio_repositories),
    actor: ActorContext = Depends(internal_actor_context),
):
    await _projects(repos, actor).delete(
        project_id, expected_version=body.expected_version, idempotency_key=body.idempotency_key
    )
    return {"project_id": str(project_id), "deleted": True}


@router.post(
    "/projects/{project_id}/repositories",
    response_model=RepositoryBindingResponse,
    status_code=status.HTTP_201_CREATED,
)
async def attach_repository(
    project_id: UUID,
    body: RepositoryBindingCreate,
    repos: PortfolioRepositories = Depends(get_portfolio_repositories),
    actor: ActorContext = Depends(internal_actor_context),
):
    return await _bindings(repos, actor).attach(project_id, body)


@router.get("/projects/{project_id}/repositories", response_model=RepositoryBindingListResponse)
async def list_repositories(
    project_id: UUID,
    provider: str | None = None,
    role: RepositoryRole | None = None,
    after_id: UUID | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    repos: PortfolioRepositories = Depends(get_portfolio_repositories),
    actor: ActorContext = Depends(internal_actor_context),
):
    items, next_id = await _bindings(repos, actor).list(
        project_id, provider=provider, role=role, after_id=after_id, limit=limit
    )
    return RepositoryBindingListResponse(items=items, next_after_id=next_id)


@router.delete("/projects/{project_id}/repositories/{binding_id}")
async def detach_repository(
    project_id: UUID,
    binding_id: UUID,
    body: DetachRequest,
    repos: PortfolioRepositories = Depends(get_portfolio_repositories),
    actor: ActorContext = Depends(internal_actor_context),
):
    await _bindings(repos, actor).detach(
        project_id,
        binding_id,
        expected_version=body.expected_version,
        idempotency_key=body.idempotency_key,
    )
    return {"binding_id": str(binding_id), "detached": True}


@router.delete("/repositories/{binding_id}")
async def detach_repository_by_id(
    binding_id: UUID,
    body: DetachRequest,
    repos: PortfolioRepositories = Depends(get_portfolio_repositories),
    actor: ActorContext = Depends(internal_actor_context),
):
    await _bindings(repos, actor).detach_by_id(
        binding_id, expected_version=body.expected_version, idempotency_key=body.idempotency_key
    )
    return {"binding_id": str(binding_id), "detached": True}
