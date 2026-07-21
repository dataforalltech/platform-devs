"""Product record to public response mapping."""

from app.models import ProductRecord
from platform_project_product.schemas import ProductResponse


def to_response(record: ProductRecord) -> ProductResponse:
    return ProductResponse(
        product_id=record.product_id,
        slug=record.slug,
        name=record.name,
        description=record.description,
        status=record.status,
        owner_user_refs=record.owner_user_refs,
        version=record.version,
        is_active=record.is_active,
        id_environment=record.id_environment,
        id_owner=record.id_owner,
        created_at=record.created_at,
        updated_at=record.updated_at,
        created_by=record.created_by,
        updated_by=record.updated_by,
    )
