"""Catálogo de tools + dispatcher do domínio *guardian* (ADR-018, consolidado no devteam-mcp).

Estrutura idêntica aos demais domínios: `_TOOL_DEFS` (description+schema por op),
`_POLICY_SPEC` (resource_type, ação), `_meta()` expande em capability/required_scope/
data_domain, `_TOOL_SCHEMAS` = chaves de op SEM prefixo (o `plugin.register()` prefixa
`guardian_`), e `dispatch(name, args, store)` roteia op → método do `GuardianStore`.

Fase 1: CRUD do núcleo versionado das diretrizes + referência (kinds/status).
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from .db.store import (
    CONFORMANCE_STATUS,
    KIND_CAPABILITIES,
    RELATION_TYPES,
    SCOPE_RANK,
    STATUS_VOCAB,
    WAIVER_STATUS,
    GuardianStore,
    GuardianValidationError,
)
from .importer import parse_traceability_matrix, scan_hub

DOMAIN = "guardian"

_POLICY_SPEC: dict[str, tuple[str, str]] = {
    "create_directive": ("directive", "write"),
    "get_directive": ("directive", "read"),
    "list_directives": ("directive", "read"),
    "update_directive": ("directive", "write"),
    "set_directive_status": ("directive", "write"),
    "supersede_directive": ("directive", "write"),
    "seed_reference_data": ("reference", "write"),
    "list_kinds": ("reference", "read"),
    "list_status_vocab": ("reference", "read"),
    "import_hub": ("hub_import", "write"),
    "validate_hub": ("hub_import", "read"),
    "set_lcr_detail": ("lcr", "write"),
    "get_lcr_detail": ("lcr", "read"),
    "list_lcr_substitutions": ("lcr", "read"),
    "replace_sections": ("section", "write"),
    "list_sections": ("section", "read"),
    "add_relation": ("relation", "write"),
    "list_relations": ("relation", "read"),
    "remove_relation": ("relation", "write"),
    "import_traceability_matrix": ("relation", "write"),
    "set_conformance_control": ("conformance", "write"),
    "get_conformance_control": ("conformance", "read"),
    "list_conformance_controls": ("conformance", "read"),
    "conformance_summary": ("conformance", "read"),
    "create_waiver": ("waiver", "write"),
    "list_waivers": ("waiver", "read"),
    "revoke_waiver": ("waiver", "write"),
    "expire_waiver": ("waiver", "write"),
    "sweep_expired_waivers": ("waiver", "write"),
}

# resource_type → data_domain (guardian é governança).
_DATA_DOMAIN: dict[str, str] = {
    "directive": "governance",
    "reference": "governance",
    "hub_import": "governance",
    "lcr": "governance",
    "section": "governance",
    "relation": "governance",
    "conformance": "governance",
    "waiver": "governance",
}

_KINDS = sorted(KIND_CAPABILITIES)
_STATUS = sorted(STATUS_VOCAB)
_CONFORMANCE_STATUS = sorted(CONFORMANCE_STATUS)
_WAIVER_STATUS = sorted(WAIVER_STATUS)
_SCOPES = sorted(SCOPE_RANK)

_UID = {
    "type": "string",
    "minLength": 1,
    "maxLength": 64,
    "description": "ID canônico imutável (ex.: STD-SEC-001, ADR-0005, P-005).",
}  # noqa: E501

_TOOL_DEFS: dict[str, dict[str, Any]] = {
    "create_directive": {
        "description": (
            "Cria uma diretriz (cabeçalho + versão v1). directive_uid é o ID canônico imutável; "
            "kind/status/scope validados contra o vocabulário. Erro se o uid já existe "
            "(use update_directive)."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "directive_uid": _UID,
                "kind": {"type": "string", "enum": _KINDS},
                "title": {"type": "string", "minLength": 1, "maxLength": 300},
                "scope": {"type": "string", "enum": _SCOPES, "default": "platform"},
                "project_ref": {
                    "type": "string",
                    "maxLength": 64,
                    "description": "Obrigatório sse scope='project' (ref fraca ao project-product).",
                },  # noqa: E501
                "archetype_ref": {
                    "type": "string",
                    "maxLength": 64,
                    "description": "Obrigatório sse scope='archetype' (ref fraca ao registro de arquétipo).",
                },  # noqa: E501
                "owner_ref": {"type": "string", "maxLength": 64},
                "status": {"type": "string", "enum": _STATUS, "default": "proposto"},
                "body_context": {
                    "type": "string",
                    "description": "Prosa: Contexto/Enunciado/Racional.",
                },
                "body_decision": {
                    "type": "string",
                    "description": "Prosa da Decisão (ADR).",
                },
                "author_ref": {"type": "string", "maxLength": 64},
            },
            "required": ["directive_uid", "kind", "title"],
        },
    },
    "get_directive": {
        "description": "Retorna uma diretriz com a versão vigente.",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"directive_uid": _UID},
            "required": ["directive_uid"],
        },
    },
    "list_directives": {
        "description": (
            "Lista diretrizes (filtros: kind/scope/project_ref/status), "
            "com status/versão vigente."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "kind": {"type": "string", "enum": _KINDS},
                "scope": {"type": "string", "enum": _SCOPES},
                "project_ref": {"type": "string", "maxLength": 64},
                "archetype_ref": {"type": "string", "maxLength": 64},
                "status": {"type": "string", "enum": _STATUS},
                "limit": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 200,
                    "default": 50,
                },
            },
        },
    },
    "update_directive": {
        "description": (
            "Cria uma NOVA versão da diretriz (append-only) e a torna vigente atomicamente. "
            "Não muta versões anteriores."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "directive_uid": _UID,
                "status": {"type": "string", "enum": _STATUS, "default": "proposto"},
                "body_context": {"type": "string"},
                "body_decision": {"type": "string"},
                "change_reason": {"type": "string"},
                "author_ref": {"type": "string", "maxLength": 64},
            },
            "required": ["directive_uid"],
        },
    },
    "set_directive_status": {
        "description": "Transição de lifecycle: atualiza o status da versão vigente (sem nova versão).",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "directive_uid": _UID,
                "status": {"type": "string", "enum": _STATUS},
            },
            "required": ["directive_uid", "status"],
        },
    },
    "supersede_directive": {
        "description": "Marca a diretriz como substituída por outra (superseded_by_uid); versão vigente vira 'substituido'.",  # noqa: E501
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"directive_uid": _UID, "superseded_by_uid": _UID},
            "required": ["directive_uid", "superseded_by_uid"],
        },
    },
    "seed_reference_data": {
        "description": "Semeia (idempotente) as capacidades de kind e o vocabulário de status no tenant.",
        "schema": {"type": "object", "additionalProperties": False, "properties": {}},
    },
    "list_kinds": {
        "description": "Lista as capacidades por kind (camada, RFC2119, file:line, forma do corpo).",
        "schema": {"type": "object", "additionalProperties": False, "properties": {}},
    },
    "list_status_vocab": {
        "description": "Lista o vocabulário de status.",
        "schema": {"type": "object", "additionalProperties": False, "properties": {}},
    },
    "import_hub": {
        "description": (
            "Importa markdown→DB as 10 camadas do hub de governança (principles/adr/"
            "standards/reference-architecture/runbooks/it/decisions + lib-change-"
            "requests/handoffs/specs) a partir de hub_root (caminho local para a raiz "
            "'docs/' do platform-service-template ou equivalente). Idempotente: cria "
            "diretrizes novas, versiona as que mudaram, não toca as iguais; também "
            "sincroniza metadados de LCR, seções tipadas e arestas governado_por "
            "(Fase 2). Erros de parsing (parse_errors) e de validação de negócio "
            "(persist_errors — ex.: status fora do vocabulário) são coletados POR "
            "ARQUIVO, sem abortar o lote inteiro. Não importa a matriz de "
            "rastreabilidade central (use guardian_import_traceability_matrix)."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "hub_root": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Caminho local absoluto para a pasta 'docs/' do hub.",
                }
            },
            "required": ["hub_root"],
        },
    },
    "validate_hub": {
        "description": (
            "Dry-run do import_hub: reporta drift entre o filesystem e o que está "
            "persistido (diretrizes que seriam criadas/atualizadas, diretivas órfãs "
            "no DB sem arquivo correspondente, erros de parsing) SEM escrever nada. "
            "Não é paridade completa com scripts/validate_hub.py do template (que "
            "cobre templates YAML/K8s/segurança/SoA — fora do escopo do guardian, "
            "que é registry+policy, não executor) — cobre só a governança documental."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "hub_root": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Caminho local absoluto para a pasta 'docs/' do hub.",
                }
            },
            "required": ["hub_root"],
        },
    },
    "set_lcr_detail": {
        "description": (
            "Cria/atualiza (upsert por directive_uid) os metadados de gestão de "
            "mudança de um Library Change Request — biblioteca/repositorio/versões/"
            "tipo/breaking/urgencia/aprovador/solicitante/achado/data_solicitacao. "
            "Não versiona (não faz parte do núcleo append-only de directive_version)."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "directive_uid": _UID,
                "biblioteca": {"type": "string", "maxLength": 120},
                "repositorio": {"type": "string", "maxLength": 200},
                "versao_atual": {"type": "string", "maxLength": 32},
                "versao_alvo": {"type": "string", "maxLength": 32},
                "tipo": {
                    "type": "string",
                    "enum": ["patch", "minor", "major", "nao-aplicavel"],
                },
                "breaking": {"type": "boolean", "default": False},
                "urgencia": {
                    "type": "string",
                    "enum": ["critical", "high", "medium", "low", "nao-aplicavel"],
                },
                "aprovador": {"type": "string", "maxLength": 64},
                "solicitante": {"type": "string", "maxLength": 120},
                "achado": {
                    "type": "string",
                    "maxLength": 64,
                    "description": "Ref a control id de auditoria (ex.: CRY-02).",
                },
                "data_solicitacao": {
                    "type": "string",
                    "maxLength": 10,
                    "description": "YYYY-MM-DD, imutável (distinto de última atualização).",
                },
            },
            "required": ["directive_uid"],
        },
    },
    "get_lcr_detail": {
        "description": "Retorna os metadados de gestão de mudança de um LCR (ou null se não houver).",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"directive_uid": _UID},
            "required": ["directive_uid"],
        },
    },
    "list_lcr_substitutions": {
        "description": (
            "Lista os alvos de substituido_por de um LCR (arestas — normalizadas do "
            "front-matter, nunca uma lista serializada em coluna)."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"directive_uid": _UID},
            "required": ["directive_uid"],
        },
    },
    "replace_sections": {
        "description": (
            "Substitui TODAS as seções de uma (directive_uid, version) atomicamente "
            "(full-replace, não merge) — corpo tipado por heading (ADR-018 Fase 2). "
            "Sem version, usa a versão vigente."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "directive_uid": _UID,
                "version": {"type": "integer", "minimum": 1},
                "sections": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "order_index": {"type": "integer", "minimum": 0},
                            "section_key": {"type": "string", "maxLength": 80},
                            "heading": {"type": "string", "maxLength": 200},
                            "content": {"type": "string"},
                        },
                        "required": ["order_index", "section_key", "heading"],
                    },
                },
            },
            "required": ["directive_uid", "sections"],
        },
    },
    "list_sections": {
        "description": (
            "Lista as seções tipadas de uma diretriz (versão vigente se `version` "
            "for omitido), em ordem."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "directive_uid": _UID,
                "version": {"type": "integer", "minimum": 1},
            },
            "required": ["directive_uid"],
        },
    },
    "add_relation": {
        "description": (
            "Cria uma aresta tipada entre diretrizes (governed_by ou "
            "traces_to_<principle|standard|reference_arch|runbook|adr>) — cobre o "
            "campo governado_por do front-matter e a matriz de rastreabilidade de "
            "documentation-model.md. Idempotente por (from_uid, to_ref, relation_type)."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "from_uid": _UID,
                "to_ref": {
                    "type": "string",
                    "maxLength": 200,
                    "description": "Ref FRACA (uid/caminho livre, pode ser externo ao guardian).",
                },  # noqa: E501
                "relation_type": {
                    "type": "string",
                    "enum": sorted(RELATION_TYPES),
                },
            },
            "required": ["from_uid", "to_ref", "relation_type"],
        },
    },
    "list_relations": {
        "description": "Lista as arestas de uma diretriz (filtro opcional por relation_type).",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "from_uid": _UID,
                "relation_type": {"type": "string", "enum": sorted(RELATION_TYPES)},
            },
            "required": ["from_uid"],
        },
    },
    "remove_relation": {
        "description": "Remove uma aresta específica (from_uid, to_ref, relation_type).",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "from_uid": _UID,
                "to_ref": {"type": "string", "maxLength": 200},
                "relation_type": {"type": "string", "enum": sorted(RELATION_TYPES)},
            },
            "required": ["from_uid", "to_ref", "relation_type"],
        },
    },
    "import_traceability_matrix": {
        "description": (
            "Importa a matriz de rastreabilidade central (documentation-model.md: "
            "tabela ADR -> Princípios/Standards/Reference Arch./Runbooks) como "
            "arestas traces_to_* em gov_directive_relation. Diferente de import_hub "
            "(um arquivo por diretriz), esta é UMA tabela central que referencia "
            "várias diretrizes por ID textual. Linhas cujo ADR não bate com a "
            "convenção de 4 dígitos (ex. referência externa citada por prosa) são "
            "puladas, não erram. `model_path` aponta para o arquivo "
            "documentation-model.md (ou equivalente)."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "model_path": {
                    "type": "string",
                    "minLength": 1,
                    "description": "Caminho local absoluto para documentation-model.md.",
                }
            },
            "required": ["model_path"],
        },
    },
    "set_conformance_control": {
        "description": (
            "Cria/atualiza (upsert por project_ref+control_id) o estado de "
            "conformidade de um projeto frente a um control de governança. "
            "evidence é obrigatório sse status='pass'; reason é obrigatório para "
            "qualquer outro status (mesma regra do service-conformance.yaml do hub)."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "project_ref": {"type": "string", "maxLength": 64},
                "control_id": {"type": "string", "maxLength": 64},
                "status": {"type": "string", "enum": _CONFORMANCE_STATUS},
                "reason": {"type": "string"},
                "evidence": {"type": "string"},
                "directive_uid": _UID,
                "assessed_by": {"type": "string", "maxLength": 64},
                "assessed_at": {
                    "type": "string",
                    "maxLength": 10,
                    "description": "YYYY-MM-DD.",
                },
            },
            "required": ["project_ref", "control_id", "status"],
        },
    },
    "get_conformance_control": {
        "description": "Retorna o estado de conformidade de um control específico (ou null).",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "project_ref": {"type": "string", "maxLength": 64},
                "control_id": {"type": "string", "maxLength": 64},
            },
            "required": ["project_ref", "control_id"],
        },
    },
    "list_conformance_controls": {
        "description": "Lista os controls de um projeto (filtro opcional por status).",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "project_ref": {"type": "string", "maxLength": 64},
                "status": {"type": "string", "enum": _CONFORMANCE_STATUS},
            },
            "required": ["project_ref"],
        },
    },
    "conformance_summary": {
        "description": "Contagem de controls por status para um projeto (calculado ao vivo).",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"project_ref": {"type": "string", "maxLength": 64}},
            "required": ["project_ref"],
        },
    },
    "create_waiver": {
        "description": (
            "Cria uma exceção temporária a um control — SEMPRE com validade "
            "(expires_on) e aprovador; upsert por project_ref+control_id+expires_on "
            "(renovar com validade diferente cria um novo registro)."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "project_ref": {"type": "string", "maxLength": 64},
                "control_id": {"type": "string", "maxLength": 64},
                "approver_ref": {"type": "string", "maxLength": 64},
                "expires_on": {
                    "type": "string",
                    "maxLength": 10,
                    "description": "YYYY-MM-DD, obrigatório.",
                },
                "justification": {"type": "string"},
            },
            "required": ["project_ref", "control_id", "approver_ref", "expires_on"],
        },
    },
    "list_waivers": {
        "description": "Lista waivers de um projeto (filtros opcionais: control_id, status).",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "project_ref": {"type": "string", "maxLength": 64},
                "control_id": {"type": "string", "maxLength": 64},
                "status": {"type": "string", "enum": _WAIVER_STATUS},
            },
            "required": ["project_ref"],
        },
    },
    "revoke_waiver": {
        "description": "Marca um waiver como revogado (status='revoked').",
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"waiver_id": {"type": "integer", "minimum": 1}},
            "required": ["waiver_id"],
        },
    },
    "expire_waiver": {
        "description": (
            "Marca um waiver como expirado (status='expired') — marcação "
            "EXPLÍCITA, esta fase não calcula expiração automaticamente a "
            "partir de expires_on na leitura."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"waiver_id": {"type": "integer", "minimum": 1}},
            "required": ["waiver_id"],
        },
    },
    "sweep_expired_waivers": {
        "description": (
            "Varre waivers 'active' cujo expires_on já passou e marca como "
            "'expired' — resolve de fato o 'hoje > expires_on' (ao contrário de "
            "expire_waiver, que é uma marcação manual por id). project_ref "
            "opcional restringe a varredura a um projeto."
        ),
        "schema": {
            "type": "object",
            "additionalProperties": False,
            "properties": {"project_ref": {"type": "string", "maxLength": 64}},
        },
    },
}


def _meta(name: str) -> dict[str, Any]:
    resource_type, action = _POLICY_SPEC[name]
    defn = _TOOL_DEFS[name]
    return {
        "description": defn["description"],
        "capability": f"devteam-mcp.{DOMAIN}_{name}",
        "required_scope": f"{DOMAIN}:{resource_type}:{action}",
        "resource_type": resource_type,
        "data_domain": _DATA_DOMAIN.get(resource_type, "governance"),
        "schema": defn["schema"],
    }


_TOOL_SCHEMAS: dict[str, dict[str, Any]] = {name: _meta(name) for name in _TOOL_DEFS}


async def _import_hub(store: GuardianStore, hub_root: str) -> dict[str, Any]:
    docs, errors = scan_hub(Path(hub_root))
    results: list[dict[str, Any]] = []
    # Erro de PERSISTÊNCIA (ex.: status fora do vocabulário — drift real do hub,
    # como "APPROVED" maiúsculo em inglês num LCR em vez do vocabulário PT-BR)
    # não pode derrubar o lote inteiro: um GuardianValidationError num arquivo
    # perderia o resultado de TODOS os outros já importados com sucesso (mesmo
    # padrão de resiliência de scan_hub.parse_errors, aplicado agora também à
    # camada de persistência).
    persist_errors: list[dict[str, str]] = []
    for doc in docs:
        try:
            results.append(await store.import_directive(doc))
        except GuardianValidationError as exc:
            persist_errors.append(
                {
                    "directive_uid": doc.directive_uid,
                    "source_path": doc.source_path,
                    "error": str(exc),
                }
            )
    counts = Counter(r["action"] for r in results)
    mismatches = [r for r in results if r.get("kind_scope_mismatch")]
    return {
        "hub_root": hub_root,
        "scanned": len(docs) + len(errors),
        "created": counts.get("created", 0),
        "updated": counts.get("updated", 0),
        "unchanged": counts.get("unchanged", 0),
        "parse_errors": errors,
        "persist_errors": persist_errors,
        "kind_scope_mismatches": mismatches,
    }


async def _validate_hub(store: GuardianStore, hub_root: str) -> dict[str, Any]:
    docs, errors = scan_hub(Path(hub_root))
    uids: set[str] = set()
    drift: list[dict[str, Any]] = []
    for doc in docs:
        uids.add(doc.directive_uid)
        existing = await store.get_directive(doc.directive_uid)
        if existing is None:
            drift.append({"directive_uid": doc.directive_uid, "drift": "missing_in_db"})
            continue
        current = existing.get("current_version")
        out_of_sync = current is None or (
            current["status"] != doc.status
            or (current.get("body_context") or None) != (doc.body_context or None)
            or (current.get("body_decision") or None) != (doc.body_decision or None)
            or (existing.get("title") or None) != (doc.title or None)
        )
        if out_of_sync:
            drift.append(
                {"directive_uid": doc.directive_uid, "drift": "content_out_of_sync"}
            )
    orphans = await store.diff_hub(uids)
    return {
        "hub_root": hub_root,
        "scanned": len(docs) + len(errors),
        "parse_errors": errors,
        "drift": drift,
        "orphan_directives": orphans,
        "in_sync": not drift and not orphans and not errors,
    }


async def _resolve_current_version(store: GuardianStore, directive_uid: str) -> int:
    directive = await store.get_directive(directive_uid)
    if directive is None or directive.get("current_version") is None:
        raise GuardianValidationError(
            f"directive_uid não encontrado ou sem versão vigente: {directive_uid!r}"
        )
    return directive["current_version"]["version"]


async def _import_traceability_matrix(
    store: GuardianStore, model_path: str
) -> dict[str, Any]:
    text = Path(model_path).read_text(encoding="utf-8")
    parsed = parse_traceability_matrix(text)
    for relation in parsed["relations"]:
        await store.add_relation(
            from_uid=relation["from_uid"],
            to_ref=relation["to_ref"],
            relation_type=relation["relation_type"],
        )
    return {
        "model_path": model_path,
        "relations_added": len(parsed["relations"]),
        "exceptions": parsed["exceptions"],
        "skipped_rows": parsed["skipped_rows"],
    }


async def dispatch(
    name: str, args: dict[str, Any], store: GuardianStore
) -> dict[str, Any]:
    """Despacha op → método do store (async). Erros de validação viram envelope de erro."""
    a = args
    try:
        if name == "create_directive":
            return await store.create_directive(
                directive_uid=a["directive_uid"],
                kind=a["kind"],
                title=a["title"],
                scope=a.get("scope", "platform"),
                project_ref=a.get("project_ref"),
                archetype_ref=a.get("archetype_ref"),
                owner_ref=a.get("owner_ref"),
                status=a.get("status", "proposto"),
                body_context=a.get("body_context"),
                body_decision=a.get("body_decision"),
                author_ref=a.get("author_ref"),
            )
        if name == "get_directive":
            result = await store.get_directive(a["directive_uid"])
            return (
                result
                if result
                else {"error": "not_found", "directive_uid": a["directive_uid"]}
            )
        if name == "list_directives":
            return {
                "directives": await store.list_directives(
                    kind=a.get("kind"),
                    scope=a.get("scope"),
                    project_ref=a.get("project_ref"),
                    archetype_ref=a.get("archetype_ref"),
                    status=a.get("status"),
                    limit=a.get("limit", 50),
                )
            }
        if name == "update_directive":
            return await store.update_directive(
                directive_uid=a["directive_uid"],
                status=a.get("status", "proposto"),
                body_context=a.get("body_context"),
                body_decision=a.get("body_decision"),
                change_reason=a.get("change_reason"),
                author_ref=a.get("author_ref"),
            )
        if name == "set_directive_status":
            return await store.set_directive_status(
                directive_uid=a["directive_uid"], status=a["status"]
            )
        if name == "supersede_directive":
            return await store.supersede_directive(
                directive_uid=a["directive_uid"],
                superseded_by_uid=a["superseded_by_uid"],
            )
        if name == "seed_reference_data":
            return await store.seed_reference_data()
        if name == "list_kinds":
            return {"kinds": await store.list_kinds()}
        if name == "list_status_vocab":
            return {"status": await store.list_status_vocab()}
        if name == "import_hub":
            return await _import_hub(store, a["hub_root"])
        if name == "validate_hub":
            return await _validate_hub(store, a["hub_root"])
        if name == "set_lcr_detail":
            uid = a["directive_uid"]
            fields = {k: v for k, v in a.items() if k != "directive_uid"}
            return await store.set_lcr_detail(directive_uid=uid, **fields)
        if name == "get_lcr_detail":
            result = await store.get_lcr_detail(a["directive_uid"])
            return (
                result
                if result
                else {"error": "not_found", "directive_uid": a["directive_uid"]}
            )
        if name == "list_lcr_substitutions":
            return {
                "substitutions": await store.list_lcr_substitutions(a["directive_uid"])
            }
        if name == "replace_sections":
            return {
                "sections": await store.replace_sections(
                    directive_uid=a["directive_uid"],
                    version=a.get("version")
                    or await _resolve_current_version(store, a["directive_uid"]),
                    sections=a["sections"],
                )
            }
        if name == "list_sections":
            return {
                "sections": await store.list_sections(
                    a["directive_uid"], version=a.get("version")
                )
            }
        if name == "add_relation":
            await store.add_relation(
                from_uid=a["from_uid"],
                to_ref=a["to_ref"],
                relation_type=a["relation_type"],
            )
            return {"ok": True}
        if name == "list_relations":
            return {
                "relations": await store.list_relations(
                    a["from_uid"], relation_type=a.get("relation_type")
                )
            }
        if name == "remove_relation":
            await store.remove_relation(
                from_uid=a["from_uid"],
                to_ref=a["to_ref"],
                relation_type=a["relation_type"],
            )
            return {"ok": True}
        if name == "import_traceability_matrix":
            return await _import_traceability_matrix(store, a["model_path"])
        if name == "set_conformance_control":
            fields = {
                k: v for k, v in a.items() if k not in ("project_ref", "control_id")
            }
            return await store.set_conformance_control(
                project_ref=a["project_ref"], control_id=a["control_id"], **fields
            )
        if name == "get_conformance_control":
            result = await store.get_conformance_control(
                a["project_ref"], a["control_id"]
            )
            return (
                result
                if result
                else {
                    "error": "not_found",
                    "project_ref": a["project_ref"],
                    "control_id": a["control_id"],
                }
            )
        if name == "list_conformance_controls":
            return {
                "controls": await store.list_conformance_controls(
                    a["project_ref"], status=a.get("status")
                )
            }
        if name == "conformance_summary":
            return await store.conformance_summary(a["project_ref"])
        if name == "create_waiver":
            return await store.create_waiver(
                project_ref=a["project_ref"],
                control_id=a["control_id"],
                approver_ref=a["approver_ref"],
                expires_on=a["expires_on"],
                justification=a.get("justification"),
            )
        if name == "list_waivers":
            return {
                "waivers": await store.list_waivers(
                    a["project_ref"],
                    control_id=a.get("control_id"),
                    status=a.get("status"),
                )
            }
        if name == "revoke_waiver":
            await store.revoke_waiver(a["waiver_id"])
            return {"ok": True}
        if name == "expire_waiver":
            await store.expire_waiver(a["waiver_id"])
            return {"ok": True}
        if name == "sweep_expired_waivers":
            return {
                "expired": await store.sweep_expired_waivers(
                    project_ref=a.get("project_ref")
                )
            }
    except GuardianValidationError as exc:
        return {"error": "ValidationError", "details": str(exc)}
    raise KeyError(name)
