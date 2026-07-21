"""Re-export the canonical platform error contract."""

from platform_core.exceptions import (
    AuthorizationError,
    ConflictError,
    DomainError,
    ErrorResponse,
    IntegrationClientError,
    NotFoundError,
    ValidationError,
    domain_exception_handler,
    generic_exception_handler,
    http_exception_handler,
    integration_exception_handler,
    validation_exception_handler,
)

__all__ = [
    "AuthorizationError",
    "ConflictError",
    "DomainError",
    "ErrorResponse",
    "IntegrationClientError",
    "NotFoundError",
    "ValidationError",
    "domain_exception_handler",
    "generic_exception_handler",
    "http_exception_handler",
    "integration_exception_handler",
    "validation_exception_handler",
]
