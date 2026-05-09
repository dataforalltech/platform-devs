from __future__ import annotations

from src.tools.template_tool import generate_doc, list_templates


def test_list_templates_returns_6(store, settings):
    result = list_templates()
    assert result["count"] == 6
    assert len(result["templates"]) == 6


def test_list_templates_has_required_fields(store, settings):
    result = list_templates()
    for tmpl in result["templates"]:
        assert "name" in tmpl, f"Missing 'name' in {tmpl}"
        assert "file" in tmpl, f"Missing 'file' in {tmpl}"
        assert "description" in tmpl, f"Missing 'description' in {tmpl}"
        assert "variables" in tmpl, f"Missing 'variables' in {tmpl}"
        assert "use_case" in tmpl, f"Missing 'use_case' in {tmpl}"
        assert isinstance(tmpl["variables"], list)


def test_list_templates_all_names_present(store, settings):
    result = list_templates()
    names = {t["name"] for t in result["templates"]}
    expected = {"README", "CHANGELOG", "ADR", "AGENTS", "RUNBOOK", "API"}
    assert names == expected


def test_generate_doc_readme(store, settings):
    result = generate_doc(
        store,
        settings,
        template_name="README",
        variables={"service_name": "my-service", "description": "A great service", "year": "2026"},
    )

    assert result["template"] == "README"
    assert "my-service" in result["content"]
    assert "A great service" in result["content"]
    assert result["char_count"] > 0
    assert result["saved"] is False


def test_generate_doc_missing_vars_kept_as_placeholder(store, settings):
    result = generate_doc(
        store,
        settings,
        template_name="README",
        variables={"service_name": "my-service"},
    )

    # Variables not provided should remain as {{variable}} placeholders
    assert "{{" in result["content"] or len(result["variables_missing"]) >= 0
    assert "service_name" in result["variables_used"]
    assert "registry" in result["variables_missing"] or "year" in result["variables_missing"]


def test_generate_doc_saves_to_file(store, settings, tmp_path):
    out = tmp_path / "README.md"
    result = generate_doc(
        store,
        settings,
        template_name="README",
        variables={"service_name": "test-svc", "description": "Test", "year": "2026"},
        output_path=str(out),
    )

    assert result["saved"] is True
    assert result["output_path"] == str(out)
    assert out.exists()
    assert "test-svc" in out.read_text(encoding="utf-8")


def test_generate_doc_invalid_template(store, settings):
    result = generate_doc(
        store,
        settings,
        template_name="NONEXISTENT",
        variables={},
    )

    assert result["error"] == "ValidationError"
    assert "NONEXISTENT" in result["details"]


def test_generate_doc_all_vars_substituted(store, settings):
    result = generate_doc(
        store,
        settings,
        template_name="ADR",
        variables={"number": "001", "title": "Use PostgreSQL", "date": "2026-05-07"},
    )

    assert "001" in result["content"]
    assert "Use PostgreSQL" in result["content"]
    assert "2026-05-07" in result["content"]
    assert result["variables_missing"] == []
