from __future__ import annotations

from src.tools.scan_tool import get_doc_tree, scan_docs, search_docs


def test_scan_docs_finds_markdown_files(store, settings, tmp_path):
    (tmp_path / "README.md").write_text("# Service\n\nDescription\n", encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n\nChanges\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "guide.md").write_text("# Guide\n\nContent\n", encoding="utf-8")

    result = scan_docs(store, settings, repo_path=str(tmp_path))

    assert result["total"] == 3
    paths = [d["path"] for d in result["docs"]]
    assert any("README.md" in p for p in paths)
    assert any("CHANGELOG.md" in p for p in paths)
    assert any("guide.md" in p for p in paths)


def test_scan_docs_empty_dir(store, settings, tmp_path):
    result = scan_docs(store, settings, repo_path=str(tmp_path))
    assert result["total"] == 0
    assert result["docs"] == []


def test_scan_docs_detects_readme_type(store, settings, tmp_path):
    (tmp_path / "README.md").write_text("# Service\n\nDescription\n", encoding="utf-8")

    result = scan_docs(store, settings, repo_path=str(tmp_path))

    assert result["total"] == 1
    doc = result["docs"][0]
    assert doc["doc_type"] == "readme"
    assert doc["title"] == "Service"


def test_scan_docs_missing_repo_validation(store, settings):
    result = scan_docs(store, settings, repo_path="/nonexistent/path/xyz")
    assert result["error"] == "ValidationError"


def test_scan_docs_empty_repo_path_validation(store, settings):
    result = scan_docs(store, settings, repo_path="")
    assert result["error"] == "ValidationError"


def test_search_docs_finds_match(store, settings, tmp_path):
    (tmp_path / "README.md").write_text(
        "# Service\n\nThis service provides authentication support.\n",
        encoding="utf-8",
    )

    result = search_docs(store, settings, repo_path=str(tmp_path), query="authentication")

    assert result["total_matches"] >= 1
    assert len(result["results"]) >= 1
    assert result["results"][0]["file"].endswith("README.md")


def test_search_docs_case_insensitive(store, settings, tmp_path):
    (tmp_path / "doc.md").write_text("# Title\n\nHello World\n", encoding="utf-8")

    result = search_docs(store, settings, repo_path=str(tmp_path), query="hello world", case_sensitive=False)

    assert result["total_matches"] >= 1


def test_search_docs_no_match(store, settings, tmp_path):
    (tmp_path / "README.md").write_text("# Service\n\nSimple content\n", encoding="utf-8")

    result = search_docs(store, settings, repo_path=str(tmp_path), query="xyznonexistentterm")

    assert result["total_matches"] == 0
    assert result["results"] == []


def test_get_doc_tree_structure(store, settings, tmp_path):
    (tmp_path / "README.md").write_text("# Service\n\nContent here.\n", encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "api.md").write_text("# API\n\nEndpoints here.\n", encoding="utf-8")

    result = get_doc_tree(store, settings, repo_path=str(tmp_path))

    assert "tree" in result
    assert "summary" in result
    assert "README.md" in result["tree"]
    assert result["summary"]["total_files"] == 2
    assert result["summary"]["total_words"] > 0


def test_scan_docs_stores_in_index(store, settings, tmp_path):
    (tmp_path / "README.md").write_text("# My Service\n\nContent\n", encoding="utf-8")

    scan_docs(store, settings, repo_path=str(tmp_path))

    indexed = store.get_index(repo_path=str(tmp_path))
    assert len(indexed) == 1
    assert indexed[0]["title"] == "My Service"
