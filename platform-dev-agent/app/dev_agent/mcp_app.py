"""MCP server for the platform-dev-agent (Modo B) — connect it to Claude Code Desktop.

Exposes the autonomous engine over MCP (Streamable HTTP, no auth for the local PoC):

  - list_personas       — the 8 DevTeam personas (role, model, capabilities)
  - list_runbooks       — the declarative runbook catalog (DAG + steps)
  - capability_of       — the derived capability/risk of a gateway tool
  - plan                — build a plan from a runbook (selector -> builder), persisted PENDING
  - approve_and_execute — approve + execute a pending plan through the gateway

Gateway: uses an in-process DEMO gateway by default (so the whole loop works in
Desktop with no external deps). Set DEV_GATEWAY_URL (+ DEV_TENANT_ID / a real
token provider) to drive the REAL platform-mcp gateway instead.

Run (module is named ``mcp_app`` — NOT ``mcp`` — to avoid shadowing the ``mcp`` SDK):
  python -m app.dev_agent.mcp_app            # serves Streamable HTTP on :7130/mcp
"""

from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP

from app.dev_agent.capability import Capability, CapabilityResolver
from app.dev_agent.gateway.demo import DemoGatewayClient
from app.dev_agent.models.plan import RiskLevel
from app.dev_agent.pipeline import AutonomousPipeline, NoRunbookError
from app.dev_agent.profiles.registry import PROFILES
from app.dev_agent.runbook.catalog import RUNBOOK_CATALOG
from app.dev_agent.runbook_selector import RunbookSelector

_INSTRUCTIONS = (
    "platform-dev-agent (Modo B). Um leader + N personas de engenharia que planeja "
    "a partir de runbooks declarativos (DAG), pede aprovação humana e executa via o "
    "gateway platform-mcp. Fluxo: plan(objetivo) -> revise os passos -> "
    "approve_and_execute(question_id)."
)

mcp = FastMCP("platform-dev-agent", instructions=_INSTRUCTIONS)

_CAPS = CapabilityResolver()


def _build_gateway():
    """Real gateway when DEV_GATEWAY_URL *and* a token are set; else the demo one.

    Requiring the token too avoids silently going "real" with an empty Bearer
    (which would just 401 on every call) — no token => stay on the demo gateway.
    """
    url = os.getenv("DEV_GATEWAY_URL")
    if not url or not os.getenv("DEV_GATEWAY_TOKEN"):
        return DemoGatewayClient()
    from app.dev_agent.gateway.client import GatewayToolClient

    class _EnvTokenProvider:
        async def get_token(self) -> str:
            return os.getenv("DEV_GATEWAY_TOKEN", "")

    return GatewayToolClient(
        base_url=url, token_provider=_EnvTokenProvider(),
        tenant_id=os.getenv("DEV_TENANT_ID"),
    )


# One pipeline instance for the server (in-memory plan store persists across calls
# within a run). Enforcer grants every persona read+write for the PoC demo.
from app.dev_agent.capability import CapabilityEnforcer  # noqa: E402
from app.dev_agent.catalog import (  # noqa: E402
    DirCatalogSource, PolicyEngine, RegistryCapabilityResolver,
)
from app.dev_agent.plan.repository import InMemoryPlanRepository  # noqa: E402

_REPO = InMemoryPlanRepository()
_ENFORCER = CapabilityEnforcer({pid: {Capability.READ, Capability.WRITE} for pid in PROFILES})
# Fase 2: catálogo (Fase 1) como source of truth + PDP por recurso/efeito. O
# DirCatalogSource lê platform-catalog/catalog quando presente; ausente (ex.: imagem
# Docker sem o catálogo) degrada para a heurística (migração aditiva, ADR-009 D9.10).
_RESOLVER = RegistryCapabilityResolver(DirCatalogSource())
_PIPELINE = AutonomousPipeline(
    repo=_REPO, gateway=_build_gateway(), enforcer=_ENFORCER, selector=RunbookSelector(),
    resolver=_RESOLVER, policy=PolicyEngine(),
)


@mcp.tool()
def list_personas() -> list[dict]:
    """Lista as personas DevTeam (papel, modelo, capabilities) — os modos do agente."""
    out = []
    for pid, cls in sorted(PROFILES.items()):
        fm = getattr(cls, "front_matter", {}) or {}
        out.append({
            "id": pid,
            "display_name": getattr(cls, "display_name", pid),
            "model": getattr(cls, "model", ""),
            "capabilities": fm.get("capabilities", []),
        })
    return out


