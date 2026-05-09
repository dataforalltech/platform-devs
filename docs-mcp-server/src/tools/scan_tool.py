from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..knowledge.standards import DOC_TYPES


def _detect_doc_type(file_path: Path) -> str | None:
    """Detecta o tipo de documento baseado no nome do arquivo."""
    name = file_path.name
    parts = str(file_path).replace("\\", "/")

    for doc_type, patterns in DOC_TYPES.items():
        for pattern in patterns:
            if pattern in name or pattern in parts:
                return doc_type
    return None


def _extract_title(content: str, file_path: Path) -> str:
    """Extrai título: primeira linha com '# ' ou nome do arquivo sem extensão."""
    for line in content.splitlines():
        stripped = line.strip()
        if stripped.startswith("# "):
            return stripped[2:].strip()
    return file_path.stem


def _count_words(content: str) -> int:
    return len(re.findall(r"\S+", content))


def _content_hash(content: str) -> str:
    return hashlib.md5(content.encode("utf-8", errors="ignore")).hexdigest()


def _last_modified_iso(path: Path) -> str:
    ts = path.stat().st_mtime
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat()


def scan_docs(
    store: Any,
    settings: Any,
    *,
    repo_path: str,
    patterns: list[str] | None = None,
    include_hidden: bool = False,
) -> dict:
    """
    Encontra todos os arquivos de documentação em repo_path.
    """
    if not repo_path:
        return {
            "error": "ValidationError",
            "details": "repo_path is required",
            "tool": "scan_docs",
        }

    root = Path(repo_path)
    if not root.exists():
        return {
            "error": "ValidationError",
            "details": f"repo_path not found: {repo_path}",
            "tool": "scan_docs",
        }

    if patterns is None:
        patterns = ["**/*.md", "**/*.rst", "**/*.txt"]

    max_bytes = settings.max_file_size_kb * 1024
    docs: list[dict[str, Any]] = []
    seen: set[str] = set()

    for pattern in patterns:
        for fpath in root.rglob(pattern.lstrip("*").lstrip("/")):
            if not fpath.is_file():
                continue
            # Skip hidden files/dirs unless requested
            if not include_hidden:
                if any(part.startswith(".") for part in fpath.parts):
                    continue
            abs_str = str(fpath)
            if abs_str in seen:
                continue
            seen.add(abs_str)

            try:
                size_bytes = fpath.stat().st_size
            except OSError:
                continue

            if size_bytes > max_bytes:
                continue

            try:
                content = fpath.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            rel_path = str(fpath.relative_to(root)).replace("\\", "/")
            doc_type = _detect_doc_type(fpath)
            title = _extract_title(content, fpath)
            word_count = _count_words(content)
            last_mod = _last_modified_iso(fpath)
            size_kb = round(size_bytes / 1024, 2)

            # Update index in store
            store.upsert_doc_index(
                repo_path=repo_path,
                file_path=rel_path,
                doc_type=doc_type,
                title=title,
                word_count=word_count,
                last_modified=last_mod,
                content_hash=_content_hash(content),
            )

            docs.append(
                {
                    "path": rel_path,
                    "full_path": abs_str,
                    "doc_type": doc_type,
                    "size_kb": size_kb,
                    "last_modified": last_mod,
                    "word_count": word_count,
                    "title": title,
                }
            )

    docs.sort(key=lambda d: d["path"])

    return {
        "repo_path": repo_path,
        "total": len(docs),
        "docs": docs,
    }


