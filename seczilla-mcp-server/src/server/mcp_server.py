"""SecZilla MCP Server — Security & Compliance Specialist."""
from __future__ import annotations

import os

import asyncio
from src.prompts.system_prompt import SYSTEM_PROMPT
from src.tools.seczilla_tools import (
    generate_threat_model,
    generate_security_controls,
    map_attack_surface,
    review_secure_code,
    scan_dependency_risks,
    analyze_compliance,
    stub_tool,
)
from shared.hybrid_server import HybridMCPServer

_TOOLS = {
    "generate_threat_model": {
        "description": "Gera modelo de ameaças STRIDE completo",
        "schema": {
            "type": "object",
            "properties": {
                "system": {"type": "string", "description": "Nome do sistema"},
                "scope": {"type": "string", "description": "Escopo da análise"},
            },
        },
    },
    "generate_security_controls": {
        "description": "Gera controles de segurança técnicos e processuais",
        "schema": {
            "type": "object",
            "properties": {
                "system": {"type": "string"},
                "control_type": {"type": "string", "enum": ["technical", "operational"]},
            },
        },
    },
    "map_attack_surface": {
        "description": "Mapeia superfície de ataque do sistema",
        "schema": {
            "type": "object",
            "properties": {"system": {"type": "string"}},
        },
    },
    "review_secure_code": {
        "description": "Revisa código contra OWASP Top 10",
        "schema": {
            "type": "object",
            "properties": {
                "code": {"type": "string"},
                "language": {"type": "string", "enum": ["python", "typescript", "java"]},
            },
        },
    },
    "scan_dependency_risks": {
        "description": "Escaneia dependências por CVEs e riscos",
        "schema": {"type": "object"},
    },
    "analyze_compliance": {
        "description": "Analisa conformidade contra padrões de segurança",
        "schema": {"type": "object"},
    },
    "status": {"description": "Status check", "schema": {"type": "object"}},
}

_DISPATCH = {
    "generate_threat_model": lambda a: generate_threat_model(
        system=a.get("system", "system"),
        scope=a.get("scope", ""),
    ),
    "generate_security_controls": lambda a: generate_security_controls(
        system=a.get("system", "system"),
        control_type=a.get("control_type", "technical"),
    ),
    "map_attack_surface": lambda a: map_attack_surface(system=a.get("system", "system")),
    "review_secure_code": lambda a: review_secure_code(
        code=a.get("code", ""),
        language=a.get("language", "python"),
    ),
    "scan_dependency_risks": lambda a: scan_dependency_risks(),
    "analyze_compliance": lambda a: analyze_compliance(),
    "status": lambda a: stub_tool(),
}

def main() -> None:
    server = HybridMCPServer("seczilla-mcp-server", _TOOLS, _DISPATCH, SYSTEM_PROMPT)
    asyncio.run(server.run(http_port=int(os.getenv("MCP_PORT", "7100"))))

if __name__ == "__main__":
    main()
