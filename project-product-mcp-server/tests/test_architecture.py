import ast
import configparser
from pathlib import Path

import yaml

SERVICE = Path(__file__).resolve().parents[1]
ROOT = SERVICE.parent


def test_alembic_config_is_linux_parser_compatible():
    raw = (SERVICE / "alembic.ini").read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    parser = configparser.ConfigParser()
    parser.read_string(raw.decode("utf-8"))
    assert parser.get("alembic", "script_location") == "alembic"


def test_trinity_boundaries_and_multi_engine_release_contract():
    assert (SERVICE / "app/main.py").is_file()
    assert (SERVICE / "src/platform_project_product/client.py").is_file()
    assert (SERVICE / "mcp/project_product_mcp/server/mcp_server.py").is_file()
    app_main = (SERVICE / "app/main.py").read_text(encoding="utf-8").lower()
    assert "migrate" not in app_main
    migration = (SERVICE / "alembic/versions/0001_project_product.py").read_text(encoding="utf-8")
    assert "pg_advisory_xact_lock" in migration
    assert "GET_LOCK" in migration
    assert "emit_ddl" in migration
    profile = yaml.safe_load((SERVICE / "deploy/service-profile.yaml").read_text(encoding="utf-8"))
    assert profile["persistence"]["tenantEngine"] == "registry-resolved"
    assert profile["persistence"]["supportedTenantEngines"] == ["postgresql", "mysql"]
    assert profile["persistence"]["migrations"]["strategy"] == "release-job"


def test_mcp_has_no_database_or_service_imports():
    forbidden = {"sqlite3", "asyncpg", "sqlalchemy", "platform_database", "app"}
    for path in (SERVICE / "mcp/project_product_mcp").rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8-sig"))
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        assert not imported & forbidden, f"{path}: {imported & forbidden}"


def test_no_sqlite_runtime_or_obsolete_db_path():
    files = (
        list((SERVICE / "app").rglob("*.py"))
        + list((SERVICE / "mcp").rglob("*.py"))
        + [ROOT / "manifests/mcps/project-product-mcp.yaml"]
    )
    content = "\n".join(path.read_text(encoding="utf-8-sig").lower() for path in files)
    assert "sqlite" not in content
    assert "project_product_db_path" not in content


def test_swarm_does_not_publish_mcp_port_and_uses_same_digest():
    stack = yaml.safe_load((SERVICE / "deploy/stack.yaml").read_text(encoding="utf-8"))
    assert "ports" not in stack["services"]["mcp"]
    assert stack["services"]["api"]["image"] == stack["services"]["mcp"]["image"]
    assert stack["networks"]["adapter"]["internal"] is True
