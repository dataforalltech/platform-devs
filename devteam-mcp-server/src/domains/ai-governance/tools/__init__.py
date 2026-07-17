"""Tools MCP — uma função pura por capacidade exposta.

Cada função recebe um GovernanceRepository e os kwargs validados, e devolve
um dict serializável em JSON. As tools NÃO conhecem o protocolo MCP — a
camada `server/mcp_server.py` é quem registra e adapta para o protocolo.
"""

from .adr_tool import create_adr
from .audit_tool import get_audit_log
from .checklist_tool import get_final_response_template
from .decision_tool import validate_agent_decision
from .graph_tool import (
    GraphUnavailable,
    find_consumers_of,
    find_dependencies_of,
    get_service_metadata,
    query_ecosystem_graph,
)
from .guidelines_tool import get_agent_guidelines, get_pre_execution_checklist
from .migration_tool import validate_migration
from .ownership_tool import (
    check_scope,
    get_port_map,
    get_service_dependencies,
    get_service_ownership,
    validate_lib_change,
)
from .policy_tool import (
    get_contract_change_policy,
    get_fallback_policy,
    get_forbidden_actions,
    get_layer_policy,
)
from .repository_tool import search_governance_knowledge
from .suggestion_tool import (
    SuggestionsUnavailable,
    get_suggestion,
    list_suggestions,
    submit_suggestion,
    update_suggestion_status,
)

__all__ = [
    "get_agent_guidelines",
    "get_pre_execution_checklist",
    "get_layer_policy",
    "get_fallback_policy",
    "get_contract_change_policy",
    "get_forbidden_actions",
    "get_final_response_template",
    "search_governance_knowledge",
    "validate_agent_decision",
    "query_ecosystem_graph",
    "find_consumers_of",
    "find_dependencies_of",
    "get_service_metadata",
    "GraphUnavailable",
    "submit_suggestion",
    "list_suggestions",
    "get_suggestion",
    "update_suggestion_status",
    "SuggestionsUnavailable",
    # sprint 1
    "get_service_ownership",
    "get_service_dependencies",
    "get_port_map",
    "check_scope",
    # sprint 2
    "validate_lib_change",
    "validate_migration",
    "create_adr",
    # sprint 3 — audit trail
    "get_audit_log",
]
