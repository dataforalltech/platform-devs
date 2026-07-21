from __future__ import annotations

import importlib.util
from contextlib import asynccontextmanager
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from platform_core.request_context import get_table_case
from pydantic import SecretStr, ValidationError

from app.core import repositories
from app.core.config import Settings
from app.models import (
    IdempotencyRecord,
    ProductRecord,
    ProjectRecord,
    RepositoryBindingRecord,
)
from platform_project_product.schemas import (
    ProductCreate,
    ProductUpdate,
    ProjectCreate,
    ProjectUpdate,
    RepositoryMetadata,
    ServiceReferences,
)

SERVICE = Path(__file__).resolve().parents[1]


def _migration_module(revision: str = "0001_project_product"):
    path = SERVICE / f"alembic/versions/{revision}.py"
    spec = importlib.util.spec_from_file_location(f"project_product_{revision}", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_settings_accept_only_supported_tenant_engines():
    assert Settings(DB_ENGINE="POSTGRESQL").DB_ENGINE == "postgresql"
    assert Settings(DB_ENGINE="MySQL").DB_ENGINE == "mysql"
    with pytest.raises(ValueError, match="DB_ENGINE"):
        Settings(DB_ENGINE="sqlite")


def test_cloud_accepts_canonical_issuer_and_requires_https_jwks(monkeypatch):
    def resolved_secret(_name, *, local_value, **_kwargs):
        return local_value or SecretStr("resolved-secret")

    monkeypatch.setattr("app.core.secrets.resolve_secret", resolved_secret)
    values = {
        "RUNTIME_ENV": "cloud",
        "ENVIRONMENT": "test",
        "ADMIN_DB_HOST": "admin.internal",
        "ADMIN_DB_USER": "service",
        "READINESS_TENANT_ID": "tenant-id",
        "JWT_ISSUER": "platform-auth",
        "JWT_AUDIENCE": "platform-project-product",
        "JWT_JWKS_URL": "https://admin.internal/.well-known/jwks.json",
    }

    assert Settings(**values).JWT_ISSUER == "platform-auth"
    with pytest.raises(ValueError, match="JWT_JWKS_URL must use https"):
        Settings(**{**values, "JWT_JWKS_URL": "http://admin.internal/jwks.json"})


@pytest.mark.parametrize(
    "factory",
    [
        lambda refs: ProductCreate(
            idempotency_key="owner-validation-001",
            slug="product",
            name="Product",
            owner_user_refs=refs,
        ),
        lambda refs: ProductUpdate(
            idempotency_key="owner-validation-002",
            expected_version=1,
            owner_user_refs=refs,
        ),
        lambda refs: ProjectCreate(
            idempotency_key="owner-validation-003",
            product_id=uuid4(),
            slug="project",
            name="Project",
            owner_user_refs=refs,
        ),
        lambda refs: ProjectUpdate(
            idempotency_key="owner-validation-004",
            expected_version=1,
            owner_user_refs=refs,
        ),
    ],
)
@pytest.mark.parametrize("invalid_refs", [["duplicate", "duplicate"], [""], ["x" * 513]])
def test_all_owner_reference_contracts_apply_item_validation(factory, invalid_refs):
    with pytest.raises(ValidationError, match="owner references"):
        factory(invalid_refs)


@pytest.mark.parametrize(
    "web_url",
    [
        "javascript:alert(1)",
        "file:///tmp/repository",
        "https://user:password@example.invalid/repository",
        "https://example.invalid/repository#readme",
        "https://example.invalid\\@evil.invalid/repository",
        "http://example.invalid/repo sitory",
        "http://example.invalid/repo\tsitory",
    ],
)
def test_repository_web_url_rejects_unsafe_schemes_and_authority(web_url):
    with pytest.raises(ValidationError, match="web_url"):
        RepositoryMetadata(web_url=web_url)


@pytest.mark.parametrize("blank", ["", "   ", "\t"])
def test_service_reference_blank_string_is_normalized_to_absent(blank):
    # An empty/blank opaque ref must collapse to null so the record still satisfies
    # the MCP output contract (minLength 1 or null) and stays readable via MCP.
    assert ServiceReferences(governance_ref=blank).governance_ref is None


@pytest.mark.parametrize(
    "web_url",
    ["https://github.com/org/repository", "http://git.internal/org/repository"],
)
def test_repository_web_url_accepts_provider_neutral_http_urls(web_url):
    assert RepositoryMetadata(web_url=web_url).web_url == web_url


def test_models_decode_json_text_returned_by_database_drivers():
    product_id = uuid4()
    project_id = uuid4()
    common = {
        "version": 1,
        "last_idempotency_key": "driver-json-001",
        "id_environment": 0,
        "id_owner": 0,
    }

    product = ProductRecord.model_validate(
        {
            **common,
            "product_id": product_id,
            "slug": "product",
            "name": "Product",
            "status": "active",
            "owner_user_refs": '["user:1"]',
        }
    )
    project = ProjectRecord.model_validate(
        {
            **common,
            "project_id": project_id,
            "product_id": product_id,
            "slug": "project",
            "name": "Project",
            "status": "active",
            "owner_user_refs": "[]",
            "service_refs": '{"governance_ref":"governance:1"}',
        }
    )
    binding = RepositoryBindingRecord.model_validate(
        {
            **common,
            "binding_id": uuid4(),
            "project_id": project_id,
            "provider": "github",
            "connector_ref": "connector:1",
            "repository_ref": "repo:1",
            "role": "source",
            "metadata": '{"default_branch":"main"}',
        }
    )
    idempotency = IdempotencyRecord.model_validate(
        {
            "id_environment": 0,
            "id_owner": 0,
            "idempotency_key": "driver-json-001",
            "operation": "product.create",
            "request_hash": "a" * 64,
            "target_type": "product",
            "target_id": product_id,
            "response_body": '{"product_id":"value"}',
            "status": "completed",
        }
    )

    assert product.owner_user_refs == ["user:1"]
    assert project.service_refs == {"governance_ref": "governance:1"}
    assert binding.metadata == {"default_branch": "main"}
    assert idempotency.response_body == {"product_id": "value"}
    with pytest.raises(ValidationError, match="Database returned malformed JSON"):
        ProductRecord.model_validate(
            {
                **product.model_dump(),
                "owner_user_refs": "not-json",
            }
        )


def test_migration_compiles_postgresql_contract_without_mysql_leakage():
    migration = _migration_module()
    statements = migration.build_upgrade_statements("postgresql")
    sql = "\n".join(statements)

    assert "CREATE TABLE IF NOT EXISTS PORTFOLIO_PRODUCTS" in sql
    assert "UUID NOT NULL UNIQUE" in sql
    assert "JSONB NOT NULL" in sql
    assert "GENERATED ALWAYS AS" not in sql
    assert "WHERE (is_deleted = FALSE)" in sql
    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_portfolio_products_live_slug" in sql
    assert (
        "CONSTRAINT fk_portfolio_projects_product FOREIGN KEY (product_id) "
        "REFERENCES PORTFOLIO_PRODUCTS (product_id) ON DELETE RESTRICT"
    ) in sql
    assert (
        "CONSTRAINT fk_portfolio_bindings_project FOREIGN KEY (project_id) "
        "REFERENCES PORTFOLIO_PROJECTS (project_id) ON DELETE RESTRICT"
    ) in sql


def test_migration_compiles_mysql_84_contract_with_idempotent_table_ddl():
    migration = _migration_module()
    statements = migration.build_upgrade_statements("mysql")
    sql = "\n".join(statements)

    assert len(statements) == 3
    assert "CREATE TABLE IF NOT EXISTS PORTFOLIO_PRODUCTS" in sql
    assert "BIGINT AUTO_INCREMENT PRIMARY KEY" in sql
    assert "CHAR(36) NOT NULL UNIQUE" in sql
    assert "JSON NOT NULL" in sql
    assert "live_slug VARCHAR(80) GENERATED ALWAYS AS" in sql
    assert "live_repository_key BINARY(32) GENERATED ALWAYS AS" in sql
    assert "uq_portfolio_bindings_live_repository" in sql
    assert "JSONB" not in sql
    assert "TIMESTAMPTZ" not in sql
    assert "FOREIGN KEY (product_id) REFERENCES PORTFOLIO_PRODUCTS (product_id)" in sql
    assert "FOREIGN KEY (project_id) REFERENCES PORTFOLIO_PROJECTS (project_id)" in sql


@pytest.mark.parametrize("engine,json_type", [("postgresql", "JSONB"), ("mysql", "JSON")])
def test_forward_migration_adds_payload_bound_idempotency_ledger(engine, json_type):
    migration = _migration_module("0002_integrity_idempotency")
    sql = "\n".join(migration.build_upgrade_statements(engine))

    assert "PORTFOLIO_IDEMPOTENCY_KEYS" in sql
    assert "idempotency_key" in sql
    assert "operation VARCHAR(64) NOT NULL" in sql
    assert "request_hash CHAR(64)" in sql
    assert "target_id" in sql
    assert f"response_body {json_type} NOT NULL" in sql
    assert "status IN ('pending','completed')" in sql
    assert "uq_portfolio_idempotency_key" in sql


@pytest.mark.asyncio
async def test_repository_bundle_sets_and_restores_engine_table_case(monkeypatch):
    observed: list[tuple[str, str]] = []

    class Session:
        _pool = object()
        context = None

        def repository(self, _model, *, table_name):
            observed.append((table_name, get_table_case()))
            return SimpleNamespace()

    @asynccontextmanager
    async def fake_for_tenant(tenant_id):
        assert tenant_id in {"PLATFORM_DEV", "tenant-id"}
        yield Session()

    monkeypatch.setattr(repositories, "for_tenant", fake_for_tenant)
    monkeypatch.setattr(repositories, "dialect_for_pool", lambda pool: object())
    monkeypatch.setattr(repositories.settings, "DB_ENGINE", "mysql")
    previous = get_table_case()
    async with repositories.portfolio_repositories("PLATFORM_DEV"):
        assert all(case == "upper" for _, case in observed)
    assert get_table_case() == previous

    observed.clear()
    monkeypatch.setattr(repositories.settings, "DB_ENGINE", "postgresql")
    async with repositories.portfolio_repositories("tenant-id"):
        assert all(case == "lower" for _, case in observed)
    assert get_table_case() == previous
