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
    KIND_CAPABILITIES,
    SCOPE_RANK,
    STATUS_VOCAB,
    GuardianStore,
    GuardianValidationError,
)
from .importer import scan_hub

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
}

# resource_type → data_domain (guardian é governança).
_DATA_DOMAIN: dict[str, str] = {
    "directive": "governance",
    "reference": "governance",
    "hub_import": "governance",
    "lcr": "governance",
}

_KINDS = sorted(KIND_CAPABILITIES)
_STATUS = sorted(STATUS_VOCAB)
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
            "diretrizes novas, versiona as que mudaram, não toca as iguais; LCR também "
            "sincroniza metadados de gestão de mudança (guardian_get_lcr_detail) e "
            "arestas substituido_por. FORA de escopo: relações governado_por/matriz "
            "de rastreabilidade (Fase 2)."
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
    results = [await store.import_directive(doc) for doc in docs]
    counts = Counter(r["action"] for r in results)
    mismatches = [r for r in results if r.get("kind_scope_mismatch")]
    return {
        "hub_root": hub_root,
        "scanned": len(docs) + len(errors),
        "created": counts.get("created", 0),
        "updated": counts.get("updated", 0),
        "unchanged": counts.get("unchanged", 0),
        "parse_errors": errors,
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
    except GuardianValidationError as exc:
        return {"error": "ValidationError", "details": str(exc)}
    raise KeyError(name)
