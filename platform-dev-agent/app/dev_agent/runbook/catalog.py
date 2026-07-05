"""Declarative runbook catalog (versioned DAG).

Copied (in form) from the marketing agent's ``runbook_catalog.py`` frozen
dataclasses, adapted for the DevTeam:

- each task carries its ``tool`` directly (single source of truth in the spec,
  no parallel ``RUNBOOK_TASK_TOOLS`` map);
- ``RunbookSpec`` is versioned (``version``) so the generated plan can record
  ``runbook_version``;
- ``capability_override`` / ``risk_override`` let a task pin its classification;
- ``required`` propagates to the PlanItem and drives the final plan status.

The catalog is an import-time constant. Tool names are real gateway operations
(``<namespace>.<operationId>``).
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RunbookTaskSpec:
    """One task (DAG node) of a runbook, bound to exactly one gateway tool."""

    title: str
    description: str
    required: bool
    responsible: str  # security | qa-engineer | architecture | backend | ...
    tool: str  # "<namespace>.<operationId>" — single source here
    input_schema: dict  # JSON-schema-ish spec of expected inputs
    depends_on: list[str] = field(default_factory=list)  # task_ids of the SAME runbook
    capability_override: str | None = None  # force read/write; else derived from verb
    risk_override: str | None = None  # force low/medium/high; else heuristic


@dataclass(frozen=True)
class RunbookSpec:
    """A versioned runbook: a DAG of tasks keyed by ``task_id``."""

    id: str
    version: str  # SemVer — pins the generated plan
    name: str
    description: str
    responsible_profile: str
    tasks: dict[str, RunbookTaskSpec]  # key = task_id (depends_on target)


# --- The one runbook of the walking skeleton: linear, read-only, real tools ---
# check_health -> run_tests -> generate_report
_HEALTH_TO_REPORT = RunbookSpec(
    id="health_to_report",
    version="1.0.0",
    name="Health check -> tests -> report",
    description=(
        "Linear read-only pipeline: check service health, run the test suite, "
        "then generate a QA report. Proves transport + persistence end-to-end "
        "without any write or approval."
    ),
    responsible_profile="qa-engineer",
    tasks={
        "check_health": RunbookTaskSpec(
            title="Check service health",
            description="Query the health of the target service via the services gateway.",
            required=True,
            responsible="devops",
            tool="services-mcp.check_health",
            input_schema={
                "type": "object",
                "properties": {"service": {"type": "string"}},
                "required": ["service"],
            },
            depends_on=[],
        ),
        "run_tests": RunbookTaskSpec(
            title="Run test suite",
            description="Run the automated test suite via the QA gateway.",
            required=True,
            responsible="qa-engineer",
            tool="qa-mcp.run_tests",
            input_schema={
                "type": "object",
                "properties": {"suite": {"type": "string"}},
                "required": ["suite"],
            },
            depends_on=["check_health"],
        ),
        "generate_report": RunbookTaskSpec(
            title="Generate QA report",
            description="Generate a consolidated QA report via the QA gateway.",
            required=False,
            responsible="qa-engineer",
            tool="qa-mcp.generate_report",
            input_schema={
                "type": "object",
                "properties": {"format": {"type": "string"}},
                "required": [],
            },
            depends_on=["run_tests"],
            # The 'generate_' verb heuristic would mark this WRITE, but this
            # report generation is read-only in intent (it only reads test
            # results). Pin it READ so the runbook stays fully read-only. This
            # also exercises capability_override end-to-end.
            capability_override="read",
        ),
    },
)


# --- A runbook WITH a write/high-risk step, to exercise the N2 approval gate ---
# deploy (deploy-mcp.* => write + owner "deploy" => HIGH) requires per-item
# confirmation (N2); "approve all" alone never runs it.
_DEPLOY_SERVICE = RunbookSpec(
    id="deploy_service",
    version="1.0.0",
    name="Deploy a service (pre-check -> tests -> deploy -> verify)",
    description=(
        "Pipeline com etapa de ALTO RISCO: valida saude, roda testes, faz o deploy "
        "(write/high-risk -> exige confirmacao individual N2) e verifica pos-deploy."
    ),
    responsible_profile="devops",
    tasks={
        "check_health": RunbookTaskSpec(
            title="Pre-deploy health check",
            description="Confirma que o servico-alvo esta saudavel antes do deploy.",
            required=True, responsible="devops", tool="services-mcp.check_health",
            input_schema={"type": "object", "properties": {"service": {"type": "string"}},
                          "required": ["service"]},
            depends_on=[],
        ),
        "run_tests": RunbookTaskSpec(
            title="Run test suite",
            description="Roda a suite de testes antes de promover.",
            required=True, responsible="qa-engineer", tool="qa-mcp.run_tests",
            input_schema={"type": "object", "properties": {"suite": {"type": "string"}},
                          "required": ["suite"]},
            depends_on=["check_health"],
        ),
        "deploy": RunbookTaskSpec(
            title="Deploy the service (HIGH RISK)",
            description="Cria o deployment via deploy-mcp. Passo destrutivo -> N2.",
            required=True, responsible="devops", tool="deploy-mcp.create_deployment",
            input_schema={"type": "object",
                          "properties": {"service": {"type": "string"},
                                         "version": {"type": "string"}},
                          "required": []},
            depends_on=["run_tests"],
        ),
        "verify": RunbookTaskSpec(
            title="Post-deploy verification",
            description="Verifica a saude do servico apos o deploy.",
            required=False, responsible="devops", tool="services-mcp.check_health",
            input_schema={"type": "object", "properties": {}, "required": []},
            depends_on=["deploy"],
        ),
    },
)


# --- A read-only runbook wired to tools that ALREADY EXIST in the live gateway ---
# catalog (admin/auth health + list tenants), so approve_and_execute is genuinely
# GREEN against the real gateway TODAY. Unlike health_to_report (which targets
# services-mcp/qa-mcp — real services, but not yet registered on this gateway), every
# tool here is in the catalog and takes no arguments, so it returns a real payload.
# Proves the full chain PAT -> Twin -> PDP -> tool end-to-end with live data.
_PLATFORM_HEALTH = RunbookSpec(
    id="platform_health",
    version="1.0.0",
    name="Platform health smoke test (admin -> auth -> tenants)",
    description=(
        "Pipeline read-only contra tools JA registradas no gateway: saude do admin, "
        "saude do auth e lista de tenants. Fecha verde de verdade (payload real) sem "
        "depender de services-mcp/qa-mcp."
    ),
    responsible_profile="devops",
    tasks={
        "admin_health": RunbookTaskSpec(
            title="Check admin service health",
            description="Consulta a saude do platform-admin via o gateway.",
            required=True,
            responsible="devops",
            tool="admin.admin_health_check",
            input_schema={"type": "object", "properties": {}, "required": []},
            depends_on=[],
            capability_override="read",
        ),
        "auth_health": RunbookTaskSpec(
            title="Check auth service health",
            description="Consulta a saude do platform-auth via o gateway.",
            required=True,
            responsible="devops",
            tool="auth.auth_health_check",
            input_schema={"type": "object", "properties": {}, "required": []},
            depends_on=["admin_health"],
            capability_override="read",
        ),
        "list_tenants": RunbookTaskSpec(
            title="List tenants",
            description="Lista os tenants via o gateway (leitura).",
            required=False,
            responsible="qa-engineer",
            tool="auth.auth_list_tenants",
            input_schema={"type": "object", "properties": {}, "required": []},
            depends_on=["auth_health"],
            capability_override="read",
        ),
    },
)


RUNBOOK_CATALOG: dict[str, RunbookSpec] = {
    _HEALTH_TO_REPORT.id: _HEALTH_TO_REPORT,
    _DEPLOY_SERVICE.id: _DEPLOY_SERVICE,
    _PLATFORM_HEALTH.id: _PLATFORM_HEALTH,
}


def get_runbook(runbook_id: str) -> RunbookSpec:
    """Return the runbook by id, or raise ``ValueError`` listing the available ids."""
    runbook = RUNBOOK_CATALOG.get(runbook_id)
    if runbook is None:
        raise ValueError(
            f"Runbook {runbook_id!r} does not exist. Available: {list(RUNBOOK_CATALOG)}"
        )
    return runbook