@mcp.tool()
def list_runbooks() -> list[dict]:
    """Lista os runbooks declarativos (DAG versionado) que o agente pode planejar."""
    out = []
    for rid, rb in RUNBOOK_CATALOG.items():
        out.append({
            "id": rid,
            "version": rb.version,
            "name": rb.name,
            "responsible_profile": rb.responsible_profile,
            "tasks": [
                {"task_id": tid, "tool": t.tool, "responsible": t.responsible,
                 "required": t.required, "depends_on": list(t.depends_on)}
                for tid, t in rb.tasks.items()
            ],
        })
    return out


@mcp.tool()
def capability_of(tool: str) -> dict:
    """Mostra a capability (read/write, por verbo) e o risco de uma tool do gateway."""
    cap = _CAPS.resolve(tool)
    return {"tool": tool, "capability": cap.value,
            "risk": _CAPS.classify_risk(tool, cap).value}


@mcp.tool()
async def plan(objective: str, entity_type: str = "service_health",
               service: str = "api", suite: str = "unit") -> dict:
    """Planeja a partir de um runbook: seleciona o runbook, monta o DAG e persiste PENDING.

    Retorna o plano (passos + capability/risco) e o question_id para aprovar depois.
    """
    try:
        proposal = await _PIPELINE.plan(
            message=objective, session_id="desktop", entity_type=entity_type,
            inputs_by_task={
                "check_health": {"service": service},
                "run_tests": {"suite": suite},
                "deploy": {"service": service, "version": "v1"},
            },
        )
    except NoRunbookError as e:
        return {"error": "no_runbook", "detail": str(e),
                "hint": "tente entity_type=service_health (read-only) ou deployment (com passo high-risk)"}
    p = proposal.plan
    high = [
        {"item_id": i.item_id, "tool": i.tool, "label": i.label}
        for i in p.items if i.risk is RiskLevel.HIGH
    ]
    return {
        "plan_id": p.plan_id,
        "question_id": p.question_id,
        "title": p.title,
        "runbook": f"{p.runbook_id}@{p.runbook_version}",
        "steps": [
            {"seq": i.sequence_num, "task": i.task_id, "tool": i.tool,
             "capability": i.capability.value, "risk": i.risk.value,
             "responsible": i.responsible, "required": i.required}
            for i in p.items
        ],
        "high_risk_steps": high,  # exigem confirmacao individual (N2)
        "next": (
            f"approve_and_execute(question_id='{p.question_id}')"
            + (" -> os passos HIGH serao PULADOS ate voce chamar com confirm_high_risk=True" if high else "")
        ),
    }


@mcp.tool()
async def approve_and_execute(
    question_id: str, approve_all: bool = True, confirm_high_risk: bool = False
) -> dict:
    """Aprova (N1) e executa um plano pendente via o gateway.

    approve_all=True aprova todos os passos no N1. Passos de ALTO RISCO NUNCA rodam
    so com approve_all — exigem confirm_high_risk=True (o gate N2). Com approve_all=False
    e confirm_high_risk=False, nada e aprovado e o plano espera nova resposta.
    """
    if not approve_all and not confirm_high_risk:
        response_value: object = None  # nada aprovado -> re-prompt
    else:
        rv: dict[str, object] = {"__approve_all__": bool(approve_all)}
        if confirm_high_risk:
            plan_obj = await _REPO.get_by_question_id(question_id)
            if plan_obj is not None:
                rv["__confirm_high__"] = [
                    i.item_id for i in plan_obj.items if i.risk is RiskLevel.HIGH
                ]
        response_value = rv
    outcome = await _PIPELINE.execute(
        question_id=question_id, response_value=response_value, run_id="desktop-run",
    )
    return {
        "status": outcome.status.value,
        "needs_reprompt": outcome.needs_reprompt,
        "results": [{"task": r.task_id, "tool": r.tool, "status": r.status.value,
                     "error": r.error} for r in outcome.results],
        "gateway": "real" if os.getenv("DEV_GATEWAY_URL") else "demo",
    }


def main() -> None:
    mcp.settings.host = os.getenv("MCP_HOST", "0.0.0.0")
    mcp.settings.port = int(os.getenv("MCP_PORT", "7130"))
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
