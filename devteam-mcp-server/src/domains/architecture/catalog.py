"""Catálogo de tools + dispatcher do domínio *architecture* (consolidado no devteam-mcp).

Este módulo é a fatia "de negócio" do antigo `architecture-mcp-server/src/server/
mcp_server.py`: mantém intactos o ``_TOOL_SCHEMAS`` (metadados de policy por tool) e o
``_dispatch`` (roteamento op → handler). O que ficou de FORA é o boot/serve/segurança
(FastAPI, PEP inner-token, stdio, tenant plumbing) — isso é responsabilidade do
AGREGADOR (`src/server/mcp_server.py`), compartilhado por todos os domínios.

Diferenças vs. o server-fonte (strangler — fiel, sem inventar comportamento):
  * ``capability`` passa a ``devteam-mcp.architecture_<op>`` (namespace do server
    consolidado + nome de tool já prefixado pelo domínio — o gateway não deriva por
    nome, então a capability é o id estável).
  * ``required_scope`` passa a ``architecture:<recurso>:<ação>`` — PRESERVA o
    least-privilege por-tool do domínio (data_domain=architecture), só troca o antigo
    prefixo de namespace ``architecture-mcp`` pelo domínio canônico ``architecture``.
  * As CHAVES de ``_TOOL_SCHEMAS`` aqui continuam os nomes de op SEM prefixo
    (``save_artifact``); o ``plugin.register()`` prefixa (``architecture_save_artifact``)
    e o ``plugin.dispatch`` retira o prefixo antes de chamar ``dispatch`` daqui — assim
    a lógica de roteamento copiada do server-fonte fica byte-a-byte idêntica.
"""

from __future__ import annotations

from typing import Any

from .db.store import ArchitectureStore
from .tools import (
    delete_architecture_blueprint,
    delete_artifact,
    delete_c4_diagram,
    delete_solution_blueprint,
    generate_adr,
    generate_c4_diagram,
    generate_sequence_diagram,
    get_architecture_blueprint,
    get_artifact,
    get_c4_diagram,
    get_solution_blueprint,
    list_architecture_blueprints,
    list_artifacts,
    list_c4_diagrams,
    list_solution_blueprints,
    save_architecture_blueprint,
    save_artifact,
    save_solution_blueprint,
    set_c4_diagram,
    update_architecture_blueprint,
    update_solution_blueprint,
)

# Domínio canônico deste plugin — usado no capability/required_scope e como prefixo de
# tool (o agregador descobre o domínio por ``<domain>_<op>``).
DOMAIN = "architecture"

# ── Tool Schemas + Policy metadata (STD-MCP-001 CI-2) ─────────────────────────
# Cada tool declara description/schema + os 4 campos de política:
#   capability     — id estável <namespace>.<tool> (não derivar por nome no gateway)
#   required_scope — escopo <domain>:<resource_type>:<acao> (least-privilege)
#   resource_type  — tipo de recurso tocado
#   data_domain    — domínio de dado (governa HITL floor / classificação LGPD)
# inputSchema MUST ser type=object com properties. Consultas (list/get) usam :read;
# mutações (save/set/update/delete) usam :write.
# ─────────────────────────────────────────────────────────────────────────────
_STR = {"type": "string"}
_INT = {"type": "integer"}
_OBJ = {"type": "object"}
_ARR = {"type": "array"}


