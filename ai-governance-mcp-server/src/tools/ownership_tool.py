"""Tools de ownership, escopo e libs — sprint 1 + sprint 2.

get_service_ownership  — o que o serviço possui e NÃO deve fazer (§49)
get_service_dependencies — upstream + downstream para análise de impacto
get_port_map           — mapeamento canônico porta → serviço (§47)
check_scope            — detecta drift de escopo tarefa × arquivos modificados
validate_lib_change    — HARD STOP §18 para libs privadas
"""

from __future__ import annotations

import re

from ..knowledge.governance_repository import GovernanceRepository
from ..utils.validators import require_non_empty_string
from .graph_tool import _require_graph

# ---------------------------------------------------------------------- #
# Constantes                                                              #
# ---------------------------------------------------------------------- #

_KNOWN_LIB_PATTERNS = [
    r"^platform-[\w]+-lib$",
    r"^platform-db-vector$",
]

_LIB_CHANGE_REQUEST_TEMPLATE = """\
## LIB CHANGE REQUEST — {lib_name}

> **Aprovação requerida:** @caiog — §18 AGENTS.md
> Não implemente NADA na lib antes da aprovação explícita.

### Campos obrigatórios

| Campo | Valor |
|---|---|
| Motivo da mudança | <descreva o problema que a mudança resolve> |
| Impacto em consumidores | <liste todos os serviços que usam esta lib> |
| Compatibilidade retroativa | <sim / não — se não, detalhe a migração> |
| Testes adicionados | <sim / não — descreva> |
| PR de referência | <link do PR> |

### Proposta de mudança

{proposed_change}

### Checklist antes de submeter
- [ ] Todos os consumidores da lib foram notificados
- [ ] Testes de integração passando em todos os serviços consumidores
- [ ] CHANGELOG.md da lib atualizado
- [ ] Versão incrementada seguindo semver
"""

_CORE_INFRA_PATTERNS = [
    r"(^|[/\\])settings\.py$",
    r"(^|[/\\])config\.py$",
    r"(^|[/\\])database\.py$",
    r"(^|[/\\])base\.py$",
    r"(^|[/\\])alembic[/\\]",
    r"docker-compose",
    r"Dockerfile",
    r"(^|[/\\])pyproject\.toml$",
    r"(^|[/\\])requirements\.txt$",
]

_LIB_FILE_PATTERNS = [
    r"platform-[\w]+-lib[/\\]",
    r"platform-db-vector[/\\]",
]


# ---------------------------------------------------------------------- #
# get_service_ownership                                                   #
# ---------------------------------------------------------------------- #

def get_service_ownership(repo: GovernanceRepository, service_name: str) -> dict:
    """O que o serviço possui, o que NÃO deve fazer e quem ele chama.

    Responde a pergunta crítica de 'onde implementar' antes de começar a tarefa.
    Dados extraídos do ecosystem.yaml (§49 AGENTS.md).
    """
    require_non_empty_string(service_name, "service_name")
    g = _require_graph(repo)

    node_id = _resolve_service(g, service_name)
    if node_id is None:
        # Tenta listar serviços disponíveis para ajudar
        available = sorted(
            nid for nid, data in g.graph.nodes(data=True)
            if data.get("kind") == "service"
        )
        return {
            "service_name": service_name,
            "found": False,
            "notes": [
                f"Serviço '{service_name}' não encontrado no grafo.",
                f"Serviços disponíveis: {available}",
            ],
        }

    node_data = dict(g.graph.nodes[node_id])

    # owns: description + campo owns explícito (ex: rag-service)
    owns: list[str] = []
    description = node_data.get("description")
    if description:
        owns.append(description)
    extra_owns = node_data.get("owns")
    if isinstance(extra_owns, list):
        owns.extend(str(x) for x in extra_owns)
    elif isinstance(extra_owns, str):
        owns.append(extra_owns)

    # must_not: explicit_non_responsibilities
    must_not = node_data.get("explicit_non_responsibilities") or []
    if isinstance(must_not, str):
        must_not = [must_not]

    # calls: arestas de saída para service/library/contract
    calls: list[dict] = []
    for _, dst, key in g.graph.out_edges(node_id, keys=True):
        dst_data = g.graph.nodes.get(dst, {})
        dst_kind = dst_data.get("kind")
        if dst_kind in ("service", "library", "contract"):
            calls.append({"id": dst, "kind": dst_kind, "via": key})

    notes: list[str] = []
    raw_notes = node_data.get("notes")
    if raw_notes:
        notes.append(raw_notes if isinstance(raw_notes, str) else "; ".join(raw_notes))
    if node_data.get("status") == "deprecated":
        notes.append("⚠ Serviço DEPRECADO — use o canônico em canonical_redirect.")

    # canonical_redirect se deprecado
    canonical_redirect = None
    if node_data.get("status") == "deprecated":
        for edge in g.neighbors(node_id, relation="deprecated_by", direction="out"):
            canonical_redirect = edge["to"]
            break

    return {
        "service_name": node_id,
        "found": True,
        "status": node_data.get("status", "unknown"),
        "port": node_data.get("port"),
        "gateway_prefix": node_data.get("gateway_prefix"),
        "owns": owns,
        "must_not": must_not,
        "calls": calls,
        "governance": node_data.get("governance"),
        "canonical_redirect": canonical_redirect,
        "notes": notes,
    }


