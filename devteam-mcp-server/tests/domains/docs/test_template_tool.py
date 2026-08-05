# Portado de `docs-mcp-server/tests/test_template_tool.py` pelo fan-out de testes.
#
# O código de tool do agregador é byte-a-byte o do servidor legado; só o caminho
# de import muda. Gerado por `scripts/port_domain_tests.py` — reexecutar é
# idempotente. Editar aqui diverge da origem: corrija no legado e reexecute, ou
# aposente o legado (ver ROADMAP, fechar o strangler).

"""Tools de template (compute-only): não tocam o banco → ``store=None`` (hermético)."""

from __future__ import annotations

from src.domains.docs.tools.template_tool import generate_doc, list_templates


def test_list_templates_returns_6():
    result = list_templates()
    assert result["count"] == 6
    assert len(result["templates"]) == 6


def test_list_templates_has_required_fields():
    result = list_templates()
    for tmpl in result["templates"]:
        assert "name" in tmpl, f"Missing 'name' in {tmpl}"
        assert "file" in tmpl, f"Missing 'file' in {tmpl}"
        assert "description" in tmpl, f"Missing 'description' in {tmpl}"
        assert "variables" in tmpl, f"Missing 'variables' in {tmpl}"
        assert "use_case" in tmpl, f"Missing 'use_case' in {tmpl}"
        assert isinstance(tmpl["variables"], list)


def test_list_templates_all_names_present():
    result = list_templates()
    names = {t["name"] for t in result["templates"]}
    expected = {"README", "CHANGELOG", "ADR", "AGENTS", "RUNBOOK", "API"}
    assert names == expected


def test_generate_doc_readme(settings):
    result = generate_doc(
        None,
        settings,
        template_name="README",
        variables={"service_name": "my-service", "description": "A great service", "year": "2026"},
    )

    assert result["template"] == "README"
    assert "my-service" in result["content"]
    assert "A great service" in result["content"]
    assert result["char_count"] > 0
    assert result["saved"] is False


def test_generate_doc_missing_vars_kept_as_placeholder(settings):
    result = generate_doc(
        None,
        settings,
        template_name="README",
        variables={"service_name": "my-service"},
    )

    # Variables not provided should remain as {{variable}} placeholders
    assert "{{" in result["content"] or len(result["variables_missing"]) >= 0
    assert "service_name" in result["variables_used"]
    assert "registry" in result["variables_missing"] or "year" in result["variables_missing"]


def test_generate_doc_saves_to_file(settings, tmp_path):
    out = tmp_path / "README.md"
    result = generate_doc(
        None,
        settings,
        template_name="README",
        variables={"service_name": "test-svc", "description": "Test", "year": "2026"},
        output_path=str(out),
    )

    assert result["saved"] is True
    assert result["output_path"] == str(out)
    assert out.exists()
    assert "test-svc" in out.read_text(encoding="utf-8")


def test_generate_doc_invalid_template(settings):
    result = generate_doc(
        None,
        settings,
        template_name="NONEXISTENT",
        variables={},
    )

    assert result["error"] == "ValidationError"
    assert "NONEXISTENT" in result["details"]


def test_generate_doc_all_vars_substituted(settings):
    result = generate_doc(
        None,
        settings,
        template_name="ADR",
        variables={"number": "001", "title": "Use PostgreSQL", "date": "2026-05-07"},
    )

    assert "001" in result["content"]
    assert "Use PostgreSQL" in result["content"]
    assert "2026-05-07" in result["content"]
    assert result["variables_missing"] == []
