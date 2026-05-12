import asyncio
import json
from typing import Any

from fastapi import FastAPI
from mcp.types import TextContent, Tool

from ..config.settings import get_settings
from ..db.store import AuditStore
from ..tools.approval_tool import submit_audit_approval
from ..tools.audit_tool import get_audit_status, run_audit
from ..tools.checklist_tool import get_compliance_checklist
from ..tools.gate_tool import get_audit_gate_result
from ..tools.policy_tool import get_compliance_policy, set_service_criticality
from ..tools.report_tool import get_audit_report, list_audits

_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "run_audit": {
        "description": "Executa auditoria completa de um repo em um ambiente",
        "schema": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Nome do serviço"},
                "repo": {"type": "string", "description": "Nome do repositório"},
                "env": {
                    "type": "string",
                    "description": "Ambiente: dev, hml, prod",
                    "enum": ["dev", "hml", "prod"],
                },
                "repo_path": {
                    "type": "string",
                    "description": "Caminho local do repo (opcional, tenta resolver automaticamente)",
                },
            },
            "required": ["service", "repo", "env"],
        },
    },
    "get_audit_status": {
        "description": "Retorna status da auditoria mais recente de um serviço/ambiente",
        "schema": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Nome do serviço"},
                "env": {
                    "type": "string",
                    "description": "Ambiente: dev, hml, prod",
                    "enum": ["dev", "hml", "prod"],
                },
            },
            "required": ["service", "env"],
        },
    },
    "get_compliance_policy": {
        "description": "Retorna política de conformidade para um ambiente",
        "schema": {
            "type": "object",
            "properties": {
                "env": {
                    "type": "string",
                    "description": "Ambiente: dev, hml, prod",
                    "enum": ["dev", "hml", "prod"],
                }
            },
            "required": ["env"],
        },
    },
    "get_compliance_checklist": {
        "description": "Retorna checklist dinâmico para um repo/ambiente (preview sem persistir)",
        "schema": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Nome do serviço"},
                "repo": {"type": "string", "description": "Nome do repositório"},
                "env": {
                    "type": "string",
                    "description": "Ambiente: dev, hml, prod",
                    "enum": ["dev", "hml", "prod"],
                },
            },
            "required": ["service", "repo", "env"],
        },
    },
    "submit_audit_approval": {
        "description": "Submete aprovação ou rejeição manual de uma auditoria",
        "schema": {
            "type": "object",
            "properties": {
                "audit_id": {"type": "string", "description": "ID da auditoria (audit_...)"},
                "approved_by": {"type": "string", "description": "Identificador de quem aprova"},
                "decision": {
                    "type": "string",
                    "description": "Decisão: approved ou rejected",
                    "enum": ["approved", "rejected"],
                },
                "role": {
                    "type": "string",
                    "description": "Role do aprovador (developer, lead, architect)",
                },
                "notes": {"type": "string", "description": "Notas da aprovação"},
            },
            "required": ["audit_id", "approved_by", "decision"],
        },
    },
    "get_audit_report": {
        "description": "Retorna relatório consolidado de conformidade",
        "schema": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Filtro por serviço (opcional)"},
                "env": {
                    "type": "string",
                    "description": "Filtro por ambiente (opcional)",
                },
                "period_days": {
                    "type": "integer",
                    "description": "Período de relatório em dias (default: 30)",
                },
            },
        },
    },
    "list_audits": {
        "description": "Lista auditorias com filtros opcionais",
        "schema": {
            "type": "object",
            "properties": {
                "status": {"type": "string", "description": "Filtro por status"},
                "env": {"type": "string", "description": "Filtro por ambiente"},
                "service": {"type": "string", "description": "Filtro por serviço"},
                "limit": {
                    "type": "integer",
                    "description": "Limite de resultados (default: 50)",
                },
            },
        },
    },
    "set_service_criticality": {
        "description": "Define nível de criticidade de um serviço",
        "schema": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Nome do serviço"},
                "criticality": {
                    "type": "string",
                    "description": "Nível de criticidade",
                    "enum": ["low", "medium", "high", "critical"],
                },
                "updated_by": {"type": "string", "description": "Quem está atualizando"},
            },
            "required": ["service", "criticality", "updated_by"],
        },
    },
    "get_audit_gate_result": {
        "description": "Retorna resultado do gate audit_compliance para integração com pipeline-mcp",
        "schema": {
            "type": "object",
            "properties": {
                "service": {"type": "string", "description": "Nome do serviço"},
                "env": {
                    "type": "string",
                    "description": "Ambiente: dev, hml, prod",
                    "enum": ["dev", "hml", "prod"],
                },
            },
            "required": ["service", "env"],
        },
    },
}

_EXPECTED = {
    "run_audit",
    "get_audit_status",
    "get_compliance_policy",
    "get_compliance_checklist",
    "submit_audit_approval",
    "get_audit_report",
    "list_audits",
    "set_service_criticality",
    "get_audit_gate_result",
}

assert set(_TOOL_SCHEMAS.keys()) == _EXPECTED, "Tool schemas mismatch"


def _build_http_app() -> FastAPI:
    """Build FastAPI app for Audit HTTP on port 7100."""
    app = FastAPI(title="Audit API", version="0.1.0", docs_url="/docs")
    return app


def build_server() -> tuple[Any, ...]:
    """Constrói o servidor MCP."""
    settings = get_settings()
    http_app = _build_http_app()
    store = AuditStore(settings=settings)
    server: Server = Server("audit-mcp-server")

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        return [
            Tool(
                name=name,
                description=meta["description"],
                inputSchema=meta["schema"],
            )
            for name, meta in _TOOL_SCHEMAS.items()
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict | None) -> list:
        args = arguments or {}
        try:
            payload = _dispatch(name, args, settings, store)
        except KeyError:
            payload = {"error": "unknown_tool", "tool": name}
        except Exception as exc:
            payload = {"error": "internal_error", "details": str(exc), "tool": name}

        return [TextContent(type="text", text=json.dumps(payload, ensure_ascii=False, indent=2))]

    return server, settings, store

, http_app
def _dispatch(name: str, args: dict, settings: Any, store: AuditStore) -> dict:
    """Roteia para a tool correta."""
    try:
        if name == "run_audit":
            return run_audit(store, settings, **args)
        elif name == "get_audit_status":
            return get_audit_status(store, settings, **args)
        elif name == "get_compliance_policy":
            return get_compliance_policy(store, settings, **args)
        elif name == "get_compliance_checklist":
            return get_compliance_checklist(store, settings, **args)
        elif name == "submit_audit_approval":
            return submit_audit_approval(store, settings, **args)
        elif name == "get_audit_report":
            return get_audit_report(store, settings, **args)
        elif name == "list_audits":
            return list_audits(store, settings, **args)
        elif name == "set_service_criticality":
            return set_service_criticality(store, settings, **args)
        elif name == "get_audit_gate_result":
            return get_audit_gate_result(store, settings, **args)
        raise KeyError(name)
    except TypeError as e:
        return {"error": "invalid_arguments", "message": str(e)}


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
    """Entry point."""
    asyncio.run(_run())


if __name__ == "__main__":
    main()
