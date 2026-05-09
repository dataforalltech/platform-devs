from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..knowledge.standards import DOC_TYPES, REQUIRED_DOCS, SECTION_RULES


def _detect_doc_type_by_path(file_path: Path) -> str | None:
    """Detecta tipo de doc pelo nome do arquivo."""
    name = file_path.name
    path_str = str(file_path).replace("\\", "/")

    for doc_type, patterns in DOC_TYPES.items():
        for pattern in patterns:
            if pattern in name or pattern in path_str:
                return doc_type
    return None


def _count_words(content: str) -> int:
    return len(re.findall(r"\S+", content))


def _extract_headings(content: str) -> list[str]:
    """Extrai todos os textos de headings do markdown."""
    headings = []
    for line in content.splitlines():
        m = re.match(r"^(#{1,6})\s+(.+)$", line.strip())
        if m:
            headings.append(m.group(2).strip())
    return headings


def _heading_to_slug(heading: str) -> str:
    """Converte heading para slug de âncora GitHub-style."""
    slug = heading.lower()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "-", slug)
    slug = slug.strip("-")
    return slug


def validate_doc(
    store: Any,
    settings: Any,
    *,
    file_path: str,
    doc_type: str = "auto",
) -> dict:
    """
    Valida um doc contra as regras de SECTION_RULES.
    """
    if not file_path:
        return {
            "error": "ValidationError",
            "details": "file_path is required",
            "tool": "validate_doc",
        }

    fpath = Path(file_path)
    if not fpath.exists():
        return {
            "error": "ValidationError",
            "details": f"file not found: {file_path}",
            "tool": "validate_doc",
        }

    try:
        content = fpath.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        return {
            "error": "ValidationError",
            "details": f"cannot read file: {exc}",
            "tool": "validate_doc",
        }

    # Detect doc type
    actual_type = doc_type
    if doc_type == "auto":
        detected = _detect_doc_type_by_path(fpath)
        actual_type = detected or "unknown"

    rules = SECTION_RULES.get(actual_type, {})
    issues: list[dict[str, str]] = []
    passed: list[str] = []

    if not rules:
        return {
            "file": file_path,
            "doc_type": actual_type,
            "valid": True,
            "score": 100,
            "issues": [],
            "passed": ["Tipo de documento sem regras específicas"],
        }

    headings = _extract_headings(content)
    heading_lower = [h.lower() for h in headings]
    word_count = _count_words(content)

    # Check required headings
    for req_heading in rules.get("required_headings", []):
        if any(req_heading.lower() in h for h in heading_lower):
            passed.append(f"Seção '{req_heading}' presente")
        else:
            issues.append(
                {
                    "severity": "error",
                    "message": f"Seção '{req_heading}' ausente",
                }
            )

    # Check recommended headings
    for rec_heading in rules.get("recommended_headings", []):
        if any(rec_heading.lower() in h for h in heading_lower):
            passed.append(f"Seção recomendada '{rec_heading}' presente")
        else:
            issues.append(
                {
                    "severity": "warning",
                    "message": f"Seção '{rec_heading}' recomendada mas ausente",
                }
            )

    # Check required patterns (for changelog)
    for pattern in rules.get("required_patterns", []):
        if re.search(pattern, content, re.MULTILINE):
            passed.append(f"Padrão obrigatório encontrado: {pattern}")
        else:
            issues.append(
                {
                    "severity": "error",
                    "message": f"Padrão obrigatório ausente: {pattern}",
                }
            )

    # Check min words
    min_words = rules.get("min_words", 0)
    if min_words > 0:
        if word_count >= min_words:
            passed.append(f"Mínimo de palavras OK ({word_count}/{min_words})")
        else:
            issues.append(
                {
                    "severity": "warning",
                    "message": f"Poucas palavras: {word_count}/{min_words} mínimo",
                }
            )

    # ADR-specific: check valid status
    if actual_type == "adr":
        valid_statuses = rules.get("valid_statuses", [])
        status_match = re.search(r"\*\*Status:\*\*\s*(\w+)", content)
        if not status_match:
            # Try plain Status: text
            status_match = re.search(r"^Status:\s*(\w+)", content, re.MULTILINE)
        if status_match:
            status_val = status_match.group(1).lower()
            if status_val in valid_statuses:
                passed.append(f"Status válido: {status_val}")
            else:
                issues.append(
                    {
                        "severity": "error",
                        "message": (
                            f"Status inválido '{status_val}'. "
                            f"Valores válidos: {', '.join(valid_statuses)}"
                        ),
                    }
                )
        else:
            issues.append(
                {
                    "severity": "warning",
                    "message": "Campo 'Status' não encontrado no ADR",
                }
            )

    # Compute score
    errors = sum(1 for i in issues if i["severity"] == "error")
    warnings = sum(1 for i in issues if i["severity"] == "warning")
    total_checks = len(passed) + errors + warnings
    if total_checks == 0:
        score = 100
    else:
        score = int((len(passed) / total_checks) * 100)

    return {
        "file": file_path,
        "doc_type": actual_type,
        "valid": errors == 0,
        "score": score,
        "issues": issues,
        "passed": passed,
    }


