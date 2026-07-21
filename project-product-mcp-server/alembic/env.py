"""Tenant-aware Alembic runtime delegated to platform-database-lib."""

from platform_database.migration import run_migrations

from app.core.config import settings

run_migrations(settings, target_metadata=None, version_table="alembic_version_project_product")