# ---------------------------------------------------------------------- #
# get_service_dependencies                                                #
# ---------------------------------------------------------------------- #

def get_service_dependencies(repo: GovernanceRepository, service_name: str) -> dict:
    """Upstream (o que consome) + downstream (quem consome) de um serviço.

    Voltado para análise de impacto antes de mudanças de contrato.
    Use este tool antes de validate_agent_decision(changes_contracts=True).
    """
    require_non_empty_string(service_name, "service_name")
    g = _require_graph(repo)

    node_id = _resolve_service(g, service_name)
    if node_id is None:
        return {
            "service_name": service_name,
            "found": False,
            "notes": [f"Serviço '{service_name}' não encontrado no grafo."],
        }

    upstream = g.find_dependencies_of(node_id, max_depth=1)
    downstream = g.find_consumers_of(node_id)

    n_down = len(downstream)
    if n_down >= 5:
        risk = "high"
        risk_note = (
            f"Alto impacto: {n_down} consumidores diretos. "
            "Qualquer mudança de contrato exige coordenação prévia e ADR."
        )
    elif n_down >= 2:
        risk = "medium"
        risk_note = f"Impacto moderado: {n_down} consumidores diretos."
    else:
        risk = "low"
        risk_note = f"Baixo impacto: {n_down} consumidor(es) direto(s)."

    return {
        "service_name": node_id,
        "found": True,
        "upstream": upstream,
        "downstream": downstream,
        "upstream_count": len(upstream),
        "downstream_count": n_down,
        "contract_change_risk": risk,
        "notes": [risk_note],
        "guidance": (
            "Antes de mudar contratos: executar get_contract_change_policy, "
            "notificar todos os downstream e abrir ADR se risk=high."
        ),
    }


# ---------------------------------------------------------------------- #
# get_port_map                                                            #
# ---------------------------------------------------------------------- #

def get_port_map(repo: GovernanceRepository) -> dict:
    """Mapeamento canônico porta → serviço (§47 AGENTS.md).

    Inclui próxima porta livre e range reservado para novos serviços.
    """
    g = _require_graph(repo)

    entries: list[dict] = []
    for node_id, data in g.graph.nodes(data=True):
        if data.get("kind") != "service":
            continue
        port = data.get("port")
        if port is None:
            continue
        entries.append({
            "port": int(port),
            "service": node_id,
            "gateway_prefix": data.get("gateway_prefix"),
            "status": data.get("status", "unknown"),
        })

    entries.sort(key=lambda e: e["port"])
    used_ports = {e["port"] for e in entries}

    # Convenção: 8022-8029 são reservadas; próxima livre dentro desse range.
    reserved_range = "8022–8029"
    next_available: int | None = None
    for candidate in range(8022, 8030):
        if candidate not in used_ports:
            next_available = candidate
            break
    if next_available is None:
        # Range reservado esgotado — próxima após 8029
        next_available = max(used_ports, default=8000) + 1

    return {
        "port_map": entries,
        "total_services_with_port": len(entries),
        "reserved_range": reserved_range,
        "next_available_port": next_available,
        "notes": [
            "Porta 8000 reservada — nunca usar como host port.",
            "Porta 8080: dataforall-ui-connect.",
            "Em containers Docker/K8s todos os serviços rodam internamente na 8000; "
            "este mapeamento é apenas para docker-compose local (host-side).",
        ],
    }


