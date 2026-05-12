"""POZilla MCP Server — Product Management Specialist."""
from __future__ import annotations

import os

import asyncio
from src.prompts.system_prompt import SYSTEM_PROMPT
from src.tools.pozilla_tools import (
    analyze_product_problem, calculate_rice_score, define_mvp_scope,
    define_product_metrics, define_product_vision, generate_discovery_questions,
    generate_feature_spec, generate_go_to_market_brief, generate_handoff_to_architecture,
    generate_handoff_to_design, generate_handoff_to_engineering, generate_release_plan,
    generate_user_stories, map_product_risks, map_user_journey, map_user_personas,
    prioritize_backlog,
)
from shared.hybrid_server import HybridMCPServer

_TOOLS = {
    "analyze_product_problem": {"description": "Analisa problema", "schema": {"type": "object"}},
    "calculate_rice_score": {"description": "RICE score", "schema": {"type": "object"}},
    "define_mvp_scope": {"description": "MVP scope", "schema": {"type": "object"}},
    "define_product_metrics": {"description": "Métricas", "schema": {"type": "object"}},
    "define_product_vision": {"description": "Visão", "schema": {"type": "object"}},
    "generate_discovery_questions": {"description": "Perguntas", "schema": {"type": "object"}},
    "generate_feature_spec": {"description": "Feature spec", "schema": {"type": "object"}},
    "generate_go_to_market_brief": {"description": "GTM brief", "schema": {"type": "object"}},
    "generate_handoff_to_architecture": {"description": "Arch handoff", "schema": {"type": "object"}},
    "generate_handoff_to_design": {"description": "Design handoff", "schema": {"type": "object"}},
    "generate_handoff_to_engineering": {"description": "Eng handoff", "schema": {"type": "object"}},
    "generate_release_plan": {"description": "Release plan", "schema": {"type": "object"}},
    "generate_user_stories": {"description": "Stories", "schema": {"type": "object"}},
    "map_product_risks": {"description": "Riscos", "schema": {"type": "object"}},
    "map_user_journey": {"description": "Jornada", "schema": {"type": "object"}},
    "map_user_personas": {"description": "Personas", "schema": {"type": "object"}},
    "prioritize_backlog": {"description": "Priorização", "schema": {"type": "object"}},
}

_DISPATCH = {
    "analyze_product_problem": lambda a: analyze_product_problem(),
    "calculate_rice_score": lambda a: calculate_rice_score(),
    "define_mvp_scope": lambda a: define_mvp_scope(),
    "define_product_metrics": lambda a: define_product_metrics(),
    "define_product_vision": lambda a: define_product_vision(),
    "generate_discovery_questions": lambda a: generate_discovery_questions(),
    "generate_feature_spec": lambda a: generate_feature_spec(),
    "generate_go_to_market_brief": lambda a: generate_go_to_market_brief(),
    "generate_handoff_to_architecture": lambda a: generate_handoff_to_architecture(),
    "generate_handoff_to_design": lambda a: generate_handoff_to_design(),
    "generate_handoff_to_engineering": lambda a: generate_handoff_to_engineering(),
    "generate_release_plan": lambda a: generate_release_plan(),
    "generate_user_stories": lambda a: generate_user_stories(),
    "map_product_risks": lambda a: map_product_risks(),
    "map_user_journey": lambda a: map_user_journey(),
    "map_user_personas": lambda a: map_user_personas(),
    "prioritize_backlog": lambda a: prioritize_backlog(),
}

def main() -> None:
    server = HybridMCPServer("pozilla-mcp-server", _TOOLS, _DISPATCH, SYSTEM_PROMPT)
    asyncio.run(server.run(http_port=int(os.getenv("MCP_PORT", "7100"))))

if __name__ == "__main__":
    main()
