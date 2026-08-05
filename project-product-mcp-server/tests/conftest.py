from __future__ import annotations

import os
import sys
from pathlib import Path

SERVICE = Path(__file__).resolve().parents[1]
REPOS = SERVICE.parents[1]
sys.path[:0] = [
    str(SERVICE / "mcp"),
    str(SERVICE / "src"),
    str(SERVICE),
    str(REPOS / "platform-core-lib" / "src"),
    str(REPOS / "platform-database-lib" / "src"),
    str(REPOS / "platform-tenant-lib" / "src"),
    str(REPOS / "platform-auth" / "src"),
    str(REPOS / "privates-libs" / "platform-observability-lib" / "src"),
]

_DEFAULTS = {
    "RUNTIME_ENV": "local",
    "ENVIRONMENT": "test",
    "ADMIN_DB_HOST": "admin.invalid",
    "ADMIN_DB_USER": "test-user",
    "ADMIN_DB_PASSWORD": "test-password",
    "READINESS_TENANT_ID": "11111111-1111-4111-8111-111111111111",
    "JWT_ISSUER": "https://admin.invalid",
    "JWT_AUDIENCE": "platform-project-product",
    "JWT_JWKS_URL": "https://admin.invalid/.well-known/jwks.json",
    # O que a API ACEITA na própria /api/internal/* (papel de destino).
    "INTERNAL_API_TOKEN": "internal-test-token",
    # O que o SIDECAR APRESENTA, uma credencial por destino — STD-SEC-002, passo 1
    # da "Estratégia de migração". O destino faz parte do NOME; um nome sem
    # destino só consegue designar um valor para todos eles.
    "INTERNAL_API_TARGETS": "platform-project-product,platform-governance",
    "INTERNAL_API_TOKEN__PLATFORM_PROJECT_PRODUCT": "token-para-project-product",
    "INTERNAL_API_TOKEN__PLATFORM_GOVERNANCE": "token-para-governance",
    "METRICS_SCRAPE_TOKEN": "metrics-test-token",
    "RATE_LIMIT_STORAGE_URI": "",
    "METRICS_ENABLED": "false",
    "LOG_TEMP_FOLDER": str(SERVICE),
    "SERVICE_BASE_URL": "http://service.invalid:8000",
    "SERVICE_READINESS_URL": "http://service.invalid:9090/health/ready",
    "SERVICE_ALLOWED_HOSTS": '["service.invalid"]',
    "PRIVATE_NETWORK_ENCRYPTED": "false",
    "GOVERNANCE_BASE_URL": "http://governance.invalid:8000",
    "GOVERNANCE_ALLOWED_HOSTS": '["governance.invalid"]',
    "GOVERNANCE_INTERNAL_TOKEN": "governance-test-token",
    "MCP_TWIN_AUDIENCE": "mcp:portfolio",
    "MCP_TWIN_ISSUER": "platform-admin/twin",
    "URL_ADMIN_TWIN_JWKS": "https://admin.invalid/api/v1/twin/jwks.json",
    "IDENTITY_ALLOWED_HOSTS": '["admin.invalid"]',
    "MCP_PORT": "7121",
}
for key, value in _DEFAULTS.items():
    os.environ.setdefault(key, value)
