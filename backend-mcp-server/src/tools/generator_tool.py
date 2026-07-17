"""Geradores determinísticos de backend (COMPUTE PURO — sem LLM, sem DB).

Diferente das tools stateful (``save_*``/``update_*``), estas tools NÃO tocam o
``BackendStore``: são funções puras ``spec: dict -> dict`` que scaffoldam artefatos
de backend (router FastAPI, camada de service, repositório ORM async, DDL SQL,
migration alembic, fragmento OpenAPI 3.1, política RBAC e schema de eventos) por
template de string.

Contrato de saída (uniforme): cada gerador devolve
``{"artifact": <str|dict>, "filename": <str>, "kind": <str>}`` em caso de sucesso,
ou ``{"error": <slug>, ...}`` quando a spec é inválida.

**Determinismo (requisito duro):** sem ``random``, ``datetime.now``, ``uuid`` ou
qualquer hash de tempo. Chaves de dicionários de entrada (fields/rules/properties)
são renderizadas em ordem alfabética estável, de modo que a MESMA spec produza
SEMPRE o MESMO byte-a-byte. Só depende da stdlib → importável/testável sem banco.

Fronteira de responsabilidade: o gerador FORMATA/scaffolda a spec fornecida; se algum
conteúdo não vier, usa defaults/placeholders sensatos (``raise NotImplementedError``,
``TODO``) — NÃO inventa conteúdo de domínio (isso é do agente).
"""

from __future__ import annotations

import re
from typing import Any

# ── Constantes de suporte ─────────────────────────────────────────────────────
SUPPORTED_HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete"})
SUPPORTED_MIGRATION_OPS = frozenset(
    {"create_table", "drop_table", "add_column", "drop_column", "rename_table", "execute"}
)
_SA_TYPES = {
    "int": "Integer",
    "integer": "Integer",
    "bigint": "BigInteger",
    "str": "String",
    "string": "String",
    "text": "Text",
    "bool": "Boolean",
    "boolean": "Boolean",
    "float": "Float",
    "numeric": "Numeric",
    "decimal": "Numeric",
    "datetime": "DateTime",
    "date": "Date",
    "json": "JSON",
    "uuid": "String",
}
_OPENAPI_TYPES = {
    "int": "integer",
    "integer": "integer",
    "str": "string",
    "string": "string",
    "text": "string",
    "bool": "boolean",
    "boolean": "boolean",
    "float": "number",
    "number": "number",
    "numeric": "number",
    "datetime": "string",
    "date": "string",
    "uuid": "string",
    "object": "object",
    "array": "array",
}

_WORD_SPLIT = re.compile(r"[^0-9a-zA-Z]+")
_PATH_PARAM = re.compile(r"\{([^{}]+)\}")


# ── Helpers de nomes / render (determinísticos) ───────────────────────────────
def _words(name: Any) -> list[str]:
    return [w for w in _WORD_SPLIT.split(str(name)) if w]


def _pascal(name: Any) -> str:
    """Converte snake/kebab/space em PascalCase; fallback estável ``Resource``."""
    return "".join(w[:1].upper() + w[1:] for w in _words(name)) or "Resource"


def _snake(name: Any) -> str:
    """Converte qualquer nome em snake_case; fallback estável ``resource``."""
    return "_".join(w.lower() for w in _words(name)) or "resource"


def _field_pairs(fields: Any) -> list[tuple[str, str]]:
    """Normaliza ``fields`` (list[str] | list[dict] | dict) em pares (name, type)."""
    pairs: list[tuple[str, str]] = []
    if isinstance(fields, dict):
        for key in sorted(fields):
            pairs.append((str(key), str(fields[key])))
        return pairs
    if isinstance(fields, list):
        for item in fields:
            if isinstance(item, dict):
                fname = str(item.get("name", "")).strip()
                ftype = str(item.get("type") or "string").strip()
            else:
                fname, ftype = str(item).strip(), "string"
            if fname:
                pairs.append((fname, ftype))
    return pairs


