"""Servidor MCP infra — registra as 15 tools (Phase 1 read-only + Phase 2 allocator SQLite+terraform+SSH+queue) e expõe via stdio."""

from __future__ import annotations

import os

import asyncio
import json
from typing import Any

from fastapi import FastAPI
from mcp.server import Server
from mcp.types import TextContent, Tool

from ..config.settings import Settings, get_settings
from ..db.allocator_store import AllocatorPolicy, AllocatorStore
from ..db.provisioner import ImmediateProvisioner, TerraformProvisioner
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
from ..utils.logger import get_logger, setup_logging

_log = get_logger(__name__)


# ---------------------------------------------------------------------- #
# Schemas                                                                 #
# ---------------------------------------------------------------------- #
_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "terraform_validate": {
        "description": (
            "Roda `terraform validate -json` no diretório. Retorna diagnostics "
            "estruturados (erros + warnings). Read-only — não modifica state nem "
            "consulta provider remoto."
        ),
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
        "schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    "query_capacity": {
        "description": (
            "Planejamento sem efeito: 'haveria slot para essa spec sem violar "
            "hard stops?' Retorna can_satisfy_now + by_existing_vm/would_provision "
            "+ blocked_by quando recusado."
        ),
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


# ---------------------------------------------------------------------- #
# Server                                                                  #
# ---------------------------------------------------------------------- #
def _build_http_app() -> FastAPI:
    app = FastAPI(title="Infra API", version="0.1.0", docs_url="/docs")

    @app.get("/v1/health")
    def health() -> dict:
        return {"status": "ok", "service": "infra-mcp"}

    return app


def build_server() -> tuple[Any, ...]:
    settings = get_settings()
    http_app = _build_http_app()
    setup_logging(level=settings.log_level, fmt=settings.log_format)

    # Phase 2c: provisioner real (terraform) se INFRA_TF_MODULES_ROOT estiver configurado.
    # Phase 2f: backend remoto via INFRA_TF_BACKEND_TYPE + INFRA_TF_BACKEND_CONFIG_JSON.
    if settings.tf_modules_root is not None:
        backend_config: dict[str, str] = {}
        if settings.tf_backend_config_json:
            import json as _json  # noqa: PLC0415
            try:
                backend_config = _json.loads(settings.tf_backend_config_json)
            except Exception:  # noqa: BLE001
                _log.warning(
                    "backend_config_json_parse_error",
                    extra={"extras": {"raw": settings.tf_backend_config_json[:200]}},
                )
        provisioner = TerraformProvisioner(
            terraform_bin=settings.terraform_bin,
            backend_type=settings.tf_backend_type,
            backend_config=backend_config,
            infracost_bin=settings.infracost_bin,
            cost_cap_usd_month=settings.cost_cap_usd_month,
        )
        _log.info(
            "provisioner_terraform",
            extra={"extras": {
                "tf_modules_root": str(settings.tf_modules_root),
                "backend_type": settings.tf_backend_type,
                "cost_cap_usd_month": settings.cost_cap_usd_month,
            }},
        )
    else:
        provisioner = ImmediateProvisioner()
        _log.info("provisioner_immediate", extra={"extras": {}})

    # AllocatorStore PostgreSQL-backed (Phase 2b+ → PostgreSQL migration).
    # Phase 2f: lease_secret para cifrar chaves SSH por VM.
    allocator = AllocatorStore(
        settings=settings,
        policy=AllocatorPolicy(),
        provisioner=provisioner,
        lease_secret=settings.lease_secret,
    )
    _log.info(
        "allocator_ready",
        extra={"extras": {
            "pg_host": settings.pg_host,
            "pg_db": settings.pg_db,
            "tf_modules_root": str(settings.tf_modules_root) if settings.tf_modules_root else None,
            "provisioner": type(provisioner).__name__,
            "max_cost_usd_per_hour": allocator.policy.max_cost_usd_per_hour,
            "max_active_leases_per_owner": allocator.policy.max_active_leases_per_owner,
            "max_lease_duration_min": allocator.policy.max_lease_duration_min,
        }},
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
        args = arguments or {}
        _log.info(
            "tool_called",
            extra={"extras": {"tool": name, "args_keys": sorted(args.keys())}},
        )
        try:
            payload = _dispatch(name, args, settings, allocator)
        except KeyError:
            payload = {"error": "unknown_tool", "tool": name}
            _log.error("unknown_tool", extra={"extras": {"tool": name}})
        except Exception as e:  # noqa: BLE001
            payload = {"error": "internal_error", "details": str(e), "tool": name}
            _log.exception("tool_internal_error", extra={"extras": {"tool": name}})

        return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, indent=2))]

    @http_app.get("/mcp/tools/list")
    async def http_list_tools() -> dict:
        tools = await list_tools()
        return {"result": {"tools": [t.model_dump(exclude_none=True) for t in tools]}}

    @http_app.post("/mcp/tools/call")
    async def http_call_tool(body: dict) -> dict:
        params = body.get("params", body)
        result = await call_tool(params.get("name", ""), params.get("arguments", {}))
        return {"result": {"content": [r.model_dump(exclude_none=True) for r in result]}}

    return server, settings, allocator, http_app