# ---------------------------------------------------------------------- #
# check_scope                                                             #
# ---------------------------------------------------------------------- #

def check_scope(
    repo: GovernanceRepository,
    task_description: str,
    changed_files: list[str] | None = None,
) -> dict:
    """Detecta drift de escopo comparando a descrição da tarefa com os arquivos modificados.

    Útil antes de abrir PR. Verifica:
    - Volume excessivo de arquivos
    - Arquivos de infraestrutura central
    - Arquivos de libs privadas (HARD STOP §18)
    - Arquivos de múltiplos serviços
    - Arquivos possivelmente não relacionados à tarefa
    """
    require_non_empty_string(task_description, "task_description")
    files: list[str] = list(changed_files or [])

    drift_indicators: list[str] = []
    required_actions: list[str] = []
    recommendations: list[str] = []
    risk = "low"

    # --- Volume ---
    if len(files) > 30:
        drift_indicators.append(
            f"Volume excessivo: {len(files)} arquivos modificados. "
            "PRs com > 30 arquivos são difíceis de revisar e têm alto risco de regressão."
        )
        required_actions.append("Dividir em PRs menores, um por responsabilidade.")
        risk = _bump(risk, "high")
    elif len(files) > 15:
        drift_indicators.append(
            f"Volume elevado: {len(files)} arquivos. Verifique se todos são necessários."
        )
        recommendations.append("Considere commits atômicos ou PRs separados.")
        risk = _bump(risk, "medium")

    # --- Infraestrutura central ---
    infra_hits = [f for f in files if any(re.search(p, f) for p in _CORE_INFRA_PATTERNS)]
    if infra_hits:
        drift_indicators.append(
            f"Arquivos de infraestrutura central modificados: {infra_hits}. "
            "Mudanças nesses arquivos têm impacto sistêmico e raramente são escopo de uma tarefa pontual."
        )
        required_actions.append(
            "Justificar explicitamente por que cada arquivo de infraestrutura precisa mudar para esta tarefa."
        )
        risk = _bump(risk, "high")

    # --- Libs privadas (HARD STOP) ---
    lib_hits = [f for f in files if any(re.search(p, f) for p in _LIB_FILE_PATTERNS)]
    if lib_hits:
        drift_indicators.append(
            f"Arquivos de libs privadas detectados: {lib_hits}. "
            "HARD STOP §18: requer LIB CHANGE REQUEST aprovado por @caiog."
        )
        required_actions.append(
            "Remover mudanças nas libs do PR. Submeter LIB CHANGE REQUEST via validate_lib_change."
        )
        risk = _bump(risk, "critical")

    # --- Múltiplos serviços ---
    services = _extract_services(files)
    if len(services) > 1:
        drift_indicators.append(
            f"Arquivos de múltiplos serviços detectados: {sorted(services)}. "
            "Changes multi-serviço geralmente indicam mudança de contrato — exige coordenação prévia."
        )
        required_actions.append(
            "Verificar se todos os serviços estão no escopo declarado. "
            "Se sim, executar validate_agent_decision com changes_contracts=True."
        )
        risk = _bump(risk, "high")

    # --- Heurística task × arquivos ---
    if files:
        suspicious = _files_suspicious_for_task(task_description.lower(), files)
        if suspicious:
            drift_indicators.append(
                f"Arquivos possivelmente fora do escopo declarado: {suspicious[:5]}."
            )
            recommendations.append(
                "Confirme que cada arquivo é necessário para a tarefa. "
                "Refactors de oportunidade devem ir em PR separado."
            )
            risk = _bump(risk, "medium")

    approved = risk not in ("high", "critical")

    return {
        "task_description": task_description,
        "changed_files_count": len(files),
        "approved": approved,
        "risk_level": risk,
        "drift_indicators": drift_indicators,
        "required_actions": required_actions,
        "recommendations": recommendations,
        "affected_services": sorted(services),
    }


# ---------------------------------------------------------------------- #
# validate_lib_change                                                     #
# ---------------------------------------------------------------------- #

