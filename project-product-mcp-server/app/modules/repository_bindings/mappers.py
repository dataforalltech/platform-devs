"""Repository binding record to public response mapping."""

from app.models import RepositoryBindingRecord
from platform_project_product.schemas import RepositoryBindingResponse, RepositoryMetadata


def to_response(record: RepositoryBindingRecord) -> RepositoryBindingResponse:
    return RepositoryBindingResponse(
        binding_id=record.binding_id,
        project_id=record.project_id,
        provider=record.provider,
        connector_ref=record.connector_ref,
        repository_ref=record.repository_ref,
        role=record.role,
        metadata=RepositoryMetadata.model_validate(record.metadata),
        version=record.version,
        is_active=record.is_active,
        id_environment=record.id_environment,
        id_owner=record.id_owner,
        created_at=record.created_at,
        updated_at=record.updated_at,
        created_by=record.created_by,
        updated_by=record.updated_by,
    )