def check_links(
    store: Any,
    settings: Any,
    *,
    file_path: str,
    check_external: bool | None = None,
) -> dict:
    """
    Detecta links quebrados em markdown.
    """
    if not file_path:
        return {
            "error": "ValidationError",
            "details": "file_path is required",
            "tool": "check_links",
        }

    fpath = Path(file_path)
    if not fpath.exists():
        return {
            "error": "ValidationError",
            "details": f"file not found: {file_path}",
            "tool": "check_links",
        }

    try:
        content = fpath.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        return {
            "error": "ValidationError",
            "details": f"cannot read file: {exc}",
            "tool": "check_links",
        }

    should_check_external = (
        check_external if check_external is not None else settings.check_external_links
    )
    doc_dir = fpath.parent

    # Extract headings/anchors in this document
    headings = _extract_headings(content)
    anchor_slugs = {_heading_to_slug(h) for h in headings}

    # Extract inline links: [text](url)
    inline_pattern = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
    # Extract reference-style links: [ref]: url
    ref_def_pattern = re.compile(r"^\[([^\]]+)\]:\s+(\S+)", re.MULTILINE)

    ref_urls: dict[str, str] = {}
    for m in ref_def_pattern.finditer(content):
        ref_urls[m.group(1).lower()] = m.group(2)

    links: list[tuple[int, str, str]] = []  # (line, text, url)
    lines = content.splitlines()

    for lineno, line in enumerate(lines, start=1):
        for m in inline_pattern.finditer(line):
            links.append((lineno, m.group(1), m.group(2)))

    # Also detect reference-style usage: [text][ref]
    ref_usage_pattern = re.compile(r"\[([^\]]*)\]\[([^\]]*)\]")
    for lineno, line in enumerate(lines, start=1):
        for m in ref_usage_pattern.finditer(line):
            ref_key = (m.group(2) or m.group(1)).lower()
            url = ref_urls.get(ref_key, "")
            if url:
                links.append((lineno, m.group(1), url))

    total_links = len(links)
    link_issues: list[dict[str, Any]] = []
    valid_count = 0

    for lineno, _text, url in links:
        # Skip empty URLs
        if not url:
            link_issues.append(
                {
                    "line": lineno,
                    "link": url,
                    "type": "empty",
                    "reason": "URL vazia",
                }
            )
            continue

        # Anchor-only link
        if url.startswith("#"):
            slug = url[1:]
            if slug in anchor_slugs:
                valid_count += 1
            else:
                link_issues.append(
                    {
                        "line": lineno,
                        "link": url,
                        "type": "anchor",
                        "reason": f"âncora '{slug}' não encontrada no documento",
                    }
                )
            continue

        # External link
        if url.startswith(("http://", "https://")):
            if should_check_external:
                try:
                    import httpx

                    resp = httpx.head(url, timeout=settings.http_timeout, follow_redirects=True)
                    if resp.status_code < 400:
                        valid_count += 1
                    else:
                        link_issues.append(
                            {
                                "line": lineno,
                                "link": url,
                                "type": "external",
                                "reason": f"HTTP {resp.status_code}",
                            }
                        )
                except Exception:  # noqa: BLE001
                    link_issues.append(
                        {
                            "line": lineno,
                            "link": url,
                            "type": "external",
                            "reason": "connection error",
                        }
                    )
            else:
                # Not checking external → assume valid
                valid_count += 1
            continue

        # Internal link: strip anchor part
        link_part = url.split("#")[0]
        anchor_part = url.split("#")[1] if "#" in url else None

        if not link_part:
            # Just an anchor
            if anchor_part and anchor_part in anchor_slugs:
                valid_count += 1
            elif anchor_part:
                link_issues.append(
                    {
                        "line": lineno,
                        "link": url,
                        "type": "anchor",
                        "reason": f"âncora '{anchor_part}' não encontrada",
                    }
                )
            continue

        # Resolve relative path
        resolved = (doc_dir / link_part).resolve()
        if resolved.exists():
            valid_count += 1
        else:
            link_issues.append(
                {
                    "line": lineno,
                    "link": url,
                    "type": "internal",
                    "reason": "arquivo não encontrado",
                }
            )

    return {
        "file": file_path,
        "total_links": total_links,
        "broken": len(link_issues),
        "valid": valid_count,
        "issues": link_issues,
    }


