"""Authenticated Product REST routes."""

from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.core.context import ActorContext, public_actor_context
from app.core.dependencies import get_portfolio_repositories
from app.core.limiter import limiter
from app.core.repositories import PortfolioRepositories
from app.core.security import require_portfolio_access
from app.modules.products.schemas import (
    DeleteRequest,
    ProductCreate,
    ProductListResponse,
    ProductResponse,
    ProductUpdate,
)
from app.modules.products.services import ProductService
from platform_project_product.schemas import ProductStatus

router = APIRouter(prefix="/products", tags=["Products"])


def _service(repos: PortfolioRepositories, actor: ActorContext) -> ProductService:
    return ProductService(repos, actor)


@router.post(
    "",
    response_model=ProductResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="createProduct",
    dependencies=[Depends(require_portfolio_access("write"))],
)
@limiter.limit("60/minute")
async def create_product(
    request: Request,
    body: ProductCreate,
    repos: PortfolioRepositories = Depends(get_portfolio_repositories),
    actor: ActorContext = Depends(public_actor_context),
):
    return await _service(repos, actor).create(body)


@router.get(
    "/{product_id}",
    response_model=ProductResponse,
    operation_id="getProduct",
    dependencies=[Depends(require_portfolio_access("read"))],
)
@limiter.limit("200/minute")
async def get_product(
    request: Request,
    product_id: UUID,
    repos: PortfolioRepositories = Depends(get_portfolio_repositories),
    actor: ActorContext = Depends(public_actor_context),
):
    return await _service(repos, actor).get(product_id)


@router.get(
    "",
    response_model=ProductListResponse,
    operation_id="listProducts",
    dependencies=[Depends(require_portfolio_access("read"))],
)
@limiter.limit("200/minute")
async def list_products(
    request: Request,
    status_filter: ProductStatus | None = Query(default=None, alias="status"),
    after_id: UUID | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    repos: PortfolioRepositories = Depends(get_portfolio_repositories),
    actor: ActorContext = Depends(public_actor_context),
):
    items, next_id = await _service(repos, actor).list(
        status=status_filter, after_id=after_id, limit=limit
    )
    return ProductListResponse(items=items, next_after_id=next_id)


@router.patch(
    "/{product_id}",
    response_model=ProductResponse,
    operation_id="updateProduct",
    dependencies=[Depends(require_portfolio_access("write"))],
)
@limiter.limit("60/minute")
async def update_product(
    request: Request,
    product_id: UUID,
    body: ProductUpdate,
    repos: PortfolioRepositories = Depends(get_portfolio_repositories),
    actor: ActorContext = Depends(public_actor_context),
):
    return await _service(repos, actor).update(product_id, body)


@router.delete(
    "/{product_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="deleteProduct",
    dependencies=[Depends(require_portfolio_access("delete"))],
)
@limiter.limit("30/minute")
async def delete_product(
    request: Request,
    product_id: UUID,
    body: DeleteRequest,
    repos: PortfolioRepositories = Depends(get_portfolio_repositories),
    actor: ActorContext = Depends(public_actor_context),
):
    await _service(repos, actor).delete(
        product_id,
        expected_version=body.expected_version,
        idempotency_key=body.idempotency_key,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
