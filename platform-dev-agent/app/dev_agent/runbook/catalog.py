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
    """One task (DAG node) of a runbook.

    Operation-first (ADR-009/ADR-016): a task binds to a catalog **Operation**
    (``operation_id``, e.g. ``delivery.deploy``); the concrete Tool is resolved
    at runtime via the catalog. A transitional ``tool`` fallback keeps the older
    runbooks (which bind a gateway tool directly) working. Exactly one of
    ``operation_id`` / ``tool`` must be set — enforced in ``__post_init__``.
    """

    title: str
    description: str
    required: bool
    responsible: str  # security | qa-engineer | architecture | backend | ...
    input_schema: dict  # JSON-schema-ish spec of expected inputs
    tool: str | None = None  # legacy: "<namespace>.<operationId>" bound directly
    operation_id: str | None = None  # Operation-first: catalog Operation uid
    depends_on: list[str] = field(default_factory=list)  # task_ids of the SAME runbook
    capability_override: str | None = None  # force read/write; else derived from verb
    risk_override: str | None = None  # force low/medium/high; else heuristic

    def __post_init__(self) -> None:
        # Frozen dataclass: this may raise, but must not mutate. Exactly one of
        # operation_id / tool must be set (Operation-first with legacy fallback).
        if bool(self.operation_id) == bool(self.tool):
            raise ValueError(
                f"task {self.title!r}: exactly one of 'operation_id' / 'tool' "
                f"must be set (got operation_id={self.operation_id!r}, tool={self.tool!r})"
            )


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
            tool="qa-mcp.run_unit_tests",
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
            tool="qa-mcp.generate_qa_report",
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
            required=True, responsible="qa-engineer", tool="qa-mcp.run_unit_tests",
            input_schema={"type": "object", "properties": {"suite": {"type": "string"}},
                          "required": ["suite"]},
            depends_on=["check_health"],
        ),
        "deploy": RunbookTaskSpec(
            title="Deploy the service (HIGH RISK)",
            description="Cria o deployment via deploy-mcp. Passo destrutivo -> N2.",
            required=True, responsible="devops", tool="deploy-mcp.deploy",
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


# --- Wave-1 runbooks (Fase 6) — Operation-first (ADR-009/ADR-016) -----------
# These bind each task to a catalog Operation (operation_id); the concrete Tool
# is resolved at runtime via the catalog. No capability_override/risk_override:
# the Operation in the catalog is authoritative for capability + risk.

_PERMISSIVE = {"type": "object", "properties": {}, "required": []}


def _op_task(title: str, description: str, *, required: bool, responsible: str,
             operation_id: str, depends_on: list[str] | None = None) -> RunbookTaskSpec:
    """Helper: an Operation-first task with a permissive input schema."""
    return RunbookTaskSpec(
        title=title, description=description, required=required,
        responsible=responsible, input_schema=dict(_PERMISSIVE),
        operation_id=operation_id, depends_on=depends_on or [],
    )


# --- hotfix: urgent fix pipeline with a HIGH-risk deploy step ----------------
_HOTFIX = RunbookSpec(
    id="hotfix",
    version="1.0.0",
    name="Hotfix pipeline (branch -> fix -> gates -> deploy -> verify/rollback)",
    description=(
        "Pipeline de correção urgente: valida saúde, cria branch, aplica o fix, roda "
        "testes/lint/typecheck, abre PR, checa o gate, faz merge e deploy (write/HIGH "
        "-> exige confirmação individual N2 via catálogo) e verifica pós-deploy. "
        "'rollback' é a ação compensatória do caminho de falha do 'verify' — o DAG não "
        "modela condicionais, então é o passo do operador/failure-path."
    ),
    responsible_profile="devops",
    tasks={
        "precheck_health": _op_task(
            "Pre-check service health",
            "Confirma que o serviço-alvo está saudável antes de iniciar o hotfix.",
            required=True, responsible="devops", operation_id="infra.check_health",
            depends_on=[]),
        "create_branch": _op_task(
            "Create hotfix branch",
            "Cria a branch de hotfix a partir da base.",
            required=True, responsible="devops", operation_id="delivery.create_branch",
            depends_on=["precheck_health"]),
        "commit_fix": _op_task(
            "Commit the fix",
            "Aplica e commita os arquivos do fix na branch de hotfix.",
            required=True, responsible="devops", operation_id="delivery.commit_files",
            depends_on=["create_branch"]),
        "run_tests": _op_task(
            "Run unit tests",
            "Roda a suite de testes unitários sobre o fix.",
            required=True, responsible="qa-engineer", operation_id="testing.run_unit_tests",
            depends_on=["commit_fix"]),
        "run_lint": _op_task(
            "Run linter",
            "Roda o linter sobre o fix.",
            required=True, responsible="qa-engineer", operation_id="testing.run_linter",
            depends_on=["commit_fix"]),
        "run_typecheck": _op_task(
            "Run type check",
            "Roda o type-checker sobre o fix.",
            required=True, responsible="qa-engineer", operation_id="testing.run_type_check",
            depends_on=["commit_fix"]),
        "open_pr": _op_task(
            "Open pull request",
            "Abre o PR do hotfix após os checks locais.",
            required=True, responsible="devops", operation_id="delivery.create_pr",
            depends_on=["run_tests", "run_lint", "run_typecheck"]),
        "check_gate": _op_task(
            "Check quality gate",
            "Consulta o status do gate de qualidade do PR.",
            required=True, responsible="devops", operation_id="delivery.get_gate_status",
            depends_on=["open_pr"]),
        "merge_pr": _op_task(
            "Merge pull request",
            "Faz o merge do PR após o gate verde.",
            required=True, responsible="devops", operation_id="delivery.merge_pr",
            depends_on=["check_gate"]),
        "deploy": _op_task(
            "Deploy the hotfix (HIGH RISK)",
            "Faz o deploy do hotfix (write/high -> N2 via catálogo).",
            required=True, responsible="devops", operation_id="delivery.deploy",
            depends_on=["merge_pr"]),
        "verify": _op_task(
            "Post-deploy verification",
            "Verifica a saúde do serviço após o deploy.",
            required=False, responsible="devops", operation_id="infra.check_health",
            depends_on=["deploy"]),
        "rollback": _op_task(
            "Rollback (failure-path)",
            "Ação compensatória caso o 'verify' falhe. O DAG não modela condicionais: "
            "este é o passo do operador/failure-path, executado apenas sob falha.",
            required=False, responsible="devops", operation_id="delivery.rollback",
            depends_on=["deploy"]),
    },
)


# --- architecture_review: validate against Governance/Knowledge/architecture -
_ARCHITECTURE_REVIEW = RunbookSpec(
    id="architecture_review",
    version="1.0.0",
    name="Architecture review (metadata -> graph -> layer/scope -> audit)",
    description=(
        "Revisão de arquitetura de um serviço: metadados e ownership, dependências e "
        "consumidores, grafo do ecossistema, política de camada e escopo, conhecimento "
        "de governança, validação de contrato de lib e blueprint de solução, encerrando "
        "com auditoria de compliance e veredicto. Recuperação estruturada de ADR NÃO "
        "está coberta (gap — ver docs/catalog-gaps/runbooks-wave1.md)."
    ),
    responsible_profile="architecture",
    tasks={
        "get_metadata": _op_task(
            "Get service metadata",
            "Recupera os metadados do serviço em revisão.",
            required=True, responsible="architecture",
            operation_id="governance.get_service_metadata", depends_on=[]),
        "get_ownership": _op_task(
            "Get service ownership",
            "Recupera o ownership do serviço.",
            required=True, responsible="architecture",
            operation_id="governance.get_service_ownership", depends_on=["get_metadata"]),
        "map_dependencies": _op_task(
            "Map dependencies",
            "Mapeia as dependências do serviço.",
            required=True, responsible="architecture",
            operation_id="governance.find_dependencies_of", depends_on=["get_metadata"]),
        "map_consumers": _op_task(
            "Map consumers",
            "Mapeia os consumidores do serviço.",
            required=False, responsible="architecture",
            operation_id="governance.find_consumers_of", depends_on=["get_metadata"]),
        "query_graph": _op_task(
            "Query ecosystem graph",
            "Consulta o grafo do ecossistema em torno do serviço.",
            required=True, responsible="architecture",
            operation_id="governance.query_ecosystem_graph", depends_on=["get_metadata"]),
        "check_layer": _op_task(
            "Check layer policy",
            "Verifica a política de camada aplicável ao serviço.",
            required=True, responsible="architecture",
            operation_id="governance.get_layer_policy", depends_on=["query_graph"]),
        "check_scope": _op_task(
            "Check scope",
            "Verifica o escopo permitido do serviço.",
            required=True, responsible="architecture",
            operation_id="governance.check_scope", depends_on=["check_layer"]),
        "search_knowledge": _op_task(
            "Search governance knowledge",
            "Consulta a base de conhecimento de governança.",
            required=False, responsible="architecture",
            operation_id="governance.search_governance_knowledge", depends_on=["get_metadata"]),
        "validate_contract": _op_task(
            "Validate lib change",
            "Valida a mudança de contrato de biblioteca contra as dependências.",
            required=False, responsible="architecture",
            operation_id="governance.validate_lib_change", depends_on=["map_dependencies"]),
        "generate_blueprint": _op_task(
            "Generate solution blueprint",
            "Gera o blueprint da solução a partir do grafo.",
            required=False, responsible="architecture",
            operation_id="architecture.generate_solution_blueprint", depends_on=["query_graph"]),
        "run_compliance": _op_task(
            "Run compliance audit",
            "Executa a auditoria de compliance após verificar escopo.",
            required=True, responsible="architecture",
            operation_id="governance.run_audit", depends_on=["check_scope"]),
        "record_verdict": _op_task(
            "Record audit verdict",
            "Registra o veredicto (aprovação) da auditoria.",
            required=False, responsible="architecture",
            operation_id="governance.submit_audit_approval", depends_on=["run_compliance"]),
    },
)


# --- incident: detect -> diagnose -> mitigate -> verify ----------------------
_INCIDENT = RunbookSpec(
    id="incident",
    version="1.0.0",
    name="Incident response (detect -> diagnose -> mitigate -> verify)",
    description=(
        "Resposta a incidente: detecta (saúde da plataforma, serviço afetado), "
        "diagnostica (logs, deploys/promoções recentes), mitiga (rollback/bloqueio/"
        "reload) e verifica a recuperação, capturando artefato e post-mortem. "
        "Ciclo de vida do incidente (declare/update/resolve) e paging/comunicação são "
        "GAPS (ver docs/catalog-gaps/runbooks-wave1.md) e foram omitidos — não se "
        "vincula um Tool diretamente."
    ),
    responsible_profile="devops",
    tasks={
        "check_platform_health": _op_task(
            "Check platform health",
            "Verifica a saúde de toda a plataforma para detectar o incidente.",
            required=True, responsible="devops",
            operation_id="infra.check_all_health", depends_on=[]),
        "identify_service": _op_task(
            "Identify affected service",
            "Identifica o serviço afetado a partir do status.",
            required=True, responsible="devops",
            operation_id="infra.service_status", depends_on=["check_platform_health"]),
        "fetch_logs": _op_task(
            "Fetch service logs",
            "Coleta os logs do serviço afetado.",
            required=True, responsible="devops",
            operation_id="infra.get_service_logs", depends_on=["identify_service"]),
        "search_logs": _op_task(
            "Search logs",
            "Busca padrões relevantes nos logs.",
            required=False, responsible="devops",
            operation_id="infra.search_logs", depends_on=["identify_service"]),
        "recent_deploys": _op_task(
            "Check recent deploys",
            "Consulta o status dos deploys recentes do serviço.",
            required=True, responsible="devops",
            operation_id="delivery.get_deploy_status", depends_on=["identify_service"]),
        "promotion_history": _op_task(
            "Check promotion history",
            "Consulta o histórico de promoções do serviço.",
            required=False, responsible="devops",
            operation_id="delivery.get_promotion_history", depends_on=["identify_service"]),
        "rollback": _op_task(
            "Rollback (mitigation)",
            "Mitigação: reverte o deploy suspeito (write/high -> N2 via catálogo).",
            required=False, responsible="devops",
            operation_id="delivery.rollback", depends_on=["recent_deploys"]),
        "block_service": _op_task(
            "Block service (mitigation)",
            "Mitigação: bloqueia o serviço para conter o impacto.",
            required=False, responsible="devops",
            operation_id="delivery.block_service", depends_on=["identify_service"]),
        "reload_service": _op_task(
            "Reload service (mitigation)",
            "Mitigação: recarrega o serviço afetado.",
            required=False, responsible="devops",
            operation_id="infra.reload_service", depends_on=["identify_service"]),
        "verify_recovery": _op_task(
            "Verify recovery",
            "Verifica a recuperação do serviço após a mitigação.",
            required=False, responsible="devops",
            operation_id="infra.check_health", depends_on=["rollback", "reload_service"]),
        "capture_artifact": _op_task(
            "Capture artifact",
            "Registra um artefato do incidente na sessão da plataforma.",
            required=False, responsible="devops",
            operation_id="platform.add_artifact", depends_on=["verify_recovery"]),
        "postmortem": _op_task(
            "Generate post-mortem doc",
            "Gera o documento de post-mortem do incidente.",
            required=False, responsible="devops",
            operation_id="documentation.generate_doc", depends_on=["capture_artifact"]),
    },
)


RUNBOOK_CATALOG: dict[str, RunbookSpec] = {
    _HEALTH_TO_REPORT.id: _HEALTH_TO_REPORT,
    _DEPLOY_SERVICE.id: _DEPLOY_SERVICE,
    _PLATFORM_HEALTH.id: _PLATFORM_HEALTH,
    _HOTFIX.id: _HOTFIX,
    _ARCHITECTURE_REVIEW.id: _ARCHITECTURE_REVIEW,
    _INCIDENT.id: _INCIDENT,
}


def get_runbook(runbook_id: str) -> RunbookSpec:
    """Return the runbook by id, or raise ``ValueError`` listing the available ids."""
    runbook = RUNBOOK_CATALOG.get(runbook_id)
    if runbook is None:
        raise ValueError(
            f"Runbook {runbook_id!r} does not exist. Available: {list(RUNBOOK_CATALOG)}"
        )
    return runbook