# ── 1. Router FastAPI ─────────────────────────────────────────────────────────
def generate_fastapi_router(spec: dict[str, Any]) -> dict[str, Any]:
    resource = str(spec.get("resource", "")).strip()
    if not resource:
        return {"error": "missing_resource"}
    routes = spec.get("routes")
    if not isinstance(routes, list) or not routes:
        return {"error": "missing_routes"}

    slug = _snake(resource)
    prefix = str(spec.get("prefix") or f"/{slug}")
    lines: list[str] = [
        "from __future__ import annotations",
        "",
        "from typing import Any",
        "",
        "from fastapi import APIRouter",
        "",
        f'router = APIRouter(prefix="{prefix}", tags=["{slug}"])',
        "",
    ]

    for idx, route in enumerate(routes):
        method = str(route.get("method") or "get").strip().lower()
        if method not in SUPPORTED_HTTP_METHODS:
            return {
                "error": "unsupported_method",
                "method": method,
                "valid": sorted(SUPPORTED_HTTP_METHODS),
            }
        path = str(route.get("path") or "/")
        handler = _snake(route.get("handler") or f"{method}_{slug}_{idx}")
        params = _PATH_PARAM.findall(path)
        sig = ", ".join(f"{_snake(p)}: str" for p in params)
        lines.append(f'@router.{method}("{path}")')
        lines.append(f"async def {handler}({sig}) -> dict[str, Any]:")
        lines.append(f'    """Handler {handler} (scaffold — implementar)."""')
        lines.append("    raise NotImplementedError")
        lines.append("")

    return {
        "artifact": "\n".join(lines).rstrip() + "\n",
        "filename": f"{slug}_router.py",
        "kind": "fastapi_router",
    }


# ── 2. Camada de Service ──────────────────────────────────────────────────────
def _service_signature(method: str) -> tuple[str, str]:
    """Retorna (assinatura_args, tipo_retorno) determinístico p/ um nome de método."""
    n = method.lower()
    if n in ("create", "add", "insert"):
        return "self, payload: dict[str, Any]", "dict[str, Any]"
    if n in ("update", "edit", "modify"):
        return "self, entity_id: Any, payload: dict[str, Any]", "dict[str, Any]"
    if n in ("delete", "remove"):
        return "self, entity_id: Any", "None"
    if n in ("get", "retrieve", "find"):
        return "self, entity_id: Any", "dict[str, Any] | None"
    if n in ("list", "search", "all"):
        return "self, filters: dict[str, Any] | None = None", "list[dict[str, Any]]"
    return "self", "Any"


def generate_service_layer(spec: dict[str, Any]) -> dict[str, Any]:
    entity = str(spec.get("entity", "")).strip()
    if not entity:
        return {"error": "missing_entity"}

    raw_methods = spec.get("methods")
    methods: list[str] = []
    if isinstance(raw_methods, list) and raw_methods:
        for item in raw_methods:
            mname = str(item.get("name", "") if isinstance(item, dict) else item).strip()
            if mname:
                methods.append(mname)
    if not methods:
        methods = ["create", "get", "list", "update", "delete"]

    class_name = f"{_pascal(entity)}Service"
    lines: list[str] = [
        "from __future__ import annotations",
        "",
        "from typing import Any",
        "",
        "",
        f"class {class_name}:",
        f'    """Camada de service para `{_snake(entity)}` (scaffold — implementar)."""',
        "",
        "    def __init__(self, repository: Any) -> None:",
        "        self._repository = repository",
    ]
    for method in methods:
        sig, ret = _service_signature(method)
        lines.append("")
        lines.append(f"    async def {_snake(method)}({sig}) -> {ret}:")
        lines.append(f'        """{_snake(method)} — scaffold, delega ao repository."""')
        lines.append("        raise NotImplementedError")

    return {
        "artifact": "\n".join(lines).rstrip() + "\n",
        "filename": f"{_snake(entity)}_service.py",
        "kind": "service_layer",
    }


