from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from src.config.settings import DocsSettings


def _now() -> str:
    return datetime.now(UTC).isoformat()


class FakeDocsStore:
    """In-memory stand-in for the PostgreSQL-backed DocsStore.

    Reproduces the public contract of ``src.db.store.DocsStore`` (same method
    signatures and return shapes) without opening a psycopg2 connection pool, so
    the tool-level tests stay hermetic — no database, no network, no I/O.

    The real store persists to a unified ``documents`` table; here we keep two
    in-memory lists (audits and index rows) and mirror the ordering/return
    semantics the tools depend on (audits newest-first by id, index rows sorted
    by file_path).
    """

    def __init__(self) -> None:
        self._audits: list[dict[str, Any]] = []
        self._index: list[dict[str, Any]] = []
        self._next_id = 1
        self.closed = False

    # -- audits ---------------------------------------------------------- #

    def save_audit(
        self,
        repo_path: str,
        score: int,
        grade: str,
        summary: dict,
        details: dict,
        duration_ms: int | None = None,
    ) -> int:
        audit_id = self._next_id
        self._next_id += 1
        # Round-trip through JSON to match psycopg2 json.dumps/json.loads behaviour.
        self._audits.append(
            {
                "id": audit_id,
                "repo_path": repo_path,
                "title": f"Audit: {grade}",
                "score": score,
                "grade": grade,
                "summary": json.loads(json.dumps(summary)),
                "details": json.loads(json.dumps(details)),
                "duration_ms": duration_ms,
                "created_at": _now(),
            }
        )
        return audit_id

    def list_audits(
        self,
        repo_path: str | None = None,
        limit: int = 10,
    ) -> list[dict[str, Any]]:
        rows = [a for a in self._audits if repo_path is None or a["repo_path"] == repo_path]
        rows.sort(key=lambda a: a["id"], reverse=True)  # newest first
        return [dict(a) for a in rows[:limit]]

    # -- document index -------------------------------------------------- #

    def upsert_doc_index(
        self,
        repo_path: str,
        file_path: str,
        doc_type: str | None,
        title: str | None,
        word_count: int,
        last_modified: str | None,
        content_hash: str | None,
    ) -> None:
        row = {
            "id": None,
            "repo_path": repo_path,
            "doc_type": doc_type,
            "title": title,
            "word_count": word_count,
            "last_modified": last_modified,
            "content_hash": content_hash,
            "file_path": file_path,
            "created_at": _now(),
        }
        for i, existing in enumerate(self._index):
            if existing["repo_path"] == repo_path and existing["file_path"] == file_path:
                row["id"] = existing["id"]
                self._index[i] = row
                return
        row["id"] = self._next_id
        self._next_id += 1
        self._index.append(row)

    def search_index(self, repo_path: str, query: str) -> list[dict[str, Any]]:
        q = query.lower()
        rows = [
            r
            for r in self._index
            if r["repo_path"] == repo_path and q in (r["title"] or "").lower()
        ]
        rows.sort(key=lambda r: r["title"] or "")
        return [dict(r) for r in rows]

    def get_index(self, repo_path: str) -> list[dict[str, Any]]:
        rows = [r for r in self._index if r["repo_path"] == repo_path]
        rows.sort(key=lambda r: r["file_path"])
        return [dict(r) for r in rows]

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def store():
    s = FakeDocsStore()
    yield s
    s.close()


@pytest.fixture
def settings():
    return DocsSettings(
        stale_days_threshold=90,
        check_external_links=False,
        http_timeout=5.0,
        max_file_size_kb=500,
    )


@pytest.fixture
def tmp_repo(tmp_path):
    """Cria estrutura mínima de repo para testes."""
    readme_content = (
        "# Test Service\n\n"
        "## Installation\n\nfoo bar baz qux quux\n\n"
        "## Usage\n\nbar baz qux quux corge\n"
    ) * 5
    (tmp_path / "README.md").write_text(readme_content, encoding="utf-8")
    changelog_content = (
        "# Changelog\n\n"
        "## [Unreleased]\n\n"
        "## [1.0.0] - 2026-01-01\n\n"
        "### Added\n- Initial release\n"
    )
    (tmp_path / "CHANGELOG.md").write_text(changelog_content, encoding="utf-8")
    return tmp_path
