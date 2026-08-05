#!/usr/bin/env python3
"""Discover MCP providers and compare every observable tool surface.

This is intentionally static: importing providers can execute startup code,
open network connections, or mutate state.  The audit records evidence and
uses conservative heuristics, so a gap is never presented as proof that an
operation is safe.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.control_plane.manifest_loader import load_catalog  # noqa: E402

SOURCE_SUFFIXES = {".py", ".ts", ".js", ".mjs", ".cjs"}
IGNORED_PARTS = {".git", ".venv", "node_modules", "dist", "build", "__pycache__", ".pytest_cache"}
TOOL_NAME = re.compile(r"^[a-z][a-z0-9]*(?:[_-][a-z0-9]+)*$")
PLACEHOLDER = re.compile(
    r"not[ _-]?implemented|placeholder|(?:#|//|/\*)\s*(?:todo|fixme)\b|"
    r"\bcalled\b|executed successfully|message\s*[:=].{0,80}\b(success|called)\b",
    re.IGNORECASE,
)
FALSE_SUCCESS = re.compile(
    r"approved\s*[:=]\s*true|valid\s*[:=]\s*true|status\s*[:=]\s*['\"]success['\"]|"
    r"commit_sha.{0,80}(random|math\.random)|scenarios\s*:\s*\[\]",
    re.IGNORECASE | re.DOTALL,
)
DESTRUCTIVE = re.compile(r"\b(drop|truncate|delete|destroy|remove|revoke|rotate|apply|merge|push|commit|execute)\b", re.I)
COMMANDS = re.compile(r"subprocess|child_process|\bspawn\s*\(|execFile|os\.system|shell\s*=\s*True", re.I)
EXTERNAL = re.compile(r"httpx|requests\.|fetch\s*\(|axios|urllib|socket\.|grpc|boto3", re.I)
SECRETS = re.compile(r"password|secret|private[_-]?key|access[_-]?token|credential|\.env\b", re.I)
AUTH = re.compile(r"authorization|bearer|authenticate|jwt|signed[_-]?context|context[_-]?signature", re.I)
TENANT = re.compile(r"tenant[_-]?id|tenantresolver|tenant_context", re.I)
AUDIT = re.compile(r"audit|activity[_-]?ledger|log_tool|mcp_tool_audit", re.I)
ERRORS = re.compile(r"try\s*:|except\b|catch\s*\(|raise\b|HTTPException|isError|jsonrpc.*error", re.I | re.S)


def _word_in(name: str, text: str) -> bool:
    """Whole-token membership so ``list`` does not match inside ``blocklist``.

    A tool name only counts as tested or documented when it appears as a complete
    identifier in the corpus; a bare substring collision no longer inflates the
    evidence that feeds the promotion gate.
    """
    return re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", text) is not None


@dataclass
class SurfaceEvidence:
    declared_tools: list[str] = field(default_factory=list)
    listed_tools: list[str] = field(default_factory=list)
    dispatchable_tools: list[str] = field(default_factory=list)
    catalog_tools: list[str] = field(default_factory=list)
    contract_tools: list[str] = field(default_factory=list)
    schema_tools: list[str] = field(default_factory=list)
    output_schema_tools: list[str] = field(default_factory=list)
    tested_tools: list[str] = field(default_factory=list)
    documented_tools: list[str] = field(default_factory=list)


@dataclass
class MCPAudit:
    id: str
    source_path: str
    type: str
    language: str
    runtime: str
    entrypoints: list[str]
    transports: list[str]
    surfaces: SurfaceEvidence
    tools_without_schema: list[str]
    tools_without_output_schema: list[str]
    tools_without_contract: list[str]
    tools_without_catalog: list[str]
    tools_without_tests: list[str]
    tools_without_documentation: list[str]
    tools_without_authorization: list[str]
    tools_without_tenant: list[str]
    tools_without_audit: list[str]
    tools_without_error_handling: list[str]
    tools_with_possible_secret_access: list[str]
    destructive_tools: list[str]
    command_tools: list[str]
    external_call_tools: list[str]
    placeholder_tools: list[str]
    false_success_tools: list[str]
    duplicate_tools: list[str]
    inconsistent_names: list[str]
    stdio_http_divergence: list[str]
    notes: list[str] = field(default_factory=list)


def _files(directory: Path, suffixes: set[str]) -> list[Path]:
    if not directory.is_dir():
        return []
    discovered: list[Path] = []
    for current, directories, filenames in os.walk(directory):
        directories[:] = [name for name in directories if name not in IGNORED_PARTS]
        base = Path(current)
        discovered.extend(
            base / name for name in filenames if (base / name).suffix.lower() in suffixes
        )
    return sorted(discovered)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _looks_like_mcp_implementation(directory: Path) -> bool:
    """Detecta um MCP server pela ESTRUTURA, e não pelo nome do diretório.

    O filtro anterior era ``endswith("-mcp-server") or endswith("-mcp")``, mais um
    caso especial hardcoded para ``devteam-observatory``. Com isso,
    ``cross-devteam-validators`` e ``quality-gates-system`` — que têm entrypoint
    próprio e expõem tools — NUNCA eram enumerados, e qualquer número extraído
    deste script subestimava a frota. Um censo que depende da convenção de nome
    não é censo: é a lista de quem obedeceu à convenção.
    """
    marcadores = (
        Path("src") / "tools" / "index.ts",
        Path("src") / "server.ts",
        Path("src") / "server" / "mcp_server.py",
        Path("src") / "tools" / "__init__.py",
    )
    if any((directory / marcador).is_file() for marcador in marcadores):
        return True
    # Entrypoint Python no topo do diretório (ex.: cross_devteam_validators_mcp.py).
    return any(directory.glob("*_mcp.py")) or any(directory.glob("*-mcp.py"))


def discover_implementations(root: Path) -> list[Path]:
    candidates: set[Path] = set()
    for child in root.iterdir():
        if not child.is_dir() or child.name in IGNORED_PARTS:
            continue
        if (
            child.name.endswith("-mcp-server")
            or child.name.endswith("-mcp")
            or _looks_like_mcp_implementation(child)
        ):
            candidates.add(child)
    services = root / "services"
    if services.is_dir():
        candidates.update(path for path in services.iterdir() if path.is_dir() and "mcp" in path.name)
    for script in root.glob("*-mcp.py"):
        candidates.add(script)
    return sorted(candidates, key=lambda path: path.as_posix())


def _function_name(call: ast.Call) -> str:
    target = call.func
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return ""


def _string_key_dict(value: ast.AST) -> dict[str, ast.AST]:
    if not isinstance(value, ast.Dict):
        return {}
    result: dict[str, ast.AST] = {}
    for key, item in zip(value.keys, value.values):
        if isinstance(key, ast.Constant) and isinstance(key.value, str):
            result[key.value] = item
    return result


def _python_evidence(path: Path) -> tuple[set[str], set[str], set[str], set[str], set[str]]:
    return _python_evidence_source(_read(path))


@lru_cache(maxsize=8192)
def _python_evidence_source(source: str) -> tuple[set[str], set[str], set[str], set[str], set[str]]:
    declared: set[str] = set()
    listed: set[str] = set()
    dispatchable: set[str] = set()
    schemas: set[str] = set()
    outputs: set[str] = set()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return declared, listed, dispatchable, schemas, outputs

    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and _function_name(node).lower() in {"tool", "tooldefinition"}:
            name: str | None = None
            for keyword in node.keywords:
                if keyword.arg == "name" and isinstance(keyword.value, ast.Constant) and isinstance(keyword.value.value, str):
                    name = keyword.value.value
            if name and TOOL_NAME.match(name):
                declared.add(name)
                listed.add(name)
                dispatchable.add(name)
                if any(item.arg in {"input_schema", "inputSchema"} for item in node.keywords):
                    schemas.add(name)
                if any(item.arg in {"output_schema", "outputSchema"} for item in node.keywords):
                    outputs.add(name)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                call = decorator if isinstance(decorator, ast.Call) else None
                target = call.func if call else decorator
                if isinstance(target, ast.Attribute) and target.attr == "tool":
                    name = node.name
                    if call:
                        for keyword in call.keywords:
                            if keyword.arg == "name" and isinstance(keyword.value, ast.Constant):
                                name = str(keyword.value.value)
                    if TOOL_NAME.match(name):
                        declared.add(name)
                        listed.add(name)
                        dispatchable.add(name)
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            target_names = {target.id.lower() for target in targets if isinstance(target, ast.Name)}
            if any("tool" in name or "handler" in name or "dispatch" in name for name in target_names):
                for name, definition in _string_key_dict(value).items():
                    if not TOOL_NAME.match(name):
                        continue
                    declared.add(name)
                    fields = _string_key_dict(definition)
                    if fields:
                        listed.add(name)
                        if fields.keys() & {"inputSchema", "input_schema", "schema"}:
                            schemas.add(name)
                        if fields.keys() & {"outputSchema", "output_schema"}:
                            outputs.add(name)
                    else:
                        dispatchable.add(name)
        if isinstance(node, ast.Compare) and isinstance(node.left, ast.Name) and node.left.id.lower() in {"name", "tool", "tool_name"}:
            for comparator in node.comparators:
                if isinstance(comparator, ast.Constant) and isinstance(comparator.value, str) and TOOL_NAME.match(comparator.value):
                    dispatchable.add(comparator.value)
        if isinstance(node, ast.Match):
            for case in node.cases:
                pattern = case.pattern
                if isinstance(pattern, ast.MatchValue) and isinstance(pattern.value, ast.Constant) and isinstance(pattern.value.value, str):
                    if TOOL_NAME.match(pattern.value.value):
                        dispatchable.add(pattern.value.value)
    return declared, listed, dispatchable, schemas, outputs


def _typescript_evidence(text: str) -> tuple[set[str], set[str], set[str], set[str], set[str]]:
    decorated = set(re.findall(r"(?:server|mcp|registry)\.(?:tool|registerTool)\s*\(\s*['\"]([^'\"]+)['\"]", text))
    object_tools = set(re.findall(r"name\s*:\s*['\"]([a-z][a-z0-9_-]+)['\"]\s*,\s*(?:description|inputSchema)", text))
    names = {name for name in decorated | object_tools if TOOL_NAME.match(name)}
    schemas = {
        name for name in names
        if re.search(rf"name\s*:\s*['\"]{re.escape(name)}['\"][\s\S]{{0,2000}}inputSchema", text)
    }
    outputs = {
        name for name in names
        if re.search(rf"name\s*:\s*['\"]{re.escape(name)}['\"][\s\S]{{0,2500}}outputSchema", text)
    }
    dispatch = set(re.findall(r"(?:case\s+|===?\s*)['\"]([a-z][a-z0-9_-]+)['\"]", text))
    return names, names, dispatch | decorated, schemas, outputs


def _tool_flags(names: Iterable[str], text: str, pattern: re.Pattern[str]) -> list[str]:
    candidates = set(names)
    if not candidates:
        return []
    flagged: set[str] = set()
    # Scan each risk occurrence once. Re-scanning a multi-megabyte bundled
    # provider for every tool made the baseline quadratic.
    for index, match in enumerate(pattern.finditer(text)):
        if index >= 1_000:
            break
        window = text[max(0, match.start() - 300): match.end() + 2500]
        tokens = set(re.findall(r"[a-z][a-z0-9_-]+", window, re.IGNORECASE))
        flagged.update(candidates & tokens)
    return sorted(flagged)


@lru_cache(maxsize=4)
def _catalog_index(root: Path) -> dict[str, set[str]]:
    result: defaultdict[str, set[str]] = defaultdict(set)
    catalog = root / "platform-catalog" / "catalog" / "tools"
    if not catalog.is_dir():
        return result
    for path in catalog.glob("*.yaml"):
        text = _read(path)
        provider_match = re.search(
            r"^\s*(?:provider_id|mcp_id|server)\s*:\s*['\"]?([a-z0-9-]+)", text, re.M
        )
        tool_match = re.search(r"^\s*tool\s*:\s*['\"]?([a-z][a-z0-9_-]+)", text, re.M)
        if provider_match and tool_match:
            result[provider_match.group(1)].add(tool_match.group(1))
    return dict(result)


def _catalog_tools(root: Path, provider: str) -> set[str]:
    return set(_catalog_index(root).get(provider, set()))


def _identity(path: Path, catalog: Any) -> tuple[str, str, Any | None]:
    relative = path.relative_to(ROOT).as_posix()
    for manifest in catalog.manifests.values():
        paths = [manifest.ownership.source_path, *manifest.ownership.legacy_source_paths]
        if relative in {item for item in paths if item}:
            inferred = path.name.removesuffix("-server")
            return inferred if relative in manifest.ownership.legacy_source_paths else manifest.id, manifest.classification.type, manifest
    name = path.stem if path.is_file() else path.name
    return name.removesuffix("-server"), "unregistered", None


# Artefatos GERADOS que vivem sob docs/ e não são documentação. O relatório desta
# própria auditoria lista o nome de todas as tools da frota; sem esta exclusão, a
# primeira execução escreve o baseline e a SEGUINTE passa a considerar toda tool
# "documentada" porque o nome dela aparece no relatório. É evidência circular
# alimentando o gate de promoção — e era a causa de duas execuções consecutivas
# produzirem números diferentes.
_DOCS_GERADOS = (
    Path("docs") / "reviews" / "mcp-tools-quality-baseline.md",
    Path("docs") / "generated",
)


def _e_doc_gerado(path: Path, root: Path) -> bool:
    try:
        relativo = path.relative_to(root)
    except ValueError:
        return False
    return any(relativo == alvo or alvo in relativo.parents for alvo in _DOCS_GERADOS)


def audit_repository(root: Path = ROOT) -> list[MCPAudit]:
    catalog = load_catalog(root)
    records: list[MCPAudit] = []
    duplicate_index: defaultdict[str, list[int]] = defaultdict(list)
    docs_text = "\n".join(
        _read(path)
        for path in _files(root / "docs", {".md", ".rst"})
        if not _e_doc_gerado(path, root)
    )

    for implementation in discover_implementations(root):
        provider, provider_type, manifest = _identity(implementation, catalog)
        source_files = [implementation] if implementation.is_file() else _files(implementation, SOURCE_SUFFIXES)
        production = [
            path for path in source_files
            if "tests" not in {part.lower() for part in path.parts}
            and not path.name.lower().startswith("test_")
            and not path.name.lower().endswith(".test.ts")
        ]
        tests = [path for path in source_files if "test" in path.name.lower() or "tests" in {part.lower() for part in path.parts}]
        declared: set[str] = set()
        listed: set[str] = set()
        dispatchable: set[str] = set()
        schema_tools: set[str] = set()
        output_tools: set[str] = set()
        for path in production:
            evidence = _python_evidence(path) if path.suffix == ".py" else _typescript_evidence(_read(path))
            for target, values in zip((declared, listed, dispatchable, schema_tools, output_tools), evidence):
                target.update(values)
        all_tools = declared | listed | dispatchable
        source_text = "\n".join(_read(path) for path in production)
        if "create_mcp_app" in source_text:
            source_text += "\n" + _read(root / "shared" / "secure_runtime.py")
        test_text = "\n".join(_read(path) for path in tests)
        local_docs = "\n".join(_read(path) for path in source_files if path.suffix.lower() in {".md", ".rst"})
        documented = {
            name for name in all_tools if _word_in(name, docs_text) or _word_in(name, local_docs)
        }
        tested = {name for name in all_tools if _word_in(name, test_text)}
        contracts = {name for (contract_provider, name) in catalog.contracts if contract_provider == provider}
        catalog_names = _catalog_tools(root, provider)
        language = "mixed" if {path.suffix for path in production} & {".py"} and {path.suffix for path in production} & {".ts", ".js"} else ("python" if any(path.suffix == ".py" for path in production) else "typescript")
        entrypoints = sorted(path.relative_to(root).as_posix() for path in production if path.name in {"mcp_server.py", "server.py", "index.ts", "server.ts", "main.py"})
        transports: list[str] = []
        transport_text = source_text.lower()
        if "stdio" in transport_text:
            transports.append("stdio")
        if "fastapi" in transport_text or "express" in transport_text or "/mcp/tools" in transport_text:
            transports.append("http")
        if manifest:
            transports = [name for name, enabled in (("stdio", manifest.transport.stdio), ("http", manifest.transport.http)) if enabled]
        if not transports:
            transports.append("unknown")
        surfaces = SurfaceEvidence(
            declared_tools=sorted(declared), listed_tools=sorted(listed), dispatchable_tools=sorted(dispatchable),
            catalog_tools=sorted(catalog_names), contract_tools=sorted(contracts), schema_tools=sorted(schema_tools),
            output_schema_tools=sorted(output_tools), tested_tools=sorted(tested), documented_tools=sorted(documented),
        )
        # Authorization/tenant/audit are proven at PROVIDER granularity, not per tool:
        # for providers built on the shared secure runtime (create_mcp_app, appended to
        # source_text above) enforcement is centralized, so one match legitimately clears
        # every tool. A handler that bypassed the runtime would not be extracted as a tool
        # here — treat these as coarse, provider-level signals rather than per-tool proof.
        auth_missing = [] if AUTH.search(source_text) else sorted(all_tools)
        tenant_missing = [] if TENANT.search(source_text) else sorted(all_tools)
        audit_missing = [] if AUDIT.search(source_text) else sorted(all_tools)
        error_missing = [] if ERRORS.search(source_text) else sorted(all_tools)
        divergence = sorted((listed ^ dispatchable)) if set(transports) == {"stdio", "http"} else []
        notes: list[str] = []
        if not all_tools:
            notes.append("No tool names could be proven statically; inspect dynamic registration manually.")
        if manifest is None:
            notes.append("Implementation is absent from the canonical manifest catalog.")
        record = MCPAudit(
            id=provider,
            source_path=implementation.relative_to(root).as_posix(),
            type=provider_type,
            language=language,
            runtime=manifest.runtime.mode if manifest else "unregistered",
            entrypoints=entrypoints,
            transports=transports,
            surfaces=surfaces,
            tools_without_schema=sorted(all_tools - schema_tools),
            tools_without_output_schema=sorted(all_tools - output_tools),
            tools_without_contract=sorted(all_tools - contracts),
            tools_without_catalog=sorted(all_tools - catalog_names),
            tools_without_tests=sorted(all_tools - tested),
            tools_without_documentation=sorted(all_tools - documented),
            tools_without_authorization=auth_missing,
            tools_without_tenant=tenant_missing,
            tools_without_audit=audit_missing,
            tools_without_error_handling=error_missing,
            tools_with_possible_secret_access=_tool_flags(all_tools, source_text, SECRETS),
            destructive_tools=_tool_flags(all_tools, source_text, DESTRUCTIVE),
            command_tools=_tool_flags(all_tools, source_text, COMMANDS),
            external_call_tools=_tool_flags(all_tools, source_text, EXTERNAL),
            placeholder_tools=_tool_flags(all_tools, source_text, PLACEHOLDER),
            false_success_tools=_tool_flags(all_tools, source_text, FALSE_SUCCESS),
            duplicate_tools=[],
            inconsistent_names=sorted(name for name in all_tools if not TOOL_NAME.match(name)),
            stdio_http_divergence=divergence,
            notes=notes,
        )
        records.append(record)
        for name in all_tools:
            duplicate_index[name].append(len(records) - 1)

    for name, indexes in duplicate_index.items():
        if len(indexes) > 1:
            for index in indexes:
                records[index].duplicate_tools.append(name)
    for record in records:
        record.duplicate_tools.sort()
    return records


def _count(record: MCPAudit, field_name: str) -> int:
    return len(getattr(record.surfaces, field_name))


def render_markdown(records: list[MCPAudit]) -> str:
    totals = Counter()
    for record in records:
        for field_name in SurfaceEvidence.__dataclass_fields__:
            totals[field_name] += _count(record, field_name)
    lines = [
        "# MCP tools quality baseline",
        "",
        "> Generated by `scripts/audit_mcp_tools.py`. Static evidence is conservative; a flagged item requires review and is not proof of exploitability.",
        "",
        "## Surface comparison",
        "",
        "| MCP | Source | Declared | Listed | Dispatchable | Catalog | Contract | Input schema | Output schema | Tested | Documented |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for record in records:
        lines.append(
            f"| `{record.id}` | `{record.source_path}` | {_count(record, 'declared_tools')} | {_count(record, 'listed_tools')} | "
            f"{_count(record, 'dispatchable_tools')} | {_count(record, 'catalog_tools')} | {_count(record, 'contract_tools')} | "
            f"{_count(record, 'schema_tools')} | {_count(record, 'output_schema_tools')} | {_count(record, 'tested_tools')} | {_count(record, 'documented_tools')} |"
        )
    lines.extend([
        f"| **Total evidence** | — | {totals['declared_tools']} | {totals['listed_tools']} | {totals['dispatchable_tools']} | {totals['catalog_tools']} | {totals['contract_tools']} | {totals['schema_tools']} | {totals['output_schema_tools']} | {totals['tested_tools']} | {totals['documented_tools']} |",
        "",
        "## Findings by MCP",
        "",
    ])
    gap_fields = (
        "tools_without_schema", "tools_without_output_schema", "tools_without_contract", "tools_without_catalog",
        "tools_without_tests", "tools_without_documentation",
        "tools_without_authorization", "tools_without_tenant", "tools_without_audit",
        "tools_without_error_handling", "tools_with_possible_secret_access", "destructive_tools",
        "command_tools", "external_call_tools", "placeholder_tools", "false_success_tools",
        "duplicate_tools", "inconsistent_names", "stdio_http_divergence",
    )
    for record in records:
        lines.extend([
            f"### `{record.id}` — `{record.source_path}`", "",
            f"- Type/language/runtime: `{record.type}` / `{record.language}` / `{record.runtime}`",
            f"- Entrypoints: {', '.join(f'`{item}`' for item in record.entrypoints) or 'not proven'}",
            f"- Transports: {', '.join(f'`{item}`' for item in record.transports)}",
        ])
        for field_name in gap_fields:
            values = getattr(record, field_name)
            if values:
                lines.append(f"- {field_name}: {', '.join(f'`{item}`' for item in values)}")
        for note in record.notes:
            lines.append(f"- Note: {note}")
        lines.append("")
    lines.extend([
        "## Interpretation and gate",
        "",
        "The executable gateway surface is the enforcement boundary. A provider may only be promoted when every listed and dispatchable tool has matching input/output schemas, a canonical contract, behavior tests, tenant-aware authorization, audit evidence, and equivalent HTTP/stdio behavior where both transports are enabled. `--fail-on-runtime-gaps` enforces this rule for gateway-enabled providers.",
        "",
    ])
    return "\n".join(lines)


def runtime_gaps(records: list[MCPAudit], root: Path = ROOT) -> list[str]:
    catalog = load_catalog(root)
    gateway_enabled = {item.id for item in catalog.manifests.values() if item.gateway.enabled and item.runtime.exposes_tools}
    errors: list[str] = []
    for record in records:
        if record.id not in gateway_enabled:
            continue
        for field_name in (
            "tools_without_schema", "tools_without_output_schema", "tools_without_contract", "tools_without_catalog",
            "tools_without_tests", "tools_without_documentation",
            "tools_without_authorization", "tools_without_tenant", "tools_without_audit",
            "tools_without_error_handling", "placeholder_tools", "false_success_tools", "stdio_http_divergence",
        ):
            values = getattr(record, field_name)
            if values:
                errors.append(f"{record.id}: {field_name}: {', '.join(values)}")
    return errors


_BASELINE_MD = Path("docs/reviews/mcp-tools-quality-baseline.md")
_BASELINE_JSON = Path("generated/mcp-tools-audit.json")


def _evidence_payload(records: list) -> str:
    payload = {
        "schema_version": 1,
        "repository": "dataforalltech/platform-devs",
        "mcps": [asdict(item) for item in records],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False) + "\n"


def _check_drift(records: list, markdown: str) -> int:
    """Compara os artefatos versionados com o que o HEAD produz agora.

    Existe porque os números de maturidade envelheceram em silêncio: o
    `mcp-tools-audit.json` versionado ficou semanas atrás do código, e qualquer
    documento que o citasse citava número errado. O `generate_mcp_artifacts.py`
    já tinha um `--check` para os artefatos derivados do manifesto; estes dois
    não tinham dono nenhum.
    """
    esperado = {_BASELINE_MD: markdown, _BASELINE_JSON: _evidence_payload(records)}
    drift: list[str] = []
    for relativo, conteudo in esperado.items():
        caminho = ROOT / relativo
        if not caminho.is_file():
            drift.append(f"missing generated artifact: {relativo.as_posix()}")
        elif caminho.read_text(encoding="utf-8") != conteudo:
            drift.append(f"generated artifact drift: {relativo.as_posix()}")

    if drift:
        for item in drift:
            print(f"ERROR: {item}", file=sys.stderr)
        print(
            "Regenere com: python scripts/audit_mcp_tools.py "
            f"--output {_BASELINE_MD.as_posix()} --json-output {_BASELINE_JSON.as_posix()}",
            file=sys.stderr,
        )
        return 1
    print("OK: quality baseline matches the current tree", file=sys.stderr)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, help="write the Markdown report")
    parser.add_argument("--json-output", type=Path, help="write machine-readable evidence")
    parser.add_argument("--fail-on-runtime-gaps", action="store_true")
    parser.add_argument(
        "--check",
        action="store_true",
        help="não escreve; sai com 1 se os artefatos versionados estiverem defasados",
    )
    args = parser.parse_args()
    records = audit_repository(ROOT)
    markdown = render_markdown(records)

    if args.check:
        return _check_drift(records, markdown)

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(markdown, encoding="utf-8", newline="\n")
    else:
        print(markdown)
    if args.json_output:
        args.json_output.parent.mkdir(parents=True, exist_ok=True)
        args.json_output.write_text(_evidence_payload(records), encoding="utf-8", newline="\n")
    gaps = runtime_gaps(records)
    if args.fail_on_runtime_gaps and gaps:
        for gap in gaps:
            print(f"ERROR: {gap}", file=sys.stderr)
        return 1
    print(f"Audited {len(records)} MCP implementations", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