def validate_lib_change(
    repo: GovernanceRepository,
    lib_name: str,
    proposed_change: str,
) -> dict:
    """HARD STOP para mudanças em libs privadas (§18 AGENTS.md).

    Retorna blocked=True se lib_name é uma lib privada governada, junto com
    o template de LIB CHANGE REQUEST pré-preenchido e os consumidores identificados.
    """
    require_non_empty_string(lib_name, "lib_name")
    require_non_empty_string(proposed_change, "proposed_change")

    is_lib = _is_lib(lib_name, repo)
    if not is_lib:
        return {
            "lib_name": lib_name,
            "blocked": False,
            "notes": [
                f"'{lib_name}' não foi reconhecida como lib privada governada. "
                "Se for uma lib, adicione-a ao ecosystem.yaml com kind=library e "
                "governance=lib_change_request_required."
            ],
        }

    # Consumidores identificados no grafo para pré-preencher o template
    consumers: list[str] = []
    g = repo.ecosystem
    if g is not None and g.graph.has_node(lib_name):
        consumers = [c["id"] for c in g.find_consumers_of(lib_name)]

    template = _LIB_CHANGE_REQUEST_TEMPLATE.format(
        lib_name=lib_name,
        proposed_change=proposed_change,
    )
    if consumers:
        template += f"\n**Consumidores identificados automaticamente:** {', '.join(consumers)}\n"

    return {
        "lib_name": lib_name,
        "blocked": True,
        "reason": (
            "HARD STOP — §18 AGENTS.md: mudanças em libs privadas do ecossistema "
            "requerem LIB CHANGE REQUEST aprovado por @caiog ANTES de qualquer implementação."
        ),
        "consumers": consumers,
        "lib_change_request_template": template,
        "next_steps": [
            "1. Preencher o template de LIB CHANGE REQUEST acima.",
            "2. Submeter para revisão de @caiog — aguardar aprovação explícita.",
            "3. Só então implementar a mudança na lib.",
        ],
    }


# ---------------------------------------------------------------------- #
# Helpers                                                                 #
# ---------------------------------------------------------------------- #

def _resolve_service(g, service_name: str) -> str | None:
    """Resolve service_name para o id canônico, incluindo aliases e nome parcial."""
    name_lower = service_name.lower().strip()
    if g.graph.has_node(service_name):
        return service_name
    if g.graph.has_node(name_lower):
        return name_lower
    for node_id, data in g.graph.nodes(data=True):
        aliases = data.get("aliases") or []
        if isinstance(aliases, str):
            aliases = [aliases]
        if name_lower in [str(a).lower() for a in aliases]:
            return node_id
        # ex: "monitor" → "platform-monitor"
        if node_id.endswith(f"-{name_lower}") or node_id == name_lower:
            return node_id
    return None


def _bump(current: str, new: str) -> str:
    order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    return new if order.get(new, 0) > order.get(current, 0) else current


def _is_lib(lib_name: str, repo: GovernanceRepository) -> bool:
    """Retorna True se lib_name é uma lib privada governada."""
    for pat in _KNOWN_LIB_PATTERNS:
        if re.match(pat, lib_name, re.IGNORECASE):
            return True
    g = repo.ecosystem
    if g is not None and g.graph.has_node(lib_name):
        if g.graph.nodes[lib_name].get("kind") == "library":
            return True
    return False


def _extract_services(files: list[str]) -> set[str]:
    """Extrai nomes de serviços de paths como platform-auth/src/..."""
    services: set[str] = set()
    pattern = re.compile(r"(?:^|[/\\])((platform|dataforall)-[\w-]+?)(?:[/\\]|$)")
    for f in files:
        m = pattern.search(f.replace("\\", "/"))
        if m:
            services.add(m.group(1))
    return services


def _files_suspicious_for_task(task_lower: str, files: list[str]) -> list[str]:
    """Arquivos que parecem fora do escopo de tarefas que mencionam um serviço específico."""
    suspicious: list[str] = []
    service_in_task = re.findall(r"(platform-[\w-]+|dataforall-[\w-]+)", task_lower)
    if not service_in_task:
        return suspicious
    target = service_in_task[0]
    for f in files:
        f_norm = f.replace("\\", "/")
        if re.search(r"(platform|dataforall)-", f_norm) and target not in f_norm:
            suspicious.append(f)
    return suspicious
