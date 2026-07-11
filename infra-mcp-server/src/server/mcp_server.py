"""Servidor MCP do infra — sidecar kind=mcp_http, GATEWAY-READY (Model C).

Reescrito para o padrão canônico do platform-service-template (v2.0). Implementa o
contrato de integração com o MCP Gateway central (platform-mcp-gateway):
  - docs/standards/STD-MCP-001-mcp-gateway-integration-contract.md  (CI-1..CI-11)
  - docs/standards/STD-SEC-006-token-model-c-inner-token.md          (inner token / audiência)

Pontos gateway-ready:
  1. /mcp/tools/list emite, por tool, inputSchema type=object + capability +
     required_scope + resource_type + data_domain (o gateway NÃO deriva por nome).
  2. /mcp/tools/call re-verifica o **inner Twin Token** (aud=mcp:infra-mcp) via
     JWKS do platform-admin, na PRÓPRIA audiência (defense in depth — CI-4/CI-5). O
     inner token chega em params._meta.twin_token.
  3. tenant_id vem SEMPRE dos claims do token verificado — nunca de argumento do
     cliente (SEC-035 / INV-3). As tools de allocator são tenant-scoped (o store abre a
     sessão do tenant resolvida dos claims); as tools compute-only (terraform/checkov/
     infracost) não tocam dados do tenant.
  4. _EXEMPT_TOOLS (tokenless) e _EXCLUDE_TOOLS (denylist fail-safe).
  5. /docs desabilitado (DOCS_ENABLED=false — HTTP-01).

Transporte: stdio (primário, MCP) + sidecar HTTP (:MCP_PORT, default 7100):
  GET  /v1/health        — liveness (health_path do registro, sem token)
  GET  /mcp/tools/list   — catálogo governado (com metadados de policy)
  POST /mcp/tools/call   — execução (inner token obrigatório, exceto _EXEMPT_TOOLS)

NOTA: infra-mcp NÃO fala com um Trinity backend/REST. As 6 tools compute-only
(terraform/checkov/infracost) operam sobre CLIs locais (rodam em thread via
``asyncio.to_thread``). As 9 tools do **allocator** persistem 100% sobre o ORM canônico,
**tenant-scoped e dual-db**: por-request o server resolve o pool do tenant (credencial-zero
via ``for_tenant``), garante o schema (1x/tenant) e constrói um ``AllocatorStore`` ligado à
``TenantSession``. O provisioner (terraform/mock) e o segredo Fernet vivem no nível de
processo. stdio é gateway-only (recusa fail-closed): a execução real entra pelo sidecar HTTP.
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, cast

import jwt  # PyJWT — verificação RS256 do inner token via JWKS
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from mcp.server import Server
from mcp.types import TextContent, Tool
from platform_database import close_tenant_pools
from platform_database.orm import configure, for_tenant
from platform_database.orm.dialects import dialect_for_pool
from platform_database.tenant_resolver import get_pool_for_tenant

from ..config.logging import configure_logging
from ..config.secrets import load_secret
from ..config.settings import Settings, get_settings
from ..db.allocator_store import AllocatorPolicy, AllocatorStore
from ..db.provisioner import ImmediateProvisioner, Provisioner, TerraformProvisioner
from ..db.schema import ensure_schema
from ..tools import (
    cancel_queued_request,
    cost_estimate_infracost,
    extend_lease,
    get_lease,
    get_lease_ssh_key,
    list_my_leases,
    list_pool,
    policy_scan_checkov,
    query_capacity,
    release_lease,
    request_vm,
    terraform_fmt_check,
    terraform_plan,
    terraform_show_plan,
    terraform_validate,
)
from ..utils.logger import get_logger

_log = get_logger(__name__)


# ── Tool Schemas + Policy metadata (STD-MCP-001 CI-2) ─────────────────────────
# Cada tool declara, além de description/schema, os 4 campos de política:
#   capability     — id estável <namespace>.<tool> (não derivar por nome no gateway)
#   required_scope — escopo de execução no formato dominio:tipo:acao (least-privilege)
#   resource_type  — tipo de recurso tocado
#   data_domain    — domínio de dado (governa HITL floor / classificação LGPD)
# inputSchema MUST ser type=object com properties (senão a validação no front-door
# é fail-open). Mutação → verbo :write; consulta/plan/scan → :read.
# ─────────────────────────────────────────────────────────────────────────────
_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "terraform_validate": {
        "description": (
            "Roda `terraform validate -json` no diretório. Retorna diagnostics "
            "estruturados (erros + warnings). Read-only — não modifica state nem "
            "consulta provider remoto."
        ),
        "capability": "infra-mcp.terraform_validate",
        "required_scope": "infra-mcp:terraform:read",
        "resource_type": "terraform",
        "data_domain": "infrastructure",
        "schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Diretório do módulo terraform. Default: INFRA_TERRAFORM_ROOT.",
                },
            },
            "additionalProperties": False,
        },
    },
    "terraform_fmt_check": {
        "description": (
            "Roda `terraform fmt -check -diff` (recursivo). Não modifica arquivos. "
            "Retorna lista de arquivos não-formatados + diff."
        ),
        "capability": "infra-mcp.terraform_fmt_check",
        "required_scope": "infra-mcp:terraform:read",
        "resource_type": "terraform",
        "data_domain": "infrastructure",
        "schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "recursive": {"type": "boolean", "default": True},
            },
            "additionalProperties": False,
        },
    },
    "terraform_plan": {
        "description": (
            "Roda `terraform plan -no-color -out=<file> -detailed-exitcode`. Retorna "
            "summary (add/change/destroy) + path do .tfplan binário (input para "
            "infracost e show-plan). Pode chamar provider remoto (rate limit)."
        ),
        "capability": "infra-mcp.terraform_plan",
        "required_scope": "infra-mcp:terraform:read",
        "resource_type": "terraform",
        "data_domain": "infrastructure",
        "schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "out_file": {
                    "type": "string",
                    "description": "Caminho do .tfplan a gravar. Default: <path>/.infra-mcp.tfplan",
                },
                "var_file": {
                    "type": "string",
                    "description": "-var-file=... opcional",
                },
            },
            "additionalProperties": False,
        },
    },
    "terraform_show_plan": {
        "description": (
            "Devolve o terraform plan em JSON estruturado para análise programática "
            "(via `terraform show -json <plan>`). Use depois de terraform_plan."
        ),
        "capability": "infra-mcp.terraform_show_plan",
        "required_scope": "infra-mcp:terraform:read",
        "resource_type": "terraform",
        "data_domain": "infrastructure",
        "schema": {
            "type": "object",
            "properties": {
                "plan_path": {"type": "string"},
                "path": {"type": "string"},
            },
            "required": ["plan_path"],
            "additionalProperties": False,
        },
    },
    "policy_scan_checkov": {
        "description": (
            "Roda checkov sobre código terraform (ou outro framework) e devolve "
            "findings agrupados por severity. Marca hard_stop=True se houver "
            "qualquer HIGH ou CRITICAL (cicd-deploy.md §4 #3 do ai-governance)."
        ),
        "capability": "infra-mcp.policy_scan_checkov",
        "required_scope": "infra-mcp:policy:read",
        "resource_type": "policy",
        "data_domain": "security",
        "schema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "framework": {
                    "type": "string",
                    "enum": ["terraform", "terraform_plan", "kubernetes", "dockerfile", "all"],
                    "default": "terraform",
                },
                "skip_checks": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Lista de check_ids para ignorar (ex.: CKV_AZURE_42)",
                },
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
    "cost_estimate_infracost": {
        "description": (
            "Roda `infracost diff --path <tfplan> --format json` e devolve delta "
            "mensal de custo. Marca hard_stop=True se delta > threshold (default "
            "+US$ 100/mês ou +20%, conforme cicd-deploy.md §4 #4)."
        ),
        "capability": "infra-mcp.cost_estimate_infracost",
        "required_scope": "infra-mcp:cost:read",
        "resource_type": "cost",
        "data_domain": "finops",
        "schema": {
            "type": "object",
            "properties": {
                "plan_path": {"type": "string"},
                "delta_usd_threshold": {"type": "number", "default": 100.0},
                "delta_pct_threshold": {"type": "number", "default": 20.0},
            },
            "required": ["plan_path"],
            "additionalProperties": False,
        },
    },
    # ----------------------- Phase 2a — VM allocator ----------------------- #
    "request_vm": {
        "description": (
            "Solicita capacidade ao allocator. Servidor decide entre lease em "
            "VM existente (compartilhamento), provisão de nova, fila ou denial. "
            "Spec restrita à whitelist (cpu-small/medium/large). gpu-a100 e "
            "high-mem exigem `human_approved=True` registrado out-of-band. "
            "Phase 2c: provisão via terraform real (INFRA_TF_MODULES_ROOT). "
            "Lease inicia PENDING e vai ACTIVE quando VM fica READY. "
            "Use get_lease(lease_id) para verificar connection_hint (endpoint SSH)."
        ),
        "capability": "infra-mcp.request_vm",
        "required_scope": "infra-mcp:lease:write",
        "resource_type": "lease",
        "data_domain": "infrastructure",
        "schema": {
            "type": "object",
            "properties": {
                "spec": {
                    "type": "string",
                    "enum": ["cpu-small", "cpu-medium", "cpu-large", "high-mem", "gpu-a100"],
                },
                "duration_min": {"type": "integer", "minimum": 1, "maximum": 4320},
                "owner": {"type": "string", "description": "Identificador do agente."},
                "exclusive": {"type": "boolean", "default": False},
                "priority": {"type": "string", "enum": ["low", "medium", "high"], "default": "low"},
                "purpose": {"type": "string", "description": "Descrição curta para audit."},
                "human_approved": {"type": "boolean", "default": False},
            },
            "required": ["spec", "duration_min", "owner"],
            "additionalProperties": False,
        },
    },
    "get_lease": {
        "description": "Estado atual de um lease (PENDING/ACTIVE/RELEASED/EXPIRED) + connection_hint.",
        "capability": "infra-mcp.get_lease",
        "required_scope": "infra-mcp:lease:read",
        "resource_type": "lease",
        "data_domain": "infrastructure",
        "schema": {
            "type": "object",
            "properties": {"lease_id": {"type": "string"}},
            "required": ["lease_id"],
            "additionalProperties": False,
        },
    },
    "release_lease": {
        "description": (
            "Libera um lease. Idempotente — segundo release no mesmo lease é no-op. "
            "Quando última lease de uma VM é liberada, VM é terminada (Phase 2a)."
        ),
        "capability": "infra-mcp.release_lease",
        "required_scope": "infra-mcp:lease:write",
        "resource_type": "lease",
        "data_domain": "infrastructure",
        "schema": {
            "type": "object",
            "properties": {
                "lease_id": {"type": "string"},
                "by": {"type": "string", "description": "Quem chamou release (audit)."},
            },
            "required": ["lease_id"],
            "additionalProperties": False,
        },
    },
    "extend_lease": {
        "description": (
            "Estende a validade de um lease ativo. Cap absoluto: 24h totais e "
            "no máximo 3 extensões por lease."
        ),
        "capability": "infra-mcp.extend_lease",
        "required_scope": "infra-mcp:lease:write",
        "resource_type": "lease",
        "data_domain": "infrastructure",
        "schema": {
            "type": "object",
            "properties": {
                "lease_id": {"type": "string"},
                "additional_min": {"type": "integer", "minimum": 1, "maximum": 720},
            },
            "required": ["lease_id", "additional_min"],
            "additionalProperties": False,
        },
    },
    "list_my_leases": {
        "description": "Lista leases do owner (filtro opcional por status).",
        "capability": "infra-mcp.list_my_leases",
        "required_scope": "infra-mcp:lease:read",
        "resource_type": "lease",
        "data_domain": "infrastructure",
        "schema": {
            "type": "object",
            "properties": {
                "owner": {"type": "string"},
                "status": {
                    "type": "string",
                    "enum": ["PENDING", "ACTIVE", "RELEASED", "EXPIRED"],
                },
            },
            "required": ["owner"],
            "additionalProperties": False,
        },
    },
    "list_pool": {
        "description": (
            "Snapshot do pool: VMs ativas + active_lease_count + custo/hora total. "
            "Visibilidade administrativa."
        ),
        "capability": "infra-mcp.list_pool",
        "required_scope": "infra-mcp:pool:read",
        "resource_type": "pool",
        "data_domain": "infrastructure",
        "schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "query_capacity": {
        "description": (
            "Planejamento sem efeito: 'haveria slot para essa spec sem violar "
            "hard stops?' Retorna can_satisfy_now + by_existing_vm/would_provision "
            "+ blocked_by quando recusado."
        ),
        "capability": "infra-mcp.query_capacity",
        "required_scope": "infra-mcp:capacity:read",
        "resource_type": "capacity",
        "data_domain": "infrastructure",
        "schema": {
            "type": "object",
            "properties": {
                "spec": {
                    "type": "string",
                    "enum": ["cpu-small", "cpu-medium", "cpu-large", "high-mem", "gpu-a100"],
                },
                "owner": {"type": "string", "description": "Para checar quota por agente."},
            },
            "required": ["spec"],
            "additionalProperties": False,
        },
    },
    # ----------------------- Phase 2f — SSH key per-VM --------------------- #
    "get_lease_ssh_key": {
        "description": (
            "Retorna a chave privada Ed25519 (PEM) para conectar via SSH à VM do lease. "
            "Requer lease em status ACTIVE. owner deve ser o titular do lease. "
            "A chave é deletada quando o lease é liberado — salve localmente antes do release. "
            "Uso: salvar em arquivo com chmod 600 e usar com ssh -i key.pem ubuntu@<host>."
        ),
        "capability": "infra-mcp.get_lease_ssh_key",
        "required_scope": "infra-mcp:secret:write",
        "resource_type": "secret",
        "data_domain": "secrets",
        "schema": {
            "type": "object",
            "properties": {
                "lease_id": {"type": "string"},
                "owner": {
                    "type": "string",
                    "description": "Identificador do agente titular do lease (autenticação).",
                },
            },
            "required": ["lease_id", "owner"],
            "additionalProperties": False,
        },
    },
    # ----------------------- Phase 2h — priority queue -------------------- #
    "cancel_queued_request": {
        "description": (
            "Cancela um request WAITING na fila de provisão de VM. "
            "Use quando o agente não precisa mais da VM aguardada (job cancelado, timeout). "
            "request_id foi retornado por request_vm quando outcome=QUEUED. "
            "Retorna erro se request_id não existe ou já foi FULFILLED/CANCELLED."
        ),
        "capability": "infra-mcp.cancel_queued_request",
        "required_scope": "infra-mcp:queue:write",
        "resource_type": "queue",
        "data_domain": "infrastructure",
        "schema": {
            "type": "object",
            "properties": {
                "request_id": {
                    "type": "string",
                    "description": "ID retornado por request_vm (campo request_id quando outcome=QUEUED).",
                },
                "by": {
                    "type": "string",
                    "description": "Identificador de quem está cancelando (audit).",
                },
            },
            "required": ["request_id"],
            "additionalProperties": False,
        },
    },
}

# Tools encaminhadas SEM inner token (CI-7 exempt_tools — só tokenless). infra-mcp
# não expõe tool pública/tokenless: TODA execução exige inner token válido.
_EXEMPT_TOOLS: frozenset[str] = frozenset()
# Denylist fail-safe: tools que retornam segredos NUNCA saem pelo gateway (CI-7).
# get_lease_ssh_key expõe chave privada Ed25519 — se o gateway precisar bloqueá-la,
# adicione aqui (mantido vazio: a exposição é governada por required_scope :write).
_EXCLUDE_TOOLS: frozenset[str] = frozenset()

# Campos de policy repassados no /mcp/tools/list (o gateway lê estes campos).
_POLICY_FIELDS = ("capability", "required_scope", "resource_type", "data_domain")


# ── Verificação do inner Twin Token (STD-SEC-006 / CI-4/CI-5) ─────────────────


def _verify_inner_token(twin_token: str, settings: Settings) -> dict[str, Any]:
    """Re-verifica o inner Twin Token na PRÓPRIA audiência (mcp:infra-mcp).

    O gateway já verificou o front token; o backend é 'one more verified client'
    (defense in depth). RS256 via JWKS do platform-admin; audiência exata; jti
    obrigatório. Levanta em qualquer falha (fail-closed).
    """
    if not settings.mcp_twin_audience or not settings.url_admin_twin_jwks:
        raise PermissionError(
            "integração com o gateway não configurada: defina MCP_TWIN_AUDIENCE "
            "(mcp:infra-mcp) e URL_ADMIN_TWIN_JWKS (ver STD-SEC-006 / IT-006)."
        )
    signing_key = jwt.PyJWKClient(settings.url_admin_twin_jwks).get_signing_key_from_jwt(twin_token)
    return jwt.decode(
        twin_token,
        signing_key.key,
        algorithms=["RS256"],  # RS256 exclusivo (STD-SEC-001)
        audience=settings.mcp_twin_audience,  # a falha de integração nº 1
        options={"require": ["exp", "aud", "jti"]},  # sem jti → rejeita (JTI_REQUIRED)
    )


# ── Dispatchers (compute-only sync × allocator async tenant-scoped) ───────────

# As 9 tools do allocator são async e tenant-scoped (recebem um AllocatorStore ligado à
# TenantSession do request). As 6 compute-only são sync (rodam CLIs) e recebem só settings.
_ALLOCATOR_TOOLS: frozenset[str] = frozenset(
    {
        "request_vm",
        "get_lease",
        "release_lease",
        "extend_lease",
        "list_my_leases",
        "list_pool",
        "query_capacity",
        "get_lease_ssh_key",
        "cancel_queued_request",
    }
)


def _dispatch_compute(name: str, a: dict[str, Any], settings: Settings) -> dict[str, Any]:
    """Despacha as tools compute-only (terraform/checkov/infracost) — ``tool(settings, ...)``.

    Roda em thread (``asyncio.to_thread``) para não bloquear o event loop com subprocessos.
    """
    if name == "terraform_validate":
        return terraform_validate(settings, path=a.get("path"))
    if name == "terraform_fmt_check":
        return terraform_fmt_check(settings, path=a.get("path"), recursive=a.get("recursive", True))
    if name == "terraform_plan":
        return terraform_plan(
            settings,
            path=a.get("path"),
            out_file=a.get("out_file"),
            var_file=a.get("var_file"),
        )
    if name == "terraform_show_plan":
        return terraform_show_plan(settings, plan_path=cast(str, a.get("plan_path")), path=a.get("path"))
    if name == "policy_scan_checkov":
        return policy_scan_checkov(
            settings,
            path=cast(str, a.get("path")),
            framework=a.get("framework", "terraform"),
            skip_checks=a.get("skip_checks"),
        )
    if name == "cost_estimate_infracost":
        return cost_estimate_infracost(
            settings,
            plan_path=cast(str, a.get("plan_path")),
            delta_usd_threshold=a.get("delta_usd_threshold"),
            delta_pct_threshold=a.get("delta_pct_threshold"),
        )
    raise KeyError(name)


async def _dispatch_allocator(name: str, a: dict[str, Any], store: AllocatorStore) -> dict[str, Any]:
    """Despacha as tools do allocator (async). O ``store`` já está ligado ao pool do tenant."""
    if name == "request_vm":
        return await request_vm(
            store,
            spec=cast(str, a.get("spec")),
            duration_min=cast(int, a.get("duration_min")),
            owner=cast(str, a.get("owner")),
            exclusive=a.get("exclusive", False),
            priority=a.get("priority", "low"),
            purpose=a.get("purpose"),
            human_approved=a.get("human_approved", False),
        )
    if name == "get_lease":
        return await get_lease(store, lease_id=cast(str, a.get("lease_id")))
    if name == "release_lease":
        return await release_lease(store, lease_id=cast(str, a.get("lease_id")), by=a.get("by"))
    if name == "extend_lease":
        return await extend_lease(
            store,
            lease_id=cast(str, a.get("lease_id")),
            additional_min=cast(int, a.get("additional_min")),
        )
    if name == "list_my_leases":
        return await list_my_leases(store, owner=cast(str, a.get("owner")), status=a.get("status"))
    if name == "list_pool":
        return await list_pool(store)
    if name == "query_capacity":
        return await query_capacity(store, spec=cast(str, a.get("spec")), owner=a.get("owner"))
    if name == "get_lease_ssh_key":
        return await get_lease_ssh_key(
            store, lease_id=cast(str, a.get("lease_id")), owner=cast(str, a.get("owner"))
        )
    if name == "cancel_queued_request":
        return await cancel_queued_request(store, request_id=cast(str, a.get("request_id")), by=a.get("by"))
    raise KeyError(name)


# ── Tenant plumbing (credencial-zero) ─────────────────────────────────────────
# Bootstrap de schema roda UMA vez por tenant/processo (idempotente de qualquer forma).
_SCHEMA_READY: set[str] = set()
_SCHEMA_LOCK = asyncio.Lock()


async def _ensure_tenant_schema(settings: Settings, tenant_id: str) -> None:
    """Garante as tabelas do allocator no banco do tenant (uma vez por processo). O engine é
    o do dialeto do pool resolvido — é o ponto que faz o mesmo código servir o dual-db."""
    if tenant_id in _SCHEMA_READY:
        return
    async with _SCHEMA_LOCK:
        if tenant_id in _SCHEMA_READY:
            return
        pool = await get_pool_for_tenant(settings, tenant_id, strict=True)
        await ensure_schema(pool, engine=dialect_for_pool(pool).name)
        _SCHEMA_READY.add(tenant_id)


async def _run_tool(
    name: str,
    arguments: dict[str, Any],
    settings: Settings,
    tenant_id: str,
    provisioner: Provisioner,
    fernet_key: bytes | None,
) -> dict[str, Any]:
    """Executa uma tool. Allocator → abre sessão tenant-scoped (credencial-zero) + schema;
    compute-only → roda o CLI em thread."""
    if name in _ALLOCATOR_TOOLS:
        await _ensure_tenant_schema(settings, tenant_id)
        async with for_tenant(tenant_id) as session:
            store = AllocatorStore(
                session,
                provisioner=provisioner,
                policy=AllocatorPolicy(),
                fernet_key=fernet_key,
                tf_modules_root=settings.tf_modules_root,
                provision_timeout_sec=settings.provision_timeout_sec,
            )
            return await _dispatch_allocator(name, arguments, store)
    return await asyncio.to_thread(_dispatch_compute, name, arguments, settings)


# ── HTTP Sidecar ──────────────────────────────────────────────────────────────


def _build_http_app(settings: Settings, provisioner: Provisioner, fernet_key: bytes | None) -> FastAPI:
    """Cria o sidecar HTTP (health + bridge governado /mcp/tools/*).

    Stateless quanto ao store: cada chamada de tool do allocator abre uma sessão
    tenant-scoped (credencial-zero) a partir do tenant nos claims do inner token."""
    app = FastAPI(
        title="infra-mcp API",
        version="0.1.0",
        docs_url="/docs" if settings.docs_enabled else None,  # false em todo ambiente
        redoc_url=None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )

    @app.get("/v1/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "service": "infra-mcp", "tools": len(_TOOL_SCHEMAS)}

    @app.get("/mcp/tools/list")
    def http_list_tools() -> dict:
        tools = []
        for name, meta in _TOOL_SCHEMAS.items():
            entry: dict[str, Any] = {
                "name": name,
                "description": meta["description"],
                "inputSchema": meta["schema"],
            }
            entry.update({f: meta[f] for f in _POLICY_FIELDS})
            tools.append(entry)
        return {"result": {"tools": tools}}

    @app.post("/mcp/tools/call")
    async def http_call_tool(body: dict) -> Any:
        params = body.get("params", body)
        name = params.get("name", "")
        arguments = dict(params.get("arguments", {}) or {})

        if name in _EXCLUDE_TOOLS:
            return JSONResponse(status_code=403, content={"error": "tool_excluded", "tool": name})

        # Execução (não-exempt) exige inner token válido; tenant vem dos claims.
        if name not in _EXEMPT_TOOLS:
            twin_token = (params.get("_meta") or {}).get("twin_token")
            if not twin_token:
                return JSONResponse(status_code=401, content={"error": "missing_twin_token"})
            try:
                claims = _verify_inner_token(twin_token, settings)
            except Exception as exc:  # noqa: BLE001 — fail-closed em qualquer falha de verificação
                _log.warning("inner_token_rejected", extra={"extras": {"tool": name, "detail": str(exc)}})
                return JSONResponse(status_code=401, content={"error": "invalid_twin_token"})
            tenant_id = claims.get("tenant_id")
            if not tenant_id:
                return JSONResponse(status_code=401, content={"error": "missing_tenant_scope"})
        else:  # pragma: no cover - infra-mcp não tem tools exempt
            tenant_id = None

        try:
            payload = await _run_tool(name, arguments, settings, str(tenant_id), provisioner, fernet_key)
        except KeyError:
            return JSONResponse(status_code=404, content={"error": "unknown_tool", "tool": name})
        except Exception as exc:  # noqa: BLE001 — a resposta carrega o erro
            _log.exception("tool_internal_error", extra={"extras": {"tool": name}})
            payload = {"error": "internal_error", "detail": str(exc), "tool": name}
        content = [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, indent=2))]
        return {"result": {"content": [c.model_dump(exclude_none=True) for c in content]}}

    @app.on_event("shutdown")
    async def _close_pools() -> None:
        # Fecha os pools por-tenant no shutdown (registry compartilhado da lib).
        await close_tenant_pools()

    return app


# ── Server (stdio + sidecar) ──────────────────────────────────────────────────


def _stdio_refuse(name: str) -> dict[str, Any]:
    """stdio não carrega o inner token (logo, sem tenant). infra-mcp é gateway-only: a
    execução real entra pelo sidecar HTTP (/mcp/tools/call), onde o tenant vem dos claims
    verificados. Aqui recusamos fail-closed (sem tenant)."""
    if name not in _TOOL_SCHEMAS:
        return {"error": "unknown_tool", "tool": name}
    return {
        "error": "tenant_context_required",
        "tool": name,
        "detail": (
            "infra-mcp é gateway-only; chame via o sidecar HTTP (/mcp/tools/call) com o "
            "inner Twin Token — o tenant (e o schema do allocator) vem dos claims."
        ),
    }


def _build_provisioner(settings: Settings) -> Provisioner:
    """Constrói o provisioner (terraform real ou mock) — nível de processo, stateless."""
    if settings.tf_modules_root is not None:
        backend_config: dict[str, str] = {}
        if settings.tf_backend_config_json:
            try:
                backend_config = json.loads(settings.tf_backend_config_json)
            except Exception:  # noqa: BLE001
                _log.warning(
                    "backend_config_json_parse_error",
                    extra={"extras": {"raw": settings.tf_backend_config_json[:200]}},
                )
        provisioner: Provisioner = TerraformProvisioner(
            terraform_bin=settings.terraform_bin,
            backend_type=settings.tf_backend_type,
            backend_config=backend_config,
            infracost_bin=settings.infracost_bin,
            cost_cap_usd_month=settings.cost_cap_usd_month,
        )
        _log.info(
            "provisioner_terraform",
            extra={
                "extras": {
                    "tf_modules_root": str(settings.tf_modules_root),
                    "backend_type": settings.tf_backend_type,
                    "cost_cap_usd_month": settings.cost_cap_usd_month,
                }
            },
        )
    else:
        provisioner = ImmediateProvisioner()
        _log.info("provisioner_immediate", extra={"extras": {}})
    return provisioner


def build_server() -> tuple[Any, Settings, FastAPI]:
    """Inicializa o MCP Server (stdio), settings e o sidecar HTTP.

    Não há store global: a persistência do allocator é tenant-scoped e resolvida
    por-request (credencial-zero). ``orm.configure(settings)`` registra a fonte admin
    (ADMIN_DB_*) usada para resolver o tenant → credencial do seu banco via PLATFORMS."""
    settings = get_settings()
    settings.enforce_security_invariants()
    configure_logging(settings)
    configure(settings)  # bootstrap credencial-zero (ORM-H-12): admin source p/ for_tenant

    provisioner = _build_provisioner(settings)
    # Segredo Fernet (cifra chaves SSH): Vault-fallback → env (STD-SEC-004).
    fernet_raw = load_secret("INFRA_LEASE_SECRET", env_fallback=settings.lease_secret)
    fernet_key = fernet_raw.encode() if fernet_raw else None

    http_app = _build_http_app(settings, provisioner, fernet_key)
    _log.info(
        "infra_mcp_ready",
        extra={"extras": {"tools": len(_TOOL_SCHEMAS), "engine": settings.DB_ENGINE}},
    )

    server: Server = Server("infra-mcp-server")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(name=name, description=meta["description"], inputSchema=meta["schema"])
            for name, meta in _TOOL_SCHEMAS.items()
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict[str, Any] | None) -> list[TextContent]:
        payload = _stdio_refuse(name)
        return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, indent=2))]

    return server, settings, http_app


# ── Entry point ───────────────────────────────────────────────────────────────


async def _run() -> None:
    import uvicorn
    from mcp.server.stdio import stdio_server

    server, settings, http_app = build_server()
    cfg = uvicorn.Config(
        http_app,
        host="0.0.0.0",  # noqa: S104 — bind interno do container; ingress só via gateway (INV-1)
        port=settings.mcp_port,
        log_level="warning",
        access_log=False,
    )
    server_http = uvicorn.Server(cfg)
    try:
        async with stdio_server() as (read_stream, write_stream):
            await asyncio.gather(
                server.run(read_stream, write_stream, server.create_initialization_options()),
                server_http.serve(),
            )
    except (EOFError, BrokenPipeError):
        pass


def main() -> None:
    # MCP_HTTP_ONLY=1 → só o sidecar HTTP (uso típico atrás do gateway, sem stdio).
    if os.getenv("MCP_HTTP_ONLY", "0") == "1":
        import uvicorn

        _server, settings, http_app = build_server()
        uvicorn.run(http_app, host="0.0.0.0", port=settings.mcp_port, log_level="warning")  # noqa: S104
        return
    asyncio.run(_run())


if __name__ == "__main__":
    main()
