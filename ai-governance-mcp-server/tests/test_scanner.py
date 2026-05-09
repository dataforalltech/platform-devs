"""Testes do scripts/scan_ecosystem.py.

Construímos repos fake usando tmp_path do pytest — evita arquivos versionados
que dessincronizam com o código.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
import yaml

# scripts/ não é package; importamos via path manipulation contido aos testes.
SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS_DIR))

import scan_ecosystem as scanner  # noqa: E402  (import após sys.path)


# --------------------------- helpers de fixture --------------------------- #
def _make_repo(
    base: Path,
    *,
    name: str,
    pyproject_name: str | None = None,
    port: int | None = None,
    libs: list[str] | None = None,
    consumes_urls: list[str] | None = None,
) -> Path:
    """Cria um diretório que parece ser um repo (tem .git/ + pyproject + .env)."""
    repo = base / name
    repo.mkdir(parents=True)
    (repo / ".git").mkdir()  # marker que ativa discover_repo

    if pyproject_name is not None:
        deps = ['"' + lib + '>=1.0"' for lib in (libs or [])]
        deps_block = "[" + ",\n  ".join(deps) + "]" if deps else "[]"
        (repo / "pyproject.toml").write_text(
            f'[project]\nname = "{pyproject_name}"\ndependencies = {deps_block}\n',
            encoding="utf-8",
        )

    env_lines = []
    if port is not None:
        env_lines.append(f"SERVICE_PORT={port}")
    for url_var in consumes_urls or []:
        env_lines.append(f"{url_var}=http://localhost:9000")
    if env_lines:
        (repo / ".env.example").write_text("\n".join(env_lines) + "\n", encoding="utf-8")

    return repo


def _write_yaml(path: Path, services: list[dict], extra_edges: list[dict] | None = None) -> Path:
    nodes = [{"id": "platform-team", "kind": "team"}]
    for svc in services:
        node = {
            "id": svc["id"],
            "kind": "service",
            "status": svc.get("status", "active"),
        }
        if "port" in svc:
            node["port"] = svc["port"]
        if "aliases" in svc:
            node["aliases"] = svc["aliases"]
        nodes.append(node)
    # Libs e contratos referenciados pelas edges precisam existir como nodes.
    for edge in extra_edges or []:
        for endpoint in (edge["from"], edge["to"]):
            if not any(n["id"] == endpoint for n in nodes):
                kind = "library" if endpoint.endswith("-lib") else "contract"
                nodes.append({"id": endpoint, "kind": kind})

    edges = extra_edges or []
    path.write_text(yaml.safe_dump({"nodes": nodes, "edges": edges}), encoding="utf-8")
    return path


# --------------------------- detecção --------------------------- #
def test_discover_picks_pyproject_name(tmp_path):
    repo = _make_repo(tmp_path, name="platform-foo", pyproject_name="platform-foo")
    d = scanner.discover_repo(repo)
    assert d is not None
    assert d.name == "platform-foo"


def test_discover_falls_back_to_basename(tmp_path):
    repo = tmp_path / "platform-bar"
    repo.mkdir()
    (repo / ".git").mkdir()
    d = scanner.discover_repo(repo)
    assert d is not None
    assert d.name == "platform-bar"


def test_discover_returns_none_for_non_repo(tmp_path):
    not_a_repo = tmp_path / "random-folder"
    not_a_repo.mkdir()
    d = scanner.discover_repo(not_a_repo)
    assert d is None


def test_discover_extracts_port_from_env(tmp_path):
    repo = _make_repo(tmp_path, name="x", pyproject_name="x", port=8042)
    d = scanner.discover_repo(repo)
    assert d.port == 8042
    assert ".env.example" in (d.port_source or "")


def test_discover_extracts_libs_from_pyproject(tmp_path):
    repo = _make_repo(
        tmp_path,
        name="x",
        pyproject_name="x",
        libs=["platform-core-lib", "platform-database-lib"],
    )
    d = scanner.discover_repo(repo)
    assert "platform-core-lib" in d.uses_libs
    assert "platform-database-lib" in d.uses_libs


def test_discover_maps_url_env_vars_to_services(tmp_path):
    repo = _make_repo(
        tmp_path,
        name="x",
        pyproject_name="x",
        consumes_urls=["URL_AUTH", "URL_RAG"],
    )
    d = scanner.discover_repo(repo)
    assert "platform-auth" in d.consumes_services
    assert "dataforall-rag-service" in d.consumes_services


def test_discover_ignores_unknown_url_vars(tmp_path):
    repo = _make_repo(
        tmp_path, name="x", pyproject_name="x", consumes_urls=["URL_NONEXISTENT_FOO"]
    )
    d = scanner.discover_repo(repo)
    assert d.consumes_services == set()


# --------------------------- scan + dedup --------------------------- #
def test_scan_skips_non_repo_dirs(tmp_path):
    _make_repo(tmp_path, name="platform-real", pyproject_name="platform-real")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / ".git").mkdir()  # tem .git mas é skipado pelo nome
    (tmp_path / ".cache").mkdir()
    discovered = scanner.scan(tmp_path)
    names = {d.name for d in discovered}
    assert "platform-real" in names
    assert "node_modules" not in names
    assert ".cache" not in names


def test_scan_dedupes_repos_with_same_name(tmp_path):
    """Worktrees do mesmo repo: 2 paths, 1 entry."""
    base_a = tmp_path / "checkout-a"
    base_b = tmp_path / "checkout-b"
    base_a.mkdir()
    base_b.mkdir()
    _make_repo(base_a, name="platform-foo", pyproject_name="platform-foo")
    _make_repo(base_b, name="platform-foo", pyproject_name="platform-foo")

    # Para o scanner ver os dois, eles precisam estar no mesmo parent
    # — mover ambos para tmp_path direto:
    flat = tmp_path / "flat"
    flat.mkdir()
    _make_repo(flat / "wt1", name="platform-foo", pyproject_name="platform-foo")
    _make_repo(flat / "wt2", name="platform-foo", pyproject_name="platform-foo")
    # Cada wtN está dentro de flat/wtN, mas scan(flat) só itera dirs imediatos.
    # Reorganizar: criar dois worktrees como dirs imediatos dentro de flat.

    flat2 = tmp_path / "flat2"
    flat2.mkdir()
    _make_repo(flat2, name="platform-foo", pyproject_name="platform-foo")
    # Para realmente testar dedup, criamos 2 repos com mesmo pyproject name
    # mas em paths diferentes — o scanner deve devolver 1 entry.
    target = tmp_path / "target"
    target.mkdir()
    _make_repo(target, name="repo-one", pyproject_name="platform-foo")
    _make_repo(target, name="repo-two", pyproject_name="platform-foo")
    discovered = scanner.scan(target)
    names = [d.name for d in discovered]
    assert names.count("platform-foo") == 1


# --------------------------- diff (build_report) --------------------------- #
def test_diff_no_drift_when_disk_matches_yaml(tmp_path):
    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()
    _make_repo(
        repos_dir,
        name="platform-foo",
        pyproject_name="platform-foo",
        port=8050,
        libs=["platform-core-lib"],
    )
    yaml_path = _write_yaml(
        tmp_path / "ecosystem.yaml",
        services=[{"id": "platform-foo", "port": 8050}],
        extra_edges=[
            {"from": "platform-foo", "to": "platform-core-lib", "relation": "uses_lib"}
        ],
    )

    discovered = scanner.scan(repos_dir)
    report = scanner.build_report(yaml_path, discovered, repos_dir)
    assert report.conflicts == []
    assert report.lib_drift == []
    assert "platform-foo" in report.consistent


def test_diff_detects_port_conflict(tmp_path):
    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()
    _make_repo(repos_dir, name="x", pyproject_name="platform-foo", port=9999)
    yaml_path = _write_yaml(
        tmp_path / "ecosystem.yaml", services=[{"id": "platform-foo", "port": 8050}]
    )
    report = scanner.build_report(yaml_path, scanner.scan(repos_dir), repos_dir)
    assert len(report.conflicts) == 1
    c = report.conflicts[0]
    assert c["service"] == "platform-foo"
    assert c["yaml_value"] == 8050
    assert c["disk_value"] == 9999


def test_diff_detects_missing_from_yaml(tmp_path):
    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()
    _make_repo(repos_dir, name="x", pyproject_name="brand-new-service", port=8088)
    yaml_path = _write_yaml(tmp_path / "ecosystem.yaml", services=[])
    report = scanner.build_report(yaml_path, scanner.scan(repos_dir), repos_dir)
    assert len(report.missing_from_yaml) == 1
    assert report.missing_from_yaml[0]["name"] == "brand-new-service"


def test_diff_detects_missing_on_disk_active(tmp_path):
    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()
    yaml_path = _write_yaml(
        tmp_path / "ecosystem.yaml",
        services=[
            {"id": "platform-active", "status": "active"},
            {"id": "platform-old", "status": "deprecated"},
        ],
    )
    report = scanner.build_report(yaml_path, scanner.scan(repos_dir), repos_dir)
    active_missing = [m for m in report.missing_on_disk if not m["expected"]]
    expected_missing = [m for m in report.missing_on_disk if m["expected"]]
    assert len(active_missing) == 1
    assert active_missing[0]["id"] == "platform-active"
    assert len(expected_missing) == 1
    assert expected_missing[0]["id"] == "platform-old"


def test_diff_resolves_alias(tmp_path):
    """Se YAML registra alias 'old-name', disco com 'old-name' resolve para canônico."""
    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()
    _make_repo(repos_dir, name="x", pyproject_name="old-name", port=8050)
    yaml_path = _write_yaml(
        tmp_path / "ecosystem.yaml",
        services=[{"id": "canonical-name", "port": 8050, "aliases": ["old-name"]}],
    )
    report = scanner.build_report(yaml_path, scanner.scan(repos_dir), repos_dir)
    assert report.missing_from_yaml == []
    assert "canonical-name" in report.consistent


def test_diff_resolves_basename_when_pyproject_differs(tmp_path):
    """pyproject diz X, basename diz Y; YAML conhece Y como id → resolve por basename."""
    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()
    repo_path = repos_dir / "dataforall-foo"
    repo_path.mkdir()
    (repo_path / ".git").mkdir()
    (repo_path / "pyproject.toml").write_text(
        '[project]\nname = "platform-foo"\n', encoding="utf-8"
    )

    yaml_path = _write_yaml(
        tmp_path / "ecosystem.yaml", services=[{"id": "dataforall-foo"}]
    )
    report = scanner.build_report(yaml_path, scanner.scan(repos_dir), repos_dir)
    assert "dataforall-foo" in report.consistent
    assert report.missing_from_yaml == []


def test_diff_detects_lib_drift_only_on_disk(tmp_path):
    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()
    _make_repo(
        repos_dir,
        name="x",
        pyproject_name="platform-foo",
        port=8050,
        libs=["platform-core-lib", "platform-extra-lib"],
    )
    yaml_path = _write_yaml(
        tmp_path / "ecosystem.yaml",
        services=[{"id": "platform-foo", "port": 8050}],
        extra_edges=[
            {"from": "platform-foo", "to": "platform-core-lib", "relation": "uses_lib"}
        ],
    )
    report = scanner.build_report(yaml_path, scanner.scan(repos_dir), repos_dir)
    assert len(report.lib_drift) == 1
    drift = report.lib_drift[0]
    assert "platform-extra-lib" in drift["only_on_disk"]
    assert drift["only_in_yaml"] == []


# --------------------------- exit code --------------------------- #
def test_has_conflicts_property(tmp_path):
    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()
    _make_repo(repos_dir, name="x", pyproject_name="platform-foo", port=9999)
    yaml_path = _write_yaml(
        tmp_path / "ecosystem.yaml", services=[{"id": "platform-foo", "port": 8050}]
    )
    report = scanner.build_report(yaml_path, scanner.scan(repos_dir), repos_dir)
    assert report.has_conflicts is True
    assert report.has_warnings is False


# --------------------------- render --------------------------- #
def test_render_text_includes_conflicts(tmp_path):
    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()
    _make_repo(repos_dir, name="x", pyproject_name="platform-foo", port=9999)
    yaml_path = _write_yaml(
        tmp_path / "ecosystem.yaml", services=[{"id": "platform-foo", "port": 8050}]
    )
    report = scanner.build_report(yaml_path, scanner.scan(repos_dir), repos_dir)
    text = scanner.render_text(report)
    assert "CONFLICTS" in text
    assert "platform-foo" in text
    assert "8050" in text
    assert "9999" in text


def test_render_json_is_valid_json(tmp_path):
    import json as _json

    repos_dir = tmp_path / "repos"
    repos_dir.mkdir()
    _make_repo(repos_dir, name="x", pyproject_name="platform-foo", port=8050)
    yaml_path = _write_yaml(
        tmp_path / "ecosystem.yaml", services=[{"id": "platform-foo", "port": 8050}]
    )
    report = scanner.build_report(yaml_path, scanner.scan(repos_dir), repos_dir)
    parsed = _json.loads(scanner.render_json(report))
    assert parsed["yaml_services_count"] == 1
    assert parsed["repos_scanned"] == 1
    assert parsed["has_conflicts"] is False


# --------------------------- url var map sanity --------------------------- #
def test_url_var_map_resolves_to_existing_yaml_services():
    """Os IDs no _URL_VAR_TO_SERVICE devem existir no ecosystem.yaml real."""
    project_root = Path(__file__).resolve().parents[1]
    yaml_path = project_root / "knowledge-base" / "ecosystem.yaml"
    data = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    yaml_ids = {n["id"] for n in data.get("nodes") or []}
    for url_var, service_id in scanner._URL_VAR_TO_SERVICE.items():
        assert service_id in yaml_ids, (
            f"{url_var} mapeia para {service_id} mas esse id não existe no ecosystem.yaml"
        )


@pytest.fixture
def isolated_repos(tmp_path):
    """Constrói um pequeno ecosystem fake reutilizável."""
    repos = tmp_path / "repos"
    repos.mkdir()
    _make_repo(repos, name="platform-auth", pyproject_name="platform-auth", port=8001)
    _make_repo(repos, name="platform-admin", pyproject_name="platform-admin", port=8002)
    _make_repo(
        repos,
        name="platform-cdc",
        pyproject_name="platform-cdc",
        port=8017,
        libs=["platform-core-lib"],
        consumes_urls=["URL_AUTH"],
    )
    return repos


def test_realistic_three_service_scan(tmp_path, isolated_repos):
    yaml_path = _write_yaml(
        tmp_path / "ecosystem.yaml",
        services=[
            {"id": "platform-auth", "port": 8001},
            {"id": "platform-admin", "port": 8002},
            {"id": "platform-cdc", "port": 8017},
        ],
        extra_edges=[
            {"from": "platform-cdc", "to": "platform-core-lib", "relation": "uses_lib"},
        ],
    )
    discovered = scanner.scan(isolated_repos)
    assert len(discovered) == 3
    report = scanner.build_report(yaml_path, discovered, isolated_repos)
    assert not report.has_conflicts
    # consume_drift: cdc consume URL_AUTH mas yaml não modela platform-auth como provider de contrato consumido por cdc nessa fixture
    # → esperado aparecer em consume_drift
    drifts = {d["service"] for d in report.consume_drift}
    assert "platform-cdc" in drifts