def check_required_docs(
    store: Any,
    settings: Any,
    *,
    repo_path: str,
    standard: str = "standard",
) -> dict:
    """
    Verifica se o repo tem os arquivos obrigatórios para o nível de standard.
    """
    if not repo_path:
        return {
            "error": "ValidationError",
            "details": "repo_path is required",
            "tool": "check_required_docs",
        }

    root = Path(repo_path)
    if not root.exists():
        return {
            "error": "ValidationError",
            "details": f"repo_path not found: {repo_path}",
            "tool": "check_required_docs",
        }

    if standard not in REQUIRED_DOCS:
        return {
            "error": "ValidationError",
            "details": f"unknown standard '{standard}'. Valid: {list(REQUIRED_DOCS.keys())}",
            "tool": "check_required_docs",
        }

    required = REQUIRED_DOCS[standard]
    present: list[str] = []
    missing: list[str] = []

    for doc_name in required:
        # Check if file exists at root or in common locations
        found = False
        for candidate in [root / doc_name, root / "docs" / doc_name]:
            if candidate.exists():
                found = True
                break
        if found:
            present.append(doc_name)
        else:
            missing.append(doc_name)

    total = len(required)
    coverage_pct = round(len(present) / total * 100, 1) if total > 0 else 0.0

    return {
        "repo_path": repo_path,
        "standard": standard,
        "required": required,
        "present": present,
        "missing": missing,
        "coverage_pct": coverage_pct,
        "passed": len(missing) == 0,
    }


def lint_markdown(
    store: Any,
    settings: Any,
    *,
    file_path: str,
) -> dict:
    """
    Linting de qualidade do markdown.
    """
    if not file_path:
        return {
            "error": "ValidationError",
            "details": "file_path is required",
            "tool": "lint_markdown",
        }

    fpath = Path(file_path)
    if not fpath.exists():
        return {
            "error": "ValidationError",
            "details": f"file not found: {file_path}",
            "tool": "lint_markdown",
        }

    try:
        content = fpath.read_text(encoding="utf-8", errors="ignore")
    except OSError as exc:
        return {
            "error": "ValidationError",
            "details": f"cannot read file: {exc}",
            "tool": "lint_markdown",
        }

    issues: list[dict[str, Any]] = []
    lines = content.splitlines()
    total_lines = len(lines)

    in_codeblock = False
    codeblock_count = 0
    last_heading_level = 0
    seen_headings: dict[str, int] = {}
    has_h1 = False

    for lineno, line in enumerate(lines, start=1):
        # Track code blocks
        if line.strip().startswith("```"):
            codeblock_count += 1
            in_codeblock = not in_codeblock

        if in_codeblock:
            continue

        # Check headings
        m = re.match(r"^(#{1,6})\s+(.+)$", line)
        if m:
            level = len(m.group(1))
            heading_text = m.group(2).strip()

            if level == 1:
                has_h1 = True

            # Check heading skip (e.g., h1 → h3 skips h2)
            if last_heading_level > 0 and level > last_heading_level + 1:
                issues.append(
                    {
                        "line": lineno,
                        "severity": "warning",
                        "rule": "heading-skip",
                        "message": (
                            f"h{last_heading_level}→h{level} salta h{last_heading_level + 1}"
                        ),
                    }
                )
            last_heading_level = level

            # Check duplicate headings
            slug = heading_text.lower()
            if slug in seen_headings:
                issues.append(
                    {
                        "line": lineno,
                        "severity": "warning",
                        "rule": "duplicate-heading",
                        "message": (
                            f"Heading duplicado '{heading_text}' "
                            f"(primeira ocorrência: linha {seen_headings[slug]})"
                        ),
                    }
                )
            else:
                seen_headings[slug] = lineno

        # Check empty links [text]()
        empty_link_pattern = re.compile(r"\[([^\]]+)\]\(\s*\)")
        for m2 in empty_link_pattern.finditer(line):
            issues.append(
                {
                    "line": lineno,
                    "severity": "warning",
                    "rule": "empty-link",
                    "message": f"Link vazio: [{m2.group(1)}]()",
                }
            )

        # Check images without alt text: ![]()
        no_alt_pattern = re.compile(r"!\[\]\([^)]+\)")
        for _ in no_alt_pattern.finditer(line):
            issues.append(
                {
                    "line": lineno,
                    "severity": "warning",
                    "rule": "image-no-alt",
                    "message": "Imagem sem texto alternativo (alt text)",
                }
            )

        # Check long lines (>120 chars) in regular paragraphs
        if not line.startswith("#") and not line.startswith("|") and len(line) > 120:
            issues.append(
                {
                    "line": lineno,
                    "severity": "warning",
                    "rule": "long-line",
                    "message": f"Linha muito longa ({len(line)} chars > 120)",
                }
            )

    # Check unclosed code block
    if codeblock_count % 2 != 0:
        issues.append(
            {
                "line": total_lines,
                "severity": "error",
                "rule": "unclosed-codeblock",
                "message": "Bloco de código não fechado (``` sem par de fechamento)",
            }
        )

    # Check missing h1
    if total_lines > 0 and not has_h1:
        issues.append(
            {
                "line": 1,
                "severity": "warning",
                "rule": "missing-h1",
                "message": "Arquivo sem heading principal (# Título)",
            }
        )

    errors = sum(1 for i in issues if i["severity"] == "error")
    warnings = sum(1 for i in issues if i["severity"] == "warning")

    return {
        "file": file_path,
        "lines": total_lines,
        "issues": issues,
        "errors": errors,
        "warnings": warnings,
        "passed": errors == 0 and warnings == 0,
    }