# ── 3. Repositório ORM async ──────────────────────────────────────────────────
def generate_repository_layer(spec: dict[str, Any]) -> dict[str, Any]:
    entity = str(spec.get("entity", "")).strip()
    if not entity:
        return {"error": "missing_entity"}

    fields = _field_pairs(spec.get("fields"))
    columns_doc = ", ".join(f"{name} ({ftype})" for name, ftype in fields) or "(sem colunas na spec)"
    class_name = f"{_pascal(entity)}Repository"
    table = _snake(entity)

    lines: list[str] = [
        "from __future__ import annotations",
        "",
        "from typing import Any",
        "",
        "from sqlalchemy import delete as sa_delete",
        "from sqlalchemy import select",
        "from sqlalchemy import update as sa_update",
        "from sqlalchemy.ext.asyncio import AsyncSession",
        "",
        "",
        f"class {class_name}:",
        f'    """Repositório ORM async para `{table}` (scaffold — implementar).',
        "",
        f"    Colunas: {columns_doc}.",
        '    """',
        "",
        f'    __tablename__ = "{table}"',
        "",
        "    def __init__(self, session: AsyncSession) -> None:",
        "        self._session = session",
        "",
        "    async def create(self, data: dict[str, Any]) -> Any:",
        f'        """Insere um registro em `{table}` (scaffold)."""',
        "        raise NotImplementedError",
        "",
        "    async def get(self, entity_id: Any) -> Any:",
        f'        """Busca um registro de `{table}` por id (scaffold)."""',
        "        _ = select  # placeholder de import (implementar query)",
        "        raise NotImplementedError",
        "",
        "    async def list(self, filters: dict[str, Any] | None = None) -> list[Any]:",
        f'        """Lista registros de `{table}` (scaffold)."""',
        "        raise NotImplementedError",
        "",
        "    async def update(self, entity_id: Any, data: dict[str, Any]) -> Any:",
        f'        """Atualiza um registro de `{table}` (scaffold)."""',
        "        _ = sa_update  # placeholder de import (implementar update)",
        "        raise NotImplementedError",
        "",
        "    async def delete(self, entity_id: Any) -> None:",
        f'        """Remove um registro de `{table}` (scaffold)."""',
        "        _ = sa_delete  # placeholder de import (implementar delete)",
        "        raise NotImplementedError",
    ]

    return {
        "artifact": "\n".join(lines).rstrip() + "\n",
        "filename": f"{table}_repository.py",
        "kind": "repository_layer",
    }


# ── 4. DDL SQL (schema de banco) ──────────────────────────────────────────────
def generate_database_schema(spec: dict[str, Any]) -> dict[str, Any]:
    tables = spec.get("tables")
    if not isinstance(tables, list) or not tables:
        return {"error": "missing_tables"}

    blocks: list[str] = []
    for table in tables:
        tname = str(table.get("name", "")).strip()
        if not tname:
            return {"error": "table_missing_name", "table": table}
        columns = table.get("columns")
        if not isinstance(columns, list) or not columns:
            return {"error": "table_missing_columns", "table": tname}

        body: list[str] = []
        pks: list[str] = []
        fks: list[str] = []
        for col in columns:
            cname = str(col.get("name", "")).strip()
            if not cname:
                return {"error": "column_missing_name", "table": tname}
            ctype = str(col.get("type") or "TEXT").strip()
            body.append(f"    {cname} {ctype}")
            if col.get("pk"):
                pks.append(cname)
            fk = col.get("fk")
            if fk:
                fks.append(f"    FOREIGN KEY ({cname}) REFERENCES {fk}")

        if pks:
            body.append(f"    PRIMARY KEY ({', '.join(pks)})")
        body.extend(fks)
        block = f"CREATE TABLE {tname} (\n" + ",\n".join(body) + "\n);"
        blocks.append(block)

    return {
        "artifact": "\n\n".join(blocks) + "\n",
        "filename": "schema.sql",
        "kind": "database_schema",
    }


