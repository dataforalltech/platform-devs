"""OpsZilla MCP Server — Infrastructure & DevOps Specialist."""
from __future__ import annotations

import os

import asyncio
from src.prompts.system_prompt import SYSTEM_PROMPT
from src.tools.opszilla_tools import (
    generate_kubernetes_manifest,
    generate_dockerfile,
    generate_github_actions_pipeline,
    generate_helm_chart,
    stub_tool,
)
from shared.hybrid_server import HybridMCPServer

_TOOLS = {
    "generate_kubernetes_manifest": {
        "description": "Gera manifests Kubernetes (Deployment, Service, ConfigMap)",
        "schema": {
            "type": "object",
            "properties": {
                "application": {"type": "string"},
                "replicas": {"type": "integer"},
            },
        },
    },
    "generate_dockerfile": {
        "description": "Gera Dockerfile otimizado",
        "schema": {
            "type": "object",
            "properties": {
                "application": {"type": "string"},
                "runtime": {"type": "string"},
            },
        },
    },
    "generate_github_actions_pipeline": {
        "description": "Gera pipeline CI/CD com GitHub Actions",
        "schema": {
            "type": "object",
            "properties": {"application": {"type": "string"}},
        },
    },
    "generate_helm_chart": {
        "description": "Gera Helm Chart para Kubernetes",
        "schema": {
            "type": "object",
            "properties": {"app_name": {"type": "string"}},
        },
    },
    "status": {"description": "Status check", "schema": {"type": "object"}},
}

_DISPATCH = {
    "generate_kubernetes_manifest": lambda a: generate_kubernetes_manifest(
        application=a.get("application", "app"),
        replicas=a.get("replicas", 3),
    ),
    "generate_dockerfile": lambda a: generate_dockerfile(
        application=a.get("application", "app"),
        runtime=a.get("runtime", "python:3.11"),
    ),
    "generate_github_actions_pipeline": lambda a: generate_github_actions_pipeline(
        application=a.get("application", "app")
    ),
    "generate_helm_chart": lambda a: generate_helm_chart(app_name=a.get("app_name", "app")),
    "status": lambda a: stub_tool(),
}

def main() -> None:
    server = HybridMCPServer("opszilla-mcp-server", _TOOLS, _DISPATCH, SYSTEM_PROMPT)
    asyncio.run(server.run(http_port=int(os.getenv("MCP_PORT", "7100"))))

if __name__ == "__main__":
    main()