def _schema(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    s: dict[str, Any] = {"type": "object", "additionalProperties": False, "properties": props}
    if required:
        s["required"] = required
    return s


def _meta(cap: str, scope: str, rtype: str, domain: str, desc: str, schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "description": desc,
        # capability = <namespace do server consolidado>.<domínio>_<op>
        "capability": f"devteam-mcp.{DOMAIN}_{cap}",
        # required_scope = <domínio>:<recurso>:<ação> (least-privilege por-tool intacto)
        "required_scope": f"{DOMAIN}:{scope}",
        "resource_type": rtype,
        "data_domain": domain,
        "schema": schema,
    }


_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    # ── Architecture Blueprints ────────────────────────────────────────────── #
    "save_architecture_blueprint": _meta(
        "save_architecture_blueprint",
        "architecture_blueprint:write",
        "architecture_blueprint",
        "architecture",
        "Deriva a proposta de arquitetura dos inputs (estilo/táticas) e a persiste.",
        _schema(
            {
                "domain": dict(_STR, description="Domínio/negócio-alvo."),
                "constraints": dict(_ARR, description="Restrições técnicas/organizacionais (opcional)."),
                "quality_attributes": dict(
                    _ARR, description="Atributos de qualidade priorizados (opcional)."
                ),
                "architecture_name": dict(_STR, description="Nome da arquitetura (opcional)."),
                "status": dict(_STR, description="Status (opcional)."),
            },
            required=["domain"],
        ),
    ),
    "list_architecture_blueprints": _meta(
        "list_architecture_blueprints",
        "architecture_blueprint:read",
        "architecture_blueprint",
        "architecture",
        "Lista propostas de arquitetura persistidas, com filtros opcionais.",
        _schema(
            {
                "domain": dict(_STR, description="Filtrar por domínio (opcional)."),
                "status": dict(_STR, description="Filtrar por status (opcional)."),
            }
        ),
    ),
    "get_architecture_blueprint": _meta(
        "get_architecture_blueprint",
        "architecture_blueprint:read",
        "architecture_blueprint",
        "architecture",
        "Retorna uma proposta de arquitetura por id.",
        _schema({"id": dict(_INT, description="Id da proposta.")}, required=["id"]),
    ),
    "update_architecture_blueprint": _meta(
        "update_architecture_blueprint",
        "architecture_blueprint:write",
        "architecture_blueprint",
        "architecture",
        "Atualiza campos mutáveis de uma proposta (name/style/content/status).",
        _schema(
            {
                "id": dict(_INT, description="Id da proposta."),
                "name": dict(_STR, description="Novo nome (opcional)."),
                "style": dict(_STR, description="Novo estilo (opcional)."),
                "content": dict(_OBJ, description="Novo conteúdo (opcional)."),
                "status": dict(_STR, description="Novo status (opcional)."),
            },
            required=["id"],
        ),
    ),
    "delete_architecture_blueprint": _meta(
        "delete_architecture_blueprint",
        "architecture_blueprint:write",
        "architecture_blueprint",
        "architecture",
        "Soft-delete de uma proposta de arquitetura por id.",
        _schema({"id": dict(_INT, description="Id da proposta.")}, required=["id"]),
    ),
    # ── C4 Diagrams (upsert por system_name) ───────────────────────────────── #
    "set_c4_diagram": _meta(
        "set_c4_diagram",
        "c4_diagram:write",
        "c4_diagram",
        "architecture",
        "Deriva (ou aceita pronto) o modelo C4 e o persiste por sistema (upsert).",
        _schema(
            {
                "system_name": dict(_STR, description="Nome do sistema (chave natural única)."),
                "actors": dict(_ARR, description="Pessoas/sistemas externos (opcional)."),
                "containers": dict(_ARR, description="Aplicações/serviços internos (opcional)."),
                "relationships": dict(_ARR, description="Arestas {source,target} ou 'A -> B' (opcional)."),
                "model": dict(_OBJ, description="Modelo C4 pronto (opcional; sobrepõe o builder)."),
                "status": dict(_STR, description="Status (opcional)."),
            },
            required=["system_name"],
        ),
    ),
    "list_c4_diagrams": _meta(
        "list_c4_diagrams",
        "c4_diagram:read",
        "c4_diagram",
        "architecture",
        "Lista modelos C4 persistidos, com filtro opcional por status.",
        _schema({"status": dict(_STR, description="Filtrar por status (opcional).")}),
    ),
    "get_c4_diagram": _meta(
        "get_c4_diagram",
        "c4_diagram:read",
        "c4_diagram",
        "architecture",
        "Retorna o modelo C4 persistido de um sistema pela chave natural system_name.",
        _schema({"system_name": dict(_STR, description="Nome do sistema.")}, required=["system_name"]),
    ),
    "delete_c4_diagram": _meta(
        "delete_c4_diagram",
        "c4_diagram:write",
        "c4_diagram",
        "architecture",
        "Remove (soft-delete) o modelo C4 de um sistema pela chave system_name; idempotente.",
        _schema({"system_name": dict(_STR, description="Nome do sistema.")}, required=["system_name"]),
    ),
    # ── Solution Blueprints ────────────────────────────────────────────────── #
    "save_solution_blueprint": _meta(
        "save_solution_blueprint",
        "solution_blueprint:write",
        "solution_blueprint",
        "architecture",
        "Deriva o blueprint de solução dos requisitos (camadas/padrões/NFRs) e o persiste.",
        _schema(
            {
                "requirements": dict(_STR, description="Requisitos funcionais/de negócio."),
                "solution_name": dict(_STR, description="Nome da solução (opcional)."),
                "context": dict(_STR, description="Contexto adicional (opcional)."),
                "constraints": dict(_ARR, description="Restrições (opcional)."),
                "status": dict(_STR, description="Status (opcional)."),
            },
            required=["requirements"],
        ),
    ),
    "list_solution_blueprints": _meta(
        "list_solution_blueprints",
        "solution_blueprint:read",
        "solution_blueprint",
        "architecture",
        "Lista blueprints de solução persistidos, com filtros opcionais.",
        _schema(
            {
                "solution_name": dict(_STR, description="Filtrar por nome da solução (opcional)."),
                "status": dict(_STR, description="Filtrar por status (opcional)."),
            }
        ),
    ),
    "get_solution_blueprint": _meta(
        "get_solution_blueprint",
        "solution_blueprint:read",
        "solution_blueprint",
        "architecture",
        "Retorna um blueprint de solução persistido (camadas/padrões/NFRs) por id.",
        _schema({"id": dict(_INT, description="Id do blueprint.")}, required=["id"]),
    ),
    "update_solution_blueprint": _meta(
        "update_solution_blueprint",
        "solution_blueprint:write",
        "solution_blueprint",
        "architecture",
        "Atualiza campos mutáveis de um blueprint de solução (context/content/status).",
        _schema(
            {
                "id": dict(_INT, description="Id do blueprint."),
                "context": dict(_STR, description="Novo contexto (opcional)."),
                "content": dict(_OBJ, description="Novo conteúdo (opcional)."),
                "status": dict(_STR, description="Novo status (opcional)."),
            },
            required=["id"],
        ),
    ),
    "delete_solution_blueprint": _meta(
        "delete_solution_blueprint",
        "solution_blueprint:write",
        "solution_blueprint",
        "architecture",
        "Soft-delete de um blueprint de solução por id.",
        _schema({"id": dict(_INT, description="Id do blueprint.")}, required=["id"]),
    ),
    # ── Artifacts (histórico append-only) ──────────────────────────────────── #
    "save_artifact": _meta(
        "save_artifact",
        "artifact:write",
        "artifact",
        "architecture",
        "Persiste um artefato de arquitetura (diagrama/ADR/nota) gerado pelo agente.",
        _schema(
            {
                "kind": dict(
                    _STR,
                    description=(
                        "Tipo: adr|c4|diagram|blueprint|proposal|decision|mermaid|plantuml|markdown|note."
                    ),
                ),
                "target": dict(_STR, description="Alvo (sistema/domínio/serviço)."),
                "content": dict(_STR, description="Texto/código gerado pelo agente."),
                "format": dict(_STR, description="Formato (mermaid/plantuml/markdown/json; opcional)."),
                "meta": dict(_OBJ, description="Metadados adicionais (opcional)."),
            },
            required=["kind", "target", "content"],
        ),
    ),
    "list_artifacts": _meta(
        "list_artifacts",
        "artifact:read",
        "artifact",
        "architecture",
        "Lista artefatos persistidos, com filtros opcionais.",
        _schema(
            {
                "kind": dict(_STR, description="Filtrar por tipo (opcional)."),
                "target": dict(_STR, description="Filtrar por alvo (opcional)."),
                "limit": dict(_INT, description="Máximo de registros (default 50)."),
            }
        ),
    ),
    "get_artifact": _meta(
        "get_artifact",
        "artifact:read",
        "artifact",
        "architecture",
        "Retorna um artefato de arquitetura persistido (diagrama/ADR/nota) por id.",
        _schema({"id": dict(_INT, description="Id do artefato.")}, required=["id"]),
    ),
    "delete_artifact": _meta(
        "delete_artifact",
        "artifact:write",
        "artifact",
        "architecture",
        "Remove (soft-delete) um artefato de arquitetura por id; idempotente.",
        _schema({"id": dict(_INT, description="Id do artefato.")}, required=["id"]),
    ),
    # ── Geradores determinísticos (COMPUTE PURO — não persistem) ───────────── #
    # required_scope: os scopes existentes seguem `<resource_type>:<acao>` com
    # :read p/ consultas e :write p/ mutações do estado do tenant. Geradores não
    # LEEM nem GRAVAM estado — só formatam a spec em artefato de arquitetura —
    # então nenhum dos dois cabe. Escolha: nova ação `:generate` sobre
    # resource_type=`artifact` (o mesmo domínio dos artefatos persistidos):
    # least-privilege real (um token só de geração não abre leitura/escrita de
    # artefatos). data_domain=architecture.
    "generate_c4_diagram": _meta(
        "generate_c4_diagram",
        "artifact:generate",
        "artifact",
        "architecture",
        "Gera um diagrama C4 em Mermaid (context|container|component) determinístico a partir da spec.",
        _schema(
            {
                "level": dict(_STR, description="Nível: context|container|component."),
                "elements": dict(
                    _ARR,
                    description="Elementos [{name,type?,technology?,description?,id?}] ou nomes (str).",
                ),
                "relations": dict(
                    _ARR, description="Relações [{from,to,text?,technology?}] ou 'A -> B' (opcional)."
                ),
                "title": dict(_STR, description="Título do diagrama (opcional)."),
            },
            required=["level", "elements"],
        ),
    ),
    "generate_sequence_diagram": _meta(
        "generate_sequence_diagram",
        "artifact:generate",
        "artifact",
        "architecture",
        "Gera um diagrama de sequência em Mermaid determinístico a partir de participantes e mensagens.",
        _schema(
            {
                "participants": dict(
                    _ARR, description="Participantes [{name,alias?}] ou nomes (str) (opcional)."
                ),
                "messages": dict(_ARR, description="Mensagens [{from,to,text?,type?}]."),
                "title": dict(_STR, description="Título do diagrama (opcional)."),
            },
            required=["messages"],
        ),
    ),
    "generate_adr": _meta(
        "generate_adr",
        "artifact:generate",
        "artifact",
        "architecture",
        "Gera um ADR (Architecture Decision Record) em Markdown determinístico a partir da spec.",
        _schema(
            {
                "title": dict(_STR, description="Título da decisão."),
                "context": dict(_STR, description="Contexto/forças (str ou lista de bullets; opcional)."),
                "decision": dict(_STR, description="Decisão tomada (str ou lista; opcional)."),
                "consequences": dict(_STR, description="Consequências (str ou lista de bullets; opcional)."),
                "status": dict(_STR, description="Status (default Proposed)."),
                "number": dict(_INT, description="Número sequencial do ADR (opcional)."),
                "alternatives": dict(_ARR, description="Alternativas consideradas (opcional)."),
            },
            required=["title"],
        ),
    ),
}


