from __future__ import annotations

from .api_contract_tool import (
    delete_api_contract,
    get_api_contract,
    list_api_contracts,
    normalize_method,
    save_api_contract,
)
from .artifact_tool import delete_artifact, get_artifact, list_artifacts, save_artifact
from .auth_policy_tool import (
    delete_auth_policy,
    get_auth_policy,
    list_auth_policies,
    save_auth_policy,
)
from .code_review_tool import (
    delete_code_review,
    get_code_review,
    list_code_reviews,
    save_code_review,
)
from .database_schema_tool import (
    delete_database_schema,
    get_database_schema,
    list_database_schemas,
    save_database_schema,
    update_database_schema,
)
from .generator_tool import (
    generate_api_contract,
    generate_auth_policy,
    generate_database_schema,
    generate_event_contracts,
    generate_fastapi_router,
    generate_migration,
    generate_repository_layer,
    generate_service_layer,
)

__all__ = [
    # API Contracts
    "save_api_contract",
    "list_api_contracts",
    "get_api_contract",
    "delete_api_contract",
    "normalize_method",
    # Database Schemas
    "save_database_schema",
    "list_database_schemas",
    "get_database_schema",
    "update_database_schema",
    "delete_database_schema",
    # Auth Policies
    "save_auth_policy",
    "list_auth_policies",
    "get_auth_policy",
    "delete_auth_policy",
    # Backend Artifacts
    "save_artifact",
    "list_artifacts",
    "get_artifact",
    "delete_artifact",
    # Code Reviews
    "save_code_review",
    "list_code_reviews",
    "get_code_review",
    "delete_code_review",
    # Geradores determinísticos (COMPUTE PURO — não persistem)
    "generate_fastapi_router",
    "generate_service_layer",
    "generate_repository_layer",
    "generate_database_schema",
    "generate_migration",
    "generate_api_contract",
    "generate_auth_policy",
    "generate_event_contracts",
]