# ── 5. Migration alembic ──────────────────────────────────────────────────────
def _migration_op_lines(op: Any) -> tuple[str, str] | dict[str, Any]:
    """Renderiza (linha_upgrade, linha_downgrade) para uma op. Erro → dict."""
    if not isinstance(op, dict):
        raw = str(op).replace('"', '\\"')
        return (f'op.execute("{raw}")', f"# TODO reverter manualmente: {raw}")

    kind = str(op.get("op") or "execute").strip().lower()
    if kind not in SUPPORTED_MIGRATION_OPS:
        return {"error": "unsupported_op", "op": kind, "valid": sorted(SUPPORTED_MIGRATION_OPS)}

    table = str(op.get("table", "")).strip()
    column = str(op.get("column", "")).strip()
    sa_type = _SA_TYPES.get(str(op.get("type") or "string").strip().lower(), "String")

    if kind == "create_table":
        return (f'op.create_table("{table}")', f'op.drop_table("{table}")')
    if kind == "drop_table":
        return (f'op.drop_table("{table}")', f'op.create_table("{table}")')
    if kind == "add_column":
        up = f'op.add_column("{table}", sa.Column("{column}", sa.{sa_type}()))'
        return (up, f'op.drop_column("{table}", "{column}")')
    if kind == "drop_column":
        down = f'op.add_column("{table}", sa.Column("{column}", sa.{sa_type}()))'
        return (f'op.drop_column("{table}", "{column}")', down)
    if kind == "rename_table":
        new = str(op.get("new_name", "")).strip()
        return (f'op.rename_table("{table}", "{new}")', f'op.rename_table("{new}", "{table}")')
    raw = str(op.get("sql", "")).replace('"', '\\"')
    return (f'op.execute("{raw}")', f"# TODO reverter manualmente: {raw}")


def generate_migration(spec: dict[str, Any]) -> dict[str, Any]:
    revision = str(spec.get("revision", "")).strip()
    if not revision:
        return {"error": "missing_revision"}
    ops = spec.get("ops")
    if not isinstance(ops, list) or not ops:
        return {"error": "missing_ops"}

    down_revision = spec.get("down_revision")
    down_literal = f'"{down_revision}"' if down_revision else "None"
    message = str(spec.get("message") or f"revision {revision}")

    upgrade: list[str] = []
    downgrade: list[str] = []
    for op in ops:
        rendered = _migration_op_lines(op)
        if isinstance(rendered, dict):
            return rendered
        up, down = rendered
        upgrade.append(f"    {up}")
        downgrade.append(f"    {down}")
    downgrade.reverse()

    header = (
        f'"""{message}\n\n'
        f"Revision ID: {revision}\n"
        f"Revises: {down_revision or ''}\n"
        '"""\n\n'
        "from alembic import op\n"
        "import sqlalchemy as sa\n\n"
        f'revision = "{revision}"\n'
        f"down_revision = {down_literal}\n"
        "branch_labels = None\n"
        "depends_on = None\n\n\n"
    )
    body = (
        "def upgrade() -> None:\n"
        + "\n".join(upgrade)
        + "\n\n\n"
        + "def downgrade() -> None:\n"
        + "\n".join(downgrade)
        + "\n"
    )

    return {
        "artifact": header + body,
        "filename": f"{revision}_migration.py",
        "kind": "migration",
    }


# ── 6. Contrato de API (OpenAPI 3.1 YAML) ─────────────────────────────────────
def generate_api_contract(spec: dict[str, Any]) -> dict[str, Any]:
    title = str(spec.get("title", "")).strip()
    if not title:
        return {"error": "missing_title"}
    paths = spec.get("paths")
    if not isinstance(paths, list) or not paths:
        return {"error": "missing_paths"}

    version = str(spec.get("version") or "1.0.0")
    # Agrupa por path → {method: meta}, ordenado deterministicamente.
    grouped: dict[str, dict[str, dict[str, Any]]] = {}
    for entry in paths:
        if not isinstance(entry, dict):
            return {"error": "invalid_path_entry", "entry": entry}
        path = str(entry.get("path", "")).strip()
        method = str(entry.get("method") or "get").strip().lower()
        if not path:
            return {"error": "path_missing_path", "entry": entry}
        if method not in SUPPORTED_HTTP_METHODS:
            return {
                "error": "unsupported_method",
                "method": method,
                "valid": sorted(SUPPORTED_HTTP_METHODS),
            }
        grouped.setdefault(path, {})[method] = entry

    lines: list[str] = [
        "openapi: 3.1.0",
        "info:",
        f'  title: "{title}"',
        f'  version: "{version}"',
        "paths:",
    ]
    for path in sorted(grouped):
        lines.append(f'  "{path}":')
        for method in sorted(grouped[path]):
            entry = grouped[path][method]
            summary = str(entry.get("summary") or f"{method.upper()} {path}")
            operation_id = _snake(entry.get("operationId") or f"{method}_{path}")
            status = str(entry.get("status") or "200")
            lines.append(f"    {method}:")
            lines.append(f'      summary: "{summary}"')
            lines.append(f"      operationId: {operation_id}")
            lines.append("      responses:")
            lines.append(f'        "{status}":')
            lines.append('          description: "OK"')

    return {
        "artifact": "\n".join(lines) + "\n",
        "filename": "openapi.yaml",
        "kind": "api_contract",
    }