def search_docs(
    store: Any,
    settings: Any,
    *,
    repo_path: str,
    query: str,
    case_sensitive: bool = False,
    file_types: list[str] | None = None,
) -> dict:
    """
    Busca full-text em todos os docs do repo_path.
    """
    if not repo_path:
        return {
            "error": "ValidationError",
            "details": "repo_path is required",
            "tool": "search_docs",
        }
    if not query:
        return {
            "error": "ValidationError",
            "details": "query is required",
            "tool": "search_docs",
        }

    root = Path(repo_path)
    if not root.exists():
        return {
            "error": "ValidationError",
            "details": f"repo_path not found: {repo_path}",
            "tool": "search_docs",
        }

    extensions = file_types or ["md", "rst", "txt"]
    patterns = [f"**/*.{ext}" for ext in extensions]
    max_bytes = settings.max_file_size_kb * 1024

    flags = 0 if case_sensitive else re.IGNORECASE
    compiled = re.compile(re.escape(query), flags)

    results: list[dict[str, Any]] = []
    files_searched = 0
    total_matches = 0

    for pattern in patterns:
        for fpath in root.rglob(pattern.lstrip("*").lstrip("/")):
            if not fpath.is_file():
                continue
            if any(part.startswith(".") for part in fpath.parts):
                continue
            try:
                size_bytes = fpath.stat().st_size
            except OSError:
                continue
            if size_bytes > max_bytes:
                continue

            try:
                content = fpath.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            files_searched += 1
            lines = content.splitlines()
            file_matches: list[dict[str, Any]] = []

            for lineno, line in enumerate(lines, start=1):
                if compiled.search(line):
                    # Build snippet: 100 chars before and after the match
                    m = compiled.search(line)
                    if m:
                        start = max(0, m.start() - 100)
                        end = min(len(line), m.end() + 100)
                        snippet = line[start:end].strip()
                    else:
                        snippet = line.strip()
                    file_matches.append({"line": lineno, "snippet": snippet})
                    total_matches += 1

            if file_matches:
                rel_path = str(fpath.relative_to(root)).replace("\\", "/")
                results.append({"file": rel_path, "matches": file_matches})

    return {
        "query": query,
        "total_matches": total_matches,
        "files_searched": files_searched,
        "results": results,
    }


def get_doc_tree(
    store: Any,
    settings: Any,
    *,
    repo_path: str,
) -> dict:
    """
    Retorna estrutura hierárquica de todos os arquivos doc.
    """
    if not repo_path:
        return {
            "error": "ValidationError",
            "details": "repo_path is required",
            "tool": "get_doc_tree",
        }

    root = Path(repo_path)
    if not root.exists():
        return {
            "error": "ValidationError",
            "details": f"repo_path not found: {repo_path}",
            "tool": "get_doc_tree",
        }

    max_bytes = settings.max_file_size_kb * 1024
    tree: dict[str, Any] = {}
    total_files = 0
    total_words = 0
    type_counts: dict[str, int] = {}

    for pattern in ["**/*.md", "**/*.rst", "**/*.txt"]:
        for fpath in root.rglob(pattern.lstrip("*").lstrip("/")):
            if not fpath.is_file():
                continue
            if any(part.startswith(".") for part in fpath.parts):
                continue
            try:
                size_bytes = fpath.stat().st_size
            except OSError:
                continue
            if size_bytes > max_bytes:
                continue

            try:
                content = fpath.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            rel_path = fpath.relative_to(root)
            doc_type = _detect_doc_type(fpath)
            word_count = _count_words(content)
            size_kb = round(size_bytes / 1024, 2)

            total_files += 1
            total_words += word_count
            if doc_type:
                type_counts[doc_type] = type_counts.get(doc_type, 0) + 1
            else:
                type_counts["other"] = type_counts.get("other", 0) + 1

            # Build nested dict structure
            node: dict[str, Any] = tree
            parts = list(rel_path.parts)
            for part in parts[:-1]:
                dir_key = part + "/"
                if dir_key not in node:
                    node[dir_key] = {}
                node = node[dir_key]
            node[parts[-1]] = {
                "type": doc_type,
                "size_kb": size_kb,
                "word_count": word_count,
            }

    return {
        "repo_path": repo_path,
        "tree": tree,
        "summary": {
            "total_files": total_files,
            "total_words": total_words,
            "types": type_counts,
        },
    }
