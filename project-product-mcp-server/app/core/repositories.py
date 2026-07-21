"""Tenant-scoped repository bundle; handlers pass only ``tenant_id``."""

from __future__ import annotations

from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from platform_core.request_context import reset_table_case, set_table_case
from platform_database.orm import Repository
from platform_database.orm.dialects import Dialect, dialect_for_pool
from platform_database.unit_of_work import UnitOfWork

from app.core.config import settings
from app.core.database import for_tenant
from app.models import (
    IdempotencyRecord,
    ProductRecord,
    ProjectRecord,
    RepositoryBindingRecord,
)
from app.modules.idempotency_repository import IdempotencyRepository
from app.modules.products.repository import ProductRepository
from app.modules.projects.repository import ProjectRepository
from app.modules.repository_bindings.repository import RepositoryBindingRepository

TransactionFactory = Callable[[], Any]


@dataclass(frozen=True)
class PortfolioRepositories:
    products: ProductRepository
    projects: ProjectRepository
    bindings: RepositoryBindingRepository
    idempotency: IdempotencyRepository
    _transaction_factory: TransactionFactory | None = field(default=None, repr=False)

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[PortfolioRepositories]:
        """Open one atomic transaction shared by every portfolio repository."""
        if self._transaction_factory is None:
            # Used by focused unit-test bundles and by a bundle already inside a UoW.
            yield self
            return
        async with self._transaction_factory() as repositories:
            yield repositories


def _repository_bundle(pool: Any, context: Any, dialect: Dialect) -> PortfolioRepositories:
    def repository(model: type, table_name: str):
        return Repository(
            pool,
            model,
            dialect=dialect,
            table_name=table_name,
            context=context,
            require_tenant=True,
        )

    return PortfolioRepositories(
        products=ProductRepository(repository(ProductRecord, "portfolio_products")),
        projects=ProjectRepository(repository(ProjectRecord, "portfolio_projects")),
        bindings=RepositoryBindingRepository(
            repository(
                RepositoryBindingRecord,
                "portfolio_project_repository_bindings",
            )
        ),
        idempotency=IdempotencyRepository(
            repository(IdempotencyRecord, "portfolio_idempotency_keys")
        ),
    )


@asynccontextmanager
async def portfolio_repositories(tenant_id: str):
    table_case_token = set_table_case("upper" if settings.DB_ENGINE == "mysql" else "lower")
    try:
        async with for_tenant(tenant_id) as session:
            dialect = dialect_for_pool(session._pool)

            @asynccontextmanager
            async def transaction():
                # TenantSession intentionally hides raw connections. UnitOfWork consumes
                # only the already-resolved pool and never exposes a connection/credential.
                async with UnitOfWork(session._pool) as unit_of_work:
                    yield _repository_bundle(unit_of_work, session.context, dialect)

            repositories = PortfolioRepositories(
                products=ProductRepository(
                    session.repository(ProductRecord, table_name="portfolio_products")
                ),
                projects=ProjectRepository(
                    session.repository(ProjectRecord, table_name="portfolio_projects")
                ),
                bindings=RepositoryBindingRepository(
                    session.repository(
                        RepositoryBindingRecord,
                        table_name="portfolio_project_repository_bindings",
                    )
                ),
                idempotency=IdempotencyRepository(
                    session.repository(
                        IdempotencyRecord,
                        table_name="portfolio_idempotency_keys",
                    )
                ),
                _transaction_factory=transaction,
            )
            yield repositories
    finally:
        reset_table_case(table_case_token)