# ── Dispatcher (stateful: recebe store; tenant_id só p/ governança) ───────────


async def dispatch(name: str, args: dict[str, Any], store: ArchitectureStore) -> dict[str, Any]:
    """Despacha a chamada para a tool (async). ``name`` é o nome de op SEM prefixo de
    domínio (o ``plugin.dispatch`` já o retirou). O tenant NÃO viaja nos args (INV-3):
    o ``store`` já está ligado ao pool do tenant (resolvido dos claims do inner token)."""
    # ── Geradores (COMPUTE PURO: síncronos, ignoram o store — não persistem) ── #
    if name == "generate_c4_diagram":
        return generate_c4_diagram(args)
    if name == "generate_sequence_diagram":
        return generate_sequence_diagram(args)
    if name == "generate_adr":
        return generate_adr(args)
    # ── Architecture Blueprints ────────────────────────────────────────────── #
    if name == "save_architecture_blueprint":
        return await save_architecture_blueprint(
            store,
            domain=args["domain"],
            constraints=args.get("constraints"),
            quality_attributes=args.get("quality_attributes"),
            architecture_name=args.get("architecture_name", ""),
            status=args.get("status"),
        )
    if name == "list_architecture_blueprints":
        return await list_architecture_blueprints(store, domain=args.get("domain"), status=args.get("status"))
    if name == "get_architecture_blueprint":
        return await get_architecture_blueprint(store, blueprint_id=args["id"])
    if name == "update_architecture_blueprint":
        return await update_architecture_blueprint(
            store,
            blueprint_id=args["id"],
            name=args.get("name"),
            style=args.get("style"),
            content=args.get("content"),
            status=args.get("status"),
        )
    if name == "delete_architecture_blueprint":
        return await delete_architecture_blueprint(store, blueprint_id=args["id"])
    # ── C4 Diagrams ────────────────────────────────────────────────────────── #
    if name == "set_c4_diagram":
        return await set_c4_diagram(
            store,
            system_name=args["system_name"],
            actors=args.get("actors"),
            containers=args.get("containers"),
            relationships=args.get("relationships"),
            model=args.get("model"),
            status=args.get("status"),
        )
    if name == "list_c4_diagrams":
        return await list_c4_diagrams(store, status=args.get("status"))
    if name == "get_c4_diagram":
        return await get_c4_diagram(store, system_name=args["system_name"])
    if name == "delete_c4_diagram":
        return await delete_c4_diagram(store, system_name=args["system_name"])
    # ── Solution Blueprints ────────────────────────────────────────────────── #
    if name == "save_solution_blueprint":
        return await save_solution_blueprint(
            store,
            requirements=args["requirements"],
            solution_name=args.get("solution_name", "Solution"),
            context=args.get("context", ""),
            constraints=args.get("constraints"),
            status=args.get("status"),
        )
    if name == "list_solution_blueprints":
        return await list_solution_blueprints(
            store, solution_name=args.get("solution_name"), status=args.get("status")
        )
    if name == "get_solution_blueprint":
        return await get_solution_blueprint(store, blueprint_id=args["id"])
    if name == "update_solution_blueprint":
        return await update_solution_blueprint(
            store,
            blueprint_id=args["id"],
            context=args.get("context"),
            content=args.get("content"),
            status=args.get("status"),
        )
    if name == "delete_solution_blueprint":
        return await delete_solution_blueprint(store, blueprint_id=args["id"])
    # ── Artifacts ──────────────────────────────────────────────────────────── #
    if name == "save_artifact":
        return await save_artifact(
            store,
            kind=args["kind"],
            target=args["target"],
            content=args["content"],
            format=args.get("format"),
            meta=args.get("meta"),
        )
    if name == "list_artifacts":
        return await list_artifacts(
            store, kind=args.get("kind"), target=args.get("target"), limit=args.get("limit", 50)
        )
    if name == "get_artifact":
        return await get_artifact(store, artifact_id=args["id"])
    if name == "delete_artifact":
        return await delete_artifact(store, artifact_id=args["id"])
    raise KeyError(name)
