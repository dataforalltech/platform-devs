"""Derivação determinística: (server, tool, capability) -> Operation + Tool binding.

Heurísticas transparentes (NÃO um LLM) que classificam os 298 tools da auditoria em
domínio/recurso/operação/efeitos/risco. É um SEED de qualidade aproximada — a ADR-009
(D9.10) prevê curadoria incremental depois. Toda regra aqui é explícita e testável.
"""

from __future__ import annotations

from .models import (
    Approval, BlastRadius, Capability, Contract, Execution, Metadata, OperationSpec,
    Resource, Risk, RiskLevel,
)

# server (dir da auditoria) -> domínio (ADR-009)
SERVER_DOMAIN = {
    "deploy-mcp-server": "delivery", "pipeline-mcp-server": "delivery",
    "services-mcp-server": "infra", "config-mcp-server": "infra", "infra-mcp-server": "infra",
    "qa-mcp-server": "testing", "test-mcp-server": "testing", "qa-engineer-mcp-server": "testing",
    "security-mcp-server": "security",
    "docs-mcp-server": "documentation",
    "ai-governance-mcp-server": "governance", "audit-mcp-server": "governance",
    "architecture-mcp-server": "architecture",
    "backend-mcp-server": "development", "frontend-mcp-server": "development",
    "devops-mcp-server": "development",
    "product-owner-mcp-server": "product", "product-manager-mcp-server": "product",
    "session-mcp-server": "platform", "dev-twin-mcp-server": "platform",
}

# server -> capability (agrupador dentro do domínio)
SERVER_CAPABILITY = {
    "deploy-mcp-server": "deployment", "pipeline-mcp-server": "promotion",
    "services-mcp-server": "service-registry", "config-mcp-server": "configuration",
    "infra-mcp-server": "provisioning", "qa-mcp-server": "quality", "test-mcp-server": "test-planning",
    "qa-engineer-mcp-server": "test-authoring", "security-mcp-server": "app-security",
    "docs-mcp-server": "docs", "ai-governance-mcp-server": "ai-governance",
    "audit-mcp-server": "audit", "architecture-mcp-server": "architecture",
    "backend-mcp-server": "backend", "frontend-mcp-server": "frontend", "devops-mcp-server": "devops",
    "product-owner-mcp-server": "product-ownership", "product-manager-mcp-server": "product-management",
    "session-mcp-server": "session", "dev-twin-mcp-server": "identity",
}
SERVER_DEFAULT_RESOURCE = {
    "deploy-mcp-server": "deployment", "pipeline-mcp-server": "pipeline",
    "services-mcp-server": "service", "config-mcp-server": "config", "infra-mcp-server": "vm",
    "qa-mcp-server": "test", "test-mcp-server": "test_plan", "qa-engineer-mcp-server": "test_artifact",
    "security-mcp-server": "security_artifact", "docs-mcp-server": "document",
    "ai-governance-mcp-server": "policy", "audit-mcp-server": "audit",
    "architecture-mcp-server": "architecture", "backend-mcp-server": "backend_artifact",
    "frontend-mcp-server": "frontend_artifact", "devops-mcp-server": "devops_artifact",
    "product-owner-mcp-server": "product_artifact", "product-manager-mcp-server": "product_artifact",
    "session-mcp-server": "session", "dev-twin-mcp-server": "token",
}
# dependências externas por server (best-effort; refinável)
SERVER_REQUIRES = {
    "deploy-mcp-server": ["github", "acr"], "pipeline-mcp-server": ["github"],
    "infra-mcp-server": ["terraform"],
}
HIGH_RISK_SERVERS = {"deploy-mcp-server", "infra-mcp-server", "pipeline-mcp-server"}

