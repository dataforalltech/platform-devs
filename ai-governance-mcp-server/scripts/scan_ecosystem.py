"""scan_ecosystem.py — detector de drift entre ecosystem.yaml e os repositórios reais.

Varre `--path` (parent dos repos) procurando diretórios com `.git/`. Para cada
repo, extrai:

- **Nome canônico** — `pyproject.toml::project.name` (preferido) ou basename do dir.
- **Porta** — primeiro hit em `.env.defaults`/`.env.example`/`.env.local-dev`
  (`SERVICE_PORT=...` ou `APP_PORT=...`); fallback para `docker-compose.yml`.
- **uses_lib** — deps em `pyproject.toml` ou `requirements.txt` que casam
  `platform-*-lib`.
- **consumes** — env vars `URL_*` em `.env*` mapeadas para o serviço canônico
  via `_URL_VAR_TO_SERVICE`.

Compara contra `knowledge-base/ecosystem.yaml` e imprime um relatório de drift
com conflitos (porta diferente), faltantes (no YAML ou no disco), drift de libs.

Uso:
    python scripts/scan_ecosystem.py
    python scripts/scan_ecosystem.py --path ../../..
    python scripts/scan_ecosystem.py --format json
    python scripts/scan_ecosystem.py --output drift-report.txt

Exit codes:
    0 — sem conflito (warnings ok)
    1 — conflito (porta divergente, lib drift)
    2 — input inválido (path não existe, YAML inválido)

Este script NÃO altera o YAML — só reporta. A regravação fica para humano +
PR explícito.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# --------------------------------------------------------------------- #
# Mapeamento env URL → service canônico                                  #
# --------------------------------------------------------------------- #
# Mantido explícito: 18 entradas, fácil de revisar/atualizar.
_URL_VAR_TO_SERVICE: dict[str, str] = {
    "URL_AUTH": "platform-auth",
    "URL_IAM": "platform-admin",
    "URL_ADMIN": "platform-admin",
    "URL_GOVERNANCE": "platform-governance",
    "URL_ANALYTICS": "platform-analytics",
    "URL_SCHEDULER": "platform-scheduler",
    "URL_CONNECTORS": "platform-connectors",
    "URL_ML": "platform-ml",
    "URL_CLOUD": "platform-cloud",
    "URL_MONITOR": "platform-monitor",
    "URL_NOTIFICATION": "platform-notification",
    "URL_COMMUNICATION": "platform-communication",
    "URL_DATAQUALITY": "platform-dataquality",
    "URL_DOCEXTRACT": "platform-docextract",
    "URL_AGENTS_FACTORY": "dataforall-agents-factory",
    "URL_RAG": "dataforall-rag-service",
    "URL_DATALAKE": "platform-datalake",
    "URL_CDC": "platform-cdc",
    "URL_API_GATEWAY": "platform-api-gateway",
    "URL_ICEBERG": "platform-iceberg",
    "URL_FLOW": "platform-flow",
    "URL_SECURITY": "platform-security",
}

# Arquivos onde procurar SERVICE_PORT (em ordem de prioridade).
_ENV_FILES = (
    ".env.defaults",
    ".env.example",
    ".env.local-dev",
    ".env.cloud-dev",
    ".env",
)

# Regex para extrair porta de env files.
_PORT_RE = re.compile(r"^\s*(?:SERVICE_PORT|APP_PORT|PORT)\s*=\s*(\d{2,5})\s*$", re.MULTILINE)
# Regex para porta em docker-compose: `${SERVICE_PORT:-8014}:8000` ou `8014:8000`.
_COMPOSE_PORT_RE = re.compile(
    r"\$\{SERVICE_PORT:-(\d{4,5})\}:|\"(\d{4,5}):\d+\""
)
# Regex para URL_X env vars.
_URL_ENV_RE = re.compile(r"^\s*(URL_[A-Z_]+)\s*=", re.MULTILINE)
# Regex para libs privadas em deps (PEP 508 + nomes lib).
_LIB_DEP_RE = re.compile(
    r"\b(platform[-_][a-z0-9]+[-_]lib)\b", re.IGNORECASE
)


# --------------------------------------------------------------------- #
# Estruturas                                                             #
# --------------------------------------------------------------------- #
@dataclass
class DiscoveredService:
    """O que o scanner achou em um repo individual."""

    name: str
    repo_path: Path
    port: int | None = None
    port_source: str | None = None
    uses_libs: set[str] = field(default_factory=set)
    consumes_services: set[str] = field(default_factory=set)
    sources: dict[str, str] = field(default_factory=dict)


@dataclass
class DriftReport:
    """Resultado da comparação YAML × disco."""

    scanned_path: Path
    yaml_source: Path
    repos_scanned: int
    discovered: list[DiscoveredService]
    yaml_services: dict[str, dict]  # service_id -> attrs

    conflicts: list[dict] = field(default_factory=list)
    missing_from_yaml: list[dict] = field(default_factory=list)
    missing_on_disk: list[dict] = field(default_factory=list)
    lib_drift: list[dict] = field(default_factory=list)
    consume_drift: list[dict] = field(default_factory=list)
    consistent: list[str] = field(default_factory=list)

    @property
    def has_conflicts(self) -> bool:
        return bool(self.conflicts)

    @property
    def has_warnings(self) -> bool:
        return bool(
            self.missing_from_yaml
            or self.missing_on_disk
            or self.lib_drift
            or self.consume_drift
        )


# --------------------------------------------------------------------- #
# Detecção                                                               #
# --------------------------------------------------------------------- #
def _read_text(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def _detect_name(repo_path: Path) -> str:
    """Tenta pyproject.toml::project.name primeiro; cai pro basename."""
    pyproject = repo_path / "pyproject.toml"
    if pyproject.exists():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
            name = data.get("project", {}).get("name")
            if name:
                return name.strip()
            poetry_name = data.get("tool", {}).get("poetry", {}).get("name")
            if poetry_name:
                return poetry_name.strip()
        except (tomllib.TOMLDecodeError, OSError):
            pass
    return repo_path.name


def _detect_port(repo_path: Path) -> tuple[int | None, str | None]:
    """Retorna (port, source_path) ou (None, None)."""
    for env_name in _ENV_FILES:
        env_path = repo_path / env_name
        text = _read_text(env_path)
        if text is None:
            continue
        match = _PORT_RE.search(text)
        if match:
            return int(match.group(1)), f"{env_name}:{text[:match.start()].count(chr(10)) + 1}"

    # Fallback: docker-compose.yml | docker-compose.local.yml
    for compose_name in ("docker-compose.yml", "docker-compose.local.yml"):
        compose = repo_path / compose_name
        text = _read_text(compose)
        if text is None:
            continue
        match = _COMPOSE_PORT_RE.search(text)
        if match:
            port = match.group(1) or match.group(2)
            return int(port), compose_name
    return None, None


def _detect_libs(repo_path: Path) -> set[str]:
    """Match `platform-*-lib` em pyproject.toml e requirements.txt."""
    libs: set[str] = set()
    for filename in ("pyproject.toml", "requirements.txt"):
        text = _read_text(repo_path / filename)
        if text is None:
            continue
        for match in _LIB_DEP_RE.finditer(text):
            normalized = match.group(1).replace("_", "-").lower()
            libs.add(normalized)
    return libs


def _detect_consumes(repo_path: Path) -> set[str]:
    """Lê URL_* env vars de todos os .env* e mapeia para service canônico."""
    consumed: set[str] = set()
    for env_name in _ENV_FILES:
        text = _read_text(repo_path / env_name)
        if text is None:
            continue
        for match in _URL_ENV_RE.finditer(text):
            var = match.group(1)
            service = _URL_VAR_TO_SERVICE.get(var)
            if service:
                consumed.add(service)
    return consumed


def discover_repo(repo_path: Path) -> DiscoveredService | None:
    """Detecta os signals de um repo. Retorna None se não parecer um repo válido."""
    if not (repo_path / ".git").exists() and not (repo_path / ".git").is_dir():
        # .git pode ser um arquivo (worktree) — aceita também
        git_marker = repo_path / ".git"
        if not git_marker.exists():
            return None

    name = _detect_name(repo_path)
    port, port_source = _detect_port(repo_path)
    libs = _detect_libs(repo_path)
    consumes = _detect_consumes(repo_path)

    return DiscoveredService(
        name=name,
        repo_path=repo_path,
        port=port,
        port_source=port_source,
        uses_libs=libs,
        consumes_services=consumes,
    )


# --------------------------------------------------------------------- #
# Diff                                                                   #
# --------------------------------------------------------------------- #
def _yaml_services(yaml_data: dict) -> dict[str, dict]:
    """Index dos nodes de kind=service no YAML."""
    result: dict[str, dict] = {}
    for node in yaml_data.get("nodes") or []:
        if node.get("kind") == "service":
            result[node["id"]] = node
    return result


def _yaml_uses_lib(yaml_data: dict, service_id: str) -> set[str]:
    libs: set[str] = set()
    for edge in yaml_data.get("edges") or []:
        if edge.get("from") == service_id and edge.get("relation") == "uses_lib":
            libs.add(edge["to"])
    return libs


def _yaml_consumes(yaml_data: dict, service_id: str) -> set[str]:
    """Quais serviços (não contratos) o `service_id` consome.

    Resolve via contratos: edge `consumes`/`consumes_event` → contrato →
    quem `provides_api`/`produces_event` → service.
    """
    consumed_contracts: set[str] = set()
    for edge in yaml_data.get("edges") or []:
        if edge.get("from") == service_id and edge.get("relation") in {
            "consumes",
            "consumes_event",
        }:
            consumed_contracts.add(edge["to"])

    consumed_services: set[str] = set()
    for contract in consumed_contracts:
        for edge in yaml_data.get("edges") or []:
            if edge.get("to") == contract and edge.get("relation") in {
                "provides_api",
                "produces_event",
            }:
                consumed_services.add(edge["from"])
    return consumed_services


def _resolve_canonical(
    candidates: list[str],
    yaml_services: dict[str, dict],
) -> str | None:
    """Tenta resolver vários candidatos de nome contra o YAML.

    Aceita lista (ex.: [pyproject_name, basename]) e devolve o primeiro hit:
    1. match direto no id
    2. match em `aliases`
    """
    for cand in candidates:
        if cand in yaml_services:
            return cand
    for service_id, attrs in yaml_services.items():
        aliases = attrs.get("aliases") or []
        for cand in candidates:
            if cand in aliases:
                return service_id
    return None


def build_report(
    yaml_path: Path,
    discovered: list[DiscoveredService],
    scanned_path: Path,
) -> DriftReport:
    yaml_data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    if not isinstance(yaml_data, dict):
        raise ValueError(f"YAML root deve ser mapping em {yaml_path}")

    yaml_svcs = _yaml_services(yaml_data)
    report = DriftReport(
        scanned_path=scanned_path,
        yaml_source=yaml_path,
        repos_scanned=len(discovered),
        discovered=discovered,
        yaml_services=yaml_svcs,
    )

    matched_yaml_ids: set[str] = set()

    # Cada disco vs YAML
    for d in discovered:
        # Candidatos: pyproject name + basename do dir (cobre divergência entre os dois).
        candidates = [d.name]
        basename = d.repo_path.name
        if basename != d.name:
            candidates.append(basename)
        canonical_id = _resolve_canonical(candidates, yaml_svcs)
        if canonical_id is None:
            report.missing_from_yaml.append(
                {
                    "name": d.name,
                    "path": str(d.repo_path),
                    "port": d.port,
                    "uses_libs": sorted(d.uses_libs),
                }
            )
            continue

        matched_yaml_ids.add(canonical_id)
        yaml_attrs = yaml_svcs[canonical_id]
        consistent = True

        # Conflito de porta
        if d.port is not None and yaml_attrs.get("port") is not None:
            if int(d.port) != int(yaml_attrs["port"]):
                report.conflicts.append(
                    {
                        "service": canonical_id,
                        "field": "port",
                        "yaml_value": int(yaml_attrs["port"]),
                        "disk_value": int(d.port),
                        "disk_source": f"{d.repo_path}/{d.port_source}",
                    }
                )
                consistent = False

        # Drift de libs
        yaml_libs = _yaml_uses_lib(yaml_data, canonical_id)
        only_yaml = yaml_libs - d.uses_libs
        only_disk = d.uses_libs - yaml_libs
        if only_yaml or only_disk:
            report.lib_drift.append(
                {
                    "service": canonical_id,
                    "only_in_yaml": sorted(only_yaml),
                    "only_on_disk": sorted(only_disk),
                }
            )
            consistent = False

        # Drift de consumes (serviços). Filtro de ruído: ignoramos quando o
        # YAML tem mais (modelagem mais rica do que o .env declara). Reportamos
        # apenas quando o disco tem URL_X que o YAML não modela como consumes.
        yaml_cons = _yaml_consumes(yaml_data, canonical_id)
        only_disk_c = d.consumes_services - yaml_cons
        if only_disk_c:
            report.consume_drift.append(
                {
                    "service": canonical_id,
                    "missing_in_yaml": sorted(only_disk_c),
                }
            )
            consistent = False

        if consistent:
            report.consistent.append(canonical_id)

    # YAML services não vistos no disco
    for sid, attrs in yaml_svcs.items():
        if sid in matched_yaml_ids:
            continue
        report.missing_on_disk.append(
            {
                "id": sid,
                "status": attrs.get("status", "active"),
                "expected": attrs.get("status") == "deprecated",
            }
        )

    return report


# --------------------------------------------------------------------- #
# Renderização                                                           #
# --------------------------------------------------------------------- #
def render_text(report: DriftReport) -> str:
    lines = [
        "ECOSYSTEM DRIFT REPORT",
        "=" * 60,
        f"Scanned: {report.scanned_path}",
        f"YAML:    {report.yaml_source}",
        f"Repos:   {report.repos_scanned} | Services in YAML: {len(report.yaml_services)}",
        "",
    ]

    if report.conflicts:
        lines.append(f"X CONFLICTS ({len(report.conflicts)})")
        for c in report.conflicts:
            lines.append(
                f"  {c['service']} ({c['field']}): "
                f"yaml={c['yaml_value']} disk={c['disk_value']}"
            )
            lines.append(f"    source: {c['disk_source']}")
        lines.append("")

    if report.missing_from_yaml:
        lines.append(f"+ MISSING FROM YAML ({len(report.missing_from_yaml)})")
        for m in report.missing_from_yaml:
            port = f"port={m['port']}" if m["port"] else "no port"
            lines.append(f"  {m['name']} ({port}, libs={m['uses_libs']})")
            lines.append(f"    path: {m['path']}")
        lines.append("")

    if report.missing_on_disk:
        unexpected = [m for m in report.missing_on_disk if not m["expected"]]
        expected = [m for m in report.missing_on_disk if m["expected"]]
        if unexpected:
            lines.append(f"! MISSING ON DISK ({len(unexpected)} active)")
            for m in unexpected:
                lines.append(f"  {m['id']} (status={m['status']})")
            lines.append("")
        if expected:
            lines.append(f"  (deprecated services not on disk, expected: {len(expected)})")
            for m in expected:
                lines.append(f"    {m['id']}")
            lines.append("")

    if report.lib_drift:
        lines.append(f"~ LIB DRIFT ({len(report.lib_drift)})")
        for d in report.lib_drift:
            if d["only_in_yaml"]:
                lines.append(
                    f"  {d['service']}: only in yaml = {d['only_in_yaml']}"
                )
            if d["only_on_disk"]:
                lines.append(
                    f"  {d['service']}: only on disk = {d['only_on_disk']}"
                )
        lines.append("")

    if report.consume_drift:
        lines.append(f"~ CONSUME DRIFT ({len(report.consume_drift)})")
        for d in report.consume_drift:
            lines.append(
                f"  {d['service']}: disk has URL_X for {d['missing_in_yaml']} "
                "but yaml does not declare these as consumed"
            )
        lines.append("")

    if report.consistent:
        lines.append(f"= CONSISTENT ({len(report.consistent)})")
        lines.append(f"  {', '.join(report.consistent)}")
        lines.append("")

    if not report.has_conflicts and not report.has_warnings:
        lines.append("Nothing to report. ecosystem.yaml matches the filesystem.")

    return "\n".join(lines)


def render_json(report: DriftReport) -> str:
    return json.dumps(
        {
            "scanned_path": str(report.scanned_path),
            "yaml_source": str(report.yaml_source),
            "repos_scanned": report.repos_scanned,
            "yaml_services_count": len(report.yaml_services),
            "conflicts": report.conflicts,
            "missing_from_yaml": report.missing_from_yaml,
            "missing_on_disk": report.missing_on_disk,
            "lib_drift": report.lib_drift,
            "consume_drift": report.consume_drift,
            "consistent": report.consistent,
            "has_conflicts": report.has_conflicts,
            "has_warnings": report.has_warnings,
        },
        indent=2,
        ensure_ascii=False,
    )


# --------------------------------------------------------------------- #
# Entrypoint                                                             #
# --------------------------------------------------------------------- #
# Diretórios que não são "diretórios de repos" — pulados pelo auto-detect e
# pelo scan iterator, mesmo que contenham subdirs com .git/.
_NON_REPO_DIR_NAMES = {
    ".claude",
    "worktrees",
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    ".tox",
    ".pytest_cache",
}


def _autodetect_scan_path(project_root: Path) -> Path:
    """Sobe na árvore procurando um diretório com >=2 subdirs com `.git/`.

    Pula nomes em `_NON_REPO_DIR_NAMES` (ex.: `.claude/`, `worktrees/`) que
    são containers operacionais de worktree, não diretórios de repos reais.
    """
    current = project_root.parent
    fallback = current
    while current != current.parent:
        if current.name in _NON_REPO_DIR_NAMES:
            current = current.parent
            continue
        try:
            repo_count = sum(
                1
                for c in current.iterdir()
                if c.is_dir()
                and c.name not in _NON_REPO_DIR_NAMES
                and not c.name.startswith(".")
                and (c / ".git").exists()
            )
        except PermissionError:
            break
        if repo_count >= 2:
            return current
        current = current.parent
    return fallback


def scan(parent_path: Path) -> list[DiscoveredService]:
    """Itera os subdiretórios de `parent_path` que parecem ser repos.

    Deduplica por nome de serviço — se o mesmo nome aparece em múltiplos paths
    (ex.: vários worktrees do mesmo repo coexistindo), mantemos só o primeiro
    e adicionamos os outros em `extra_paths` para visibilidade no relatório.
    """
    if not parent_path.is_dir():
        raise FileNotFoundError(f"path não é diretório: {parent_path}")

    found: dict[str, DiscoveredService] = {}
    for child in sorted(parent_path.iterdir()):
        if not child.is_dir():
            continue
        if child.name in _NON_REPO_DIR_NAMES or child.name.startswith("."):
            continue
        d = discover_repo(child)
        if d is None:
            continue
        if d.name in found:
            existing = found[d.name]
            existing.sources.setdefault("extra_paths", str(existing.repo_path))
            existing.sources["extra_paths"] += f"; {d.repo_path}"
            continue
        found[d.name] = d
    return list(found.values())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument(
        "--path",
        type=Path,
        default=None,
        help="Diretório pai dos repos. Default: parents do projeto MCP.",
    )
    parser.add_argument(
        "--ecosystem",
        type=Path,
        default=None,
        help="Caminho do ecosystem.yaml. Default: knowledge-base/ecosystem.yaml.",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Salvar em arquivo. Default: stdout.",
    )
    args = parser.parse_args()

    project_root = Path(__file__).resolve().parents[1]
    ecosystem_path = args.ecosystem or (project_root / "knowledge-base" / "ecosystem.yaml")
    scan_path = args.path or _autodetect_scan_path(project_root)

    if not ecosystem_path.exists():
        print(f"ecosystem.yaml não encontrado: {ecosystem_path}", file=sys.stderr)
        return 2
    if not scan_path.exists():
        print(f"path não existe: {scan_path}", file=sys.stderr)
        return 2

    try:
        discovered = scan(scan_path)
        report = build_report(ecosystem_path, discovered, scan_path)
    except (yaml.YAMLError, ValueError, FileNotFoundError) as e:
        print(f"erro: {e}", file=sys.stderr)
        return 2

    rendered = render_json(report) if args.format == "json" else render_text(report)
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered)

    return 1 if report.has_conflicts else 0


if __name__ == "__main__":
    sys.exit(main())
