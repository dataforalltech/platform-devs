"""Smoke test + monitor para o ai-governance-mcp-server.

Uso:
    python scripts/smoke_test.py            # exercita as 13 tools uma vez e sai
    python scripts/smoke_test.py --watch    # após o smoke, faz heartbeat a cada 30s
    python scripts/smoke_test.py --watch --interval 10

O servidor MCP é spawned via stdio aqui mesmo — não precisa estar rodando
em outro terminal. Os logs do servidor saem em stderr e ficam visíveis no
terminal onde este script roda.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Casos de teste para cada tool (1x cada).
SMOKE_CALLS: list[tuple[str, dict]] = [
    ("get_agent_guidelines", {"layer": "backend", "task_type": "bugfix"}),
    ("get_layer_policy", {"layer": "integrations"}),
    ("get_forbidden_actions", {"context": "security"}),
    (
        "get_fallback_policy",
        {"scenario": "cache local quando provider de perfil falha", "service_name": "user-profile"},
    ),
    (
        "get_contract_change_policy",
        {
            "provider_service": "orders",
            "consumer_services": ["frontend", "billing"],
            "contract_type": "api",
            "proposed_change": "remover campo customer_email",
        },
    ),
    ("get_final_response_template", {"task_type": "bugfix"}),
    (
        "get_pre_execution_checklist",
        {
            "repository_name": "orders-service",
            "task_description": "adicionar fallback no provider externo",
            "layer": "integrations",
        },
    ),
    ("search_governance_knowledge", {"query": "fallback silencioso", "limit": 2}),
    (
        "validate_agent_decision",
        {
            "repository_name": "payment-service",
            "task_description": "tratar timeout do provider de cartao",
            "proposed_change": "try: provider.charge(amount)\nexcept Exception: pass",
            "adds_fallback": True,
            "affected_layers": ["backend", "integrations"],
        },
    ),
    ("query_ecosystem_graph", {"query": "stats"}),
    ("query_ecosystem_graph", {"kind": "service", "status": "active"}),
    ("find_consumers_of", {"node_id": "dataforall-rag-service"}),
    ("find_dependencies_of", {"node_id": "dataforall-agents-factory", "max_depth": 2}),
    ("get_service_metadata", {"node_id": "connectors-platform"}),
    ("list_suggestions", {"limit": 5}),
    # Não chamamos submit_suggestion no smoke porque ele persiste no disco;
    # o smoke deve ser repetível sem efeitos colaterais.
    ("get_port_map", {}),
    ("get_service_ownership", {"service_name": "platform-cdc"}),
    ("get_service_dependencies", {"service_name": "dataforall-rag-service"}),
    (
        "check_scope",
        {
            "task_description": "Adicionar timeout no provider externo",
            "changed_files": ["app/services/provider.py", "tests/test_provider.py"],
        },
    ),
    (
        "validate_lib_change",
        {"lib_name": "platform-core-lib", "proposed_change": "Adicionar helper X"},
    ),
    (
        "validate_migration",
        {
            "content": (
                "def upgrade():\n"
                "    op.execute(sa.text('CREATE TABLE IF NOT EXISTS x (id INT)'))\n\n"
                "def downgrade():\n"
                "    op.execute(sa.text('DROP TABLE IF EXISTS x'))\n"
            )
        },
    ),
    # Não chamamos create_adr no smoke — escreve arquivos.
]


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _summarize(tool: str, payload: dict) -> str:
    """Devolve uma linha de resumo sem despejar o JSON inteiro."""
    if tool == "validate_agent_decision":
        return (
            f"approved={payload.get('approved')} risk={payload.get('risk_level')} "
            f"violations={len(payload.get('violations', []))}"
        )
    if tool == "search_governance_knowledge":
        return f"total={payload.get('total')} hits={[h['source'] for h in payload.get('hits', [])]}"
    if tool == "get_forbidden_actions":
        return f"total={payload.get('total')}"
    if tool == "get_layer_policy":
        return (
            f"layer={payload.get('layer')} can_do={len(payload.get('can_do', []))} "
            f"cannot_do={len(payload.get('cannot_do', []))}"
        )
    if tool == "get_fallback_policy":
        return f"allowed={payload.get('fallback_allowed')}"
    if tool == "get_contract_change_policy":
        return (
            f"breaking={payload.get('is_breaking_change')} risk={payload.get('risk_level')}"
        )
    if tool == "get_final_response_template":
        return f"sections={len(payload.get('sections', []))}"
    if tool == "get_pre_execution_checklist":
        return (
            f"docs={len(payload.get('docs_to_read', []))} "
            f"questions={len(payload.get('questions_to_answer', []))}"
        )
    if tool == "get_agent_guidelines":
        return f"rules={len(payload.get('mandatory_rules', []))}"
    if tool == "query_ecosystem_graph":
        if "stats" in payload:
            s = payload["stats"]
            return f"nodes={s['total_nodes']} edges={s['total_edges']}"
        return f"query={payload.get('query')} total={payload.get('total')}"
    if tool == "find_consumers_of":
        return f"node={payload.get('node_id')} consumers={payload.get('total')}"
    if tool == "find_dependencies_of":
        return (
            f"node={payload.get('node_id')} depth={payload.get('max_depth')} "
            f"deps={payload.get('total')}"
        )
    if tool == "get_service_metadata":
        redirect = payload.get("canonical_redirect")
        return (
            f"found={payload.get('found')} "
            f"deps={len(payload.get('direct_dependencies', []))} "
            f"consumers={len(payload.get('consumers', []))} "
            f"canonical={redirect or '-'}"
        )
    if tool == "list_suggestions":
        return f"total={payload.get('total')}"
    if tool == "get_suggestion":
        return f"found={payload.get('found')}"
    if tool in ("submit_suggestion", "update_suggestion_status"):
        s = payload.get("suggestion") or {}
        return f"id={s.get('id')} status={s.get('status')}"
    if tool == "get_port_map":
        return f"services_with_port={payload.get('total_services_with_port')} next={payload.get('next_available_port')}"
    if tool == "get_service_ownership":
        return f"found={payload.get('found')} owns={len(payload.get('owns', []))} must_not={len(payload.get('must_not', []))}"
    if tool == "get_service_dependencies":
        return (
            f"found={payload.get('found')} downstream={payload.get('downstream_count', 0)} "
            f"risk={payload.get('contract_change_risk', '?')}"
        )
    if tool == "check_scope":
        return f"approved={payload.get('approved')} risk={payload.get('risk_level')}"
    if tool == "validate_lib_change":
        return f"blocked={payload.get('blocked')} consumers={len(payload.get('consumers', []))}"
    if tool == "validate_migration":
        return (
            f"approved={payload.get('approved', 'n/a')} "
            f"issues={len(payload.get('issues', []))} warnings={len(payload.get('warnings', []))}"
        )
    return "ok"


async def _call(session: ClientSession, name: str, args: dict) -> dict:
    res = await session.call_tool(name, args)
    return json.loads(res.content[0].text)


async def _smoke(session: ClientSession) -> int:
    """Lista tools + chama cada uma 1x. Retorna 0 se tudo OK, 1 caso contrário."""
    tools = await session.list_tools()
    print(f"[{_ts()}] list_tools -> {len(tools.tools)} tools")
    for t in tools.tools:
        print(f"  - {t.name}")
    print()

    failures = 0
    for name, args in SMOKE_CALLS:
        try:
            payload = await _call(session, name, args)
            if "error" in payload:
                print(f"[{_ts()}] FAIL {name}: {payload}")
                failures += 1
            else:
                print(f"[{_ts()}] OK   {name}: {_summarize(name, payload)}")
        except Exception as e:  # noqa: BLE001
            print(f"[{_ts()}] EXC  {name}: {e}")
            failures += 1
    print()
    print(f"[{_ts()}] smoke result: {len(SMOKE_CALLS) - failures}/{len(SMOKE_CALLS)} ok")
    return 0 if failures == 0 else 1


async def _watch(session: ClientSession, interval: int) -> None:
    """Loop infinito de heartbeat — exercita 2 tools leves periodicamente."""
    print(f"[{_ts()}] entering watch mode, interval={interval}s (Ctrl+C para sair)")
    tick = 0
    while True:
        tick += 1
        try:
            tools = await session.list_tools()
            search = await _call(
                session,
                "search_governance_knowledge",
                {"query": "fallback", "limit": 1},
            )
            print(
                f"[{_ts()}] tick #{tick} list_tools={len(tools.tools)} "
                f"search_total={search.get('total')}"
            )
        except Exception as e:  # noqa: BLE001
            print(f"[{_ts()}] tick #{tick} EXC: {e}")
        await asyncio.sleep(interval)


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--watch", action="store_true", help="após o smoke, faz heartbeat")
    parser.add_argument("--interval", type=int, default=30, help="segundos entre heartbeats")
    parser.add_argument(
        "--command",
        default=sys.executable,
        help="comando para spawnar o server (default: o python atual)",
    )
    args = parser.parse_args()

    server_args = ["-m", "src.server.mcp_server"] if args.command == sys.executable else []
    params = StdioServerParameters(command=args.command, args=server_args, env=None)

    async with stdio_client(params) as (r, w):
        async with ClientSession(r, w) as session:
            await session.initialize()
            rc = await _smoke(session)
            if args.watch:
                await _watch(session, args.interval)
            return rc


if __name__ == "__main__":
    try:
        sys.exit(asyncio.run(main()))
    except KeyboardInterrupt:
        print(f"\n[{_ts()}] interrupted")
        sys.exit(0)
