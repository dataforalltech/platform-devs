"""config-mcp-server — exportacoes de todas as 21 tools."""
from __future__ import annotations

from .credential_tool import (
    delete_credential,
    get_credential,
    list_credentials,
    set_credential,
    set_credential_secure,
)
from .env_tool import (
    audit_env_files,
    get_env_config,
    list_environments,
    push_env_to_store,
    read_env_file,
    redact_env_secrets,
    set_env_var,
    sync_env_file,
)
from .sysinfo_tool import get_physical_info
from .tenant_tool import get_session_tenant_config, get_tenant_config, list_tenants, set_tenant_config
from .workspace_tool import get_workspace_config, list_workspace_config, set_workspace_config

__all__ = [
    # credentials
    "get_credential",
    "set_credential",
    "set_credential_secure",
    "list_credentials",
    "delete_credential",
    # env
    "get_env_config",
    "set_env_var",
    "list_environments",
    "sync_env_file",
    "read_env_file",
    "audit_env_files",
    "redact_env_secrets",
    "push_env_to_store",
    # sysinfo
    "get_physical_info",
    # tenants
    "get_tenant_config",
    "set_tenant_config",
    "list_tenants",
    "get_session_tenant_config",
    # workspace
    "get_workspace_config",
    "set_workspace_config",
    "list_workspace_config",
]