# ── 7. Política de auth (RBAC) ────────────────────────────────────────────────
def generate_auth_policy(spec: dict[str, Any]) -> dict[str, Any]:
    roles = spec.get("roles")
    resources = spec.get("resources")
    if not isinstance(roles, list) or not roles:
        return {"error": "missing_roles"}
    if not isinstance(resources, list) or not resources:
        return {"error": "missing_resources"}

    title = str(spec.get("title") or "RBAC Policy")
    raw_rules = spec.get("rules")
    rules = raw_rules if isinstance(raw_rules, list) else []

    lines: list[str] = [f"# {title}", "", "## Roles", ""]
    lines.extend(f"- {r}" for r in sorted(str(x) for x in roles))
    lines += ["", "## Resources", ""]
    lines.extend(f"- {r}" for r in sorted(str(x) for x in resources))
    lines += ["", "## Rules", "", "| Role | Resource | Actions | Effect |", "| --- | --- | --- | --- |"]

    rendered_rules: list[str] = []
    for rule in rules:
        if not isinstance(rule, dict):
            continue
        role = str(rule.get("role") or "*")
        resource = str(rule.get("resource") or "*")
        actions_raw = rule.get("actions") or ["read"]
        if isinstance(actions_raw, str):
            actions_raw = [actions_raw]
        actions = ", ".join(sorted(str(a) for a in actions_raw))
        effect = str(rule.get("effect") or "allow")
        rendered_rules.append(f"| {role} | {resource} | {actions} | {effect} |")
    if not rendered_rules:
        rendered_rules.append("| * | * | read | deny |")
    lines.extend(sorted(rendered_rules))

    return {
        "artifact": "\n".join(lines) + "\n",
        "filename": "rbac_policy.md",
        "kind": "auth_policy",
    }


# ── 8. Contratos de eventos (schema YAML) ─────────────────────────────────────
def generate_event_contracts(spec: dict[str, Any]) -> dict[str, Any]:
    events = spec.get("events")
    if not isinstance(events, list) or not events:
        return {"error": "missing_events"}

    version = str(spec.get("version") or "1.0")
    normalized: dict[str, list[tuple[str, str]]] = {}
    for event in events:
        if not isinstance(event, dict):
            return {"error": "invalid_event", "event": event}
        name = str(event.get("name", "")).strip()
        if not name:
            return {"error": "event_missing_name", "event": event}
        normalized[name] = _field_pairs(event.get("fields"))

    lines: list[str] = [f'version: "{version}"', "events:"]
    for name in sorted(normalized):
        fields = normalized[name]
        lines.append(f"  {name}:")
        lines.append("    type: object")
        lines.append("    properties:")
        if fields:
            for fname, ftype in fields:
                otype = _OPENAPI_TYPES.get(ftype.lower(), "string")
                lines.append(f"      {fname}:")
                lines.append(f"        type: {otype}")
            lines.append("    required:")
            for fname, _ in fields:
                lines.append(f"      - {fname}")
        else:
            lines.append("      {}")

    return {
        "artifact": "\n".join(lines) + "\n",
        "filename": "events.yaml",
        "kind": "event_contracts",
    }