# palavra-chave no nome do tool -> recurso (primeira que casar vence)
RESOURCE_KEYWORDS = [
    ("health", "service"), ("branch", "branch"), ("_pr", "pull_request"), ("prs", "pull_request"),
    ("repo", "repository"), ("pipeline", "pipeline"), ("deploy", "deployment"),
    ("credential", "credential"), ("secret", "credential"), ("env", "environment"),
    ("tenant", "tenant"), ("session", "session"), ("task", "task"), ("doc", "document"),
    ("audit", "audit"), ("policy", "policy"), ("lease", "vm"), ("vm", "vm"), ("token", "token"),
    ("suggestion", "suggestion"), ("gate", "gate"), ("port", "service"), ("service", "service"),
    ("workflow", "workflow"), ("commit", "commit"), ("test", "test"), ("scenario", "test"),
    ("checklist", "checklist"), ("bug", "bug"), ("coverage", "coverage"), ("adr", "adr"),
    ("persona", "persona"), ("story", "user_story"), ("backlog", "backlog"),
    ("kafka", "broker"), ("redis", "cache"), ("docker", "container"), ("infra", "infra"),
]
# verbo (1º token) -> efeitos (write). reads recebem effects=["read"].
VERB_EFFECTS = {
    "deploy": ["deploy"], "promote": ["deploy"], "release": ["deploy"], "rollback": ["rollback"],
    "create": ["write"], "update": ["write"], "set": ["write"], "register": ["write"],
    "add": ["write"], "save": ["write"], "record": ["write"], "sync": ["write"],
    "delete": ["delete"], "remove": ["delete"], "unregister": ["delete"], "clear": ["delete"],
    "run": ["execute"], "trigger": ["execute"], "launch": ["execute"], "stop": ["execute"],
    "cancel": ["execute"], "retry": ["execute"], "reload": ["restart"], "restart": ["restart"],
    "merge": ["merge"], "commit": ["write"], "push": ["write", "external_api"], "clone": ["write"],
    "acr": ["build"], "scaffold": ["write"], "setup": ["write"], "generate": ["generate"],
    "rotate": ["write"], "revoke": ["write"], "reset": ["write"], "approve": ["write"],
    "submit": ["write"], "start": ["write"], "confirm": ["write"], "complete": ["write"],
    "fail": ["write"], "block": ["write"], "authenticate": ["write"], "refresh": ["write"],
    "redact": ["write"], "watch": ["write"], "accept": ["write"], "reject": ["write"],
    "defer": ["write"], "supersede": ["write"], "ensure": ["write"], "check": ["read"],
}


def provider_id(server: str) -> str:
    return server[:-7] if server.endswith("-server") else server  # deploy-mcp-server -> deploy-mcp


def _resource(tool: str, server: str) -> str:
    low = tool.lower()
    for kw, res in RESOURCE_KEYWORDS:
        if kw in low:
            return res
    return SERVER_DEFAULT_RESOURCE.get(server, "generic")


def _effects(verb: str, capability: str) -> list[str]:
    if capability == "read":
        return ["read"]
    return VERB_EFFECTS.get(verb, ["write"])


def _requires(tool: str, server: str) -> list[str]:
    req = list(SERVER_REQUIRES.get(server, []))
    low = tool.lower()
    for kw, dep in (("kafka", "kafka"), ("redis", "redis"), ("docker", "docker"),
                    ("terraform", "terraform"), ("acr", "acr")):
        if kw in low and dep not in req:
            req.append(dep)
    return req


def _blast_radius(capability: str, effects: list[str], resource: str) -> BlastRadius:
    if capability == "read":
        return BlastRadius.NONE
    if {"deploy", "rollback"} & set(effects):
        return BlastRadius.ENVIRONMENT
    if resource == "tenant":
        return BlastRadius.TENANT
    if "delete" in effects:
        return BlastRadius.SERVICE
    return BlastRadius.SERVICE


def _level(capability: str, effects: list[str], server: str, blast: BlastRadius) -> RiskLevel:
    if capability == "read":
        return RiskLevel.LOW
    if blast in (BlastRadius.ENVIRONMENT, BlastRadius.TENANT, BlastRadius.GLOBAL) \
            or "delete" in effects or "deploy" in effects or server in HIGH_RISK_SERVERS:
        return RiskLevel.HIGH
    return RiskLevel.MEDIUM


def _approval(level: RiskLevel) -> Approval:
    return Approval.N2 if level in (RiskLevel.HIGH, RiskLevel.CRITICAL) else Approval.NONE


def _execution(capability: str, verb: str) -> Execution:
    is_async = verb in {"deploy", "run", "trigger", "acr", "promote", "launch", "scaffold"}
    return Execution(
        idempotent=(capability == "read"),
        side_effects=(capability == "write"),
        is_async=is_async,
        streaming=False,
        timeout_s=900 if is_async else 60,
        retry_policy="read-only" if capability == "read" else "none",
    )


def derive_operation(server: str, tool: str, capability: str) -> tuple[str, OperationSpec, Metadata]:
    """Retorna (operation_id, OperationSpec, Metadata) — id = <domínio>.<tool> (chave de merge)."""
    domain = SERVER_DOMAIN.get(server, "platform")
    verb = tool.split("_")[0].lower()
    resource = _resource(tool, server)
    effects = _effects(verb, capability)
    requires = _requires(tool, server)
    blast = _blast_radius(capability, effects, resource)
    level = _level(capability, effects, server, blast)
    op_id = f"{domain}.{tool}"

    spec = OperationSpec(
        domain=domain,
        capability=SERVER_CAPABILITY.get(server, domain),
        resource=Resource(type=resource),
        operation=verb,
        authz=Capability(capability),
        risk=Risk(effects=effects, requires=requires, blast_radius=blast,
                  default_level=level, approval_required=_approval(level)),
        contract=Contract(execution=_execution(capability, verb)),
    )
    meta = Metadata(
        name=f"{domain}/{tool}", uid=op_id, domain=domain,
        title=tool.replace("_", " "),
        tags=[domain, SERVER_CAPABILITY.get(server, domain), capability],
    )
    return op_id, spec, meta