def _dispatch(
    name: str,
    args: dict[str, Any],
    settings: Settings,
    allocator: AllocatorStore,
) -> dict:
    if name == "terraform_validate":
        return terraform_validate(settings, path=args.get("path"))
    if name == "terraform_fmt_check":
        return terraform_fmt_check(
            settings, path=args.get("path"), recursive=args.get("recursive", True)
        )
    if name == "terraform_plan":
        return terraform_plan(
            settings,
            path=args.get("path"),
            out_file=args.get("out_file"),
            var_file=args.get("var_file"),
        )
    if name == "terraform_show_plan":
        return terraform_show_plan(
            settings, plan_path=args.get("plan_path"), path=args.get("path")
        )
    if name == "policy_scan_checkov":
        return policy_scan_checkov(
            settings,
            path=args.get("path"),
            framework=args.get("framework", "terraform"),
            skip_checks=args.get("skip_checks"),
        )
    if name == "cost_estimate_infracost":
        return cost_estimate_infracost(
            settings,
            plan_path=args.get("plan_path"),
            delta_usd_threshold=args.get("delta_usd_threshold"),
            delta_pct_threshold=args.get("delta_pct_threshold"),
        )
    # ---- Phase 2a — VM allocator ----
    if name == "request_vm":
        return request_vm(
            allocator,
            spec=args.get("spec"),
            duration_min=args.get("duration_min"),
            owner=args.get("owner"),
            exclusive=args.get("exclusive", False),
            priority=args.get("priority", "low"),
            purpose=args.get("purpose"),
            human_approved=args.get("human_approved", False),
        )
    if name == "get_lease":
        return get_lease(allocator, lease_id=args.get("lease_id"))
    if name == "release_lease":
        return release_lease(allocator, lease_id=args.get("lease_id"), by=args.get("by"))
    if name == "extend_lease":
        return extend_lease(
            allocator,
            lease_id=args.get("lease_id"),
            additional_min=args.get("additional_min"),
        )
    if name == "list_my_leases":
        return list_my_leases(
            allocator, owner=args.get("owner"), status=args.get("status")
        )
    if name == "list_pool":
        return list_pool(allocator)
    if name == "query_capacity":
        return query_capacity(allocator, spec=args.get("spec"), owner=args.get("owner"))
    if name == "get_lease_ssh_key":
        return get_lease_ssh_key(
            allocator,
            lease_id=args.get("lease_id"),
            owner=args.get("owner"),
        )
    # ---- Phase 2h — priority queue ----
    if name == "cancel_queued_request":
        return cancel_queued_request(
            allocator,
            request_id=args.get("request_id"),
            by=args.get("by"),
        )
    raise KeyError(name)


async def _run() -> None:
    import uvicorn
    from mcp.server.stdio import stdio_server

    server, *rest = build_server()
    http_app = rest[-1]

    cfg = uvicorn.Config(
        http_app, host="0.0.0.0", port=int(os.getenv("MCP_PORT", "7100")),
        log_level="warning", access_log=False,
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
    asyncio.run(_run())


if __name__ == "__main__":
    main()
