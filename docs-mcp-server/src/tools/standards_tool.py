from __future__ import annotations

from pathlib import Path
from typing import Any

from .validation_tool import check_links, check_required_docs, lint_markdown, validate_doc


def _grade(score: int) -> str:
    if score >= 90:
        return "A"
    if score >= 75:
        return "B"
    if score >= 60:
        return "C"
    if score >= 40:
        return "D"
    return "F"


def check_doc_standards(
    store: Any,
    settings: Any,
    *,
    repo_path: str,
    standard: str = "standard",
) -> dict:
    """
    Verificação abrangente de padrões documentais no repo.

    Combina múltiplas verificações e calcula score por categoria:
    - completeness (30%): arquivos obrigatórios presentes
    - validity (40%): validação de estrutura por tipo
    - quality (30%): lint markdown
    """
    if not repo_path:
        return {
            "error": "ValidationError",
            "details": "repo_path is required",
            "tool": "check_doc_standards",
        }

    root = Path(repo_path)
    if not root.exists():
        return {
            "error": "ValidationError",
            "details": f"repo_path not found: {repo_path}",
            "tool": "check_doc_standards",
        }

    all_issues: list[dict[str, Any]] = []
    recommendations: list[str] = []

    # 1. Completeness check (30%)
    req_result = check_required_docs(store, settings, repo_path=repo_path, standard=standard)
    if "error" in req_result:
        return req_result

    present = req_result.get("present", [])
    missing = req_result.get("missing", [])
    coverage_pct = req_result.get("coverage_pct", 0.0)
    completeness_score = int(coverage_pct)

    if missing:
        for m in missing:
            all_issues.append({"severity": "error", "source": "completeness", "message": f"Arquivo obrigatório ausente: {m}"})
        recommendations.append(f"Adicionar arquivos obrigatórios: {', '.join(missing)}")
        completeness_detail = f"{len(present)}/{len(present) + len(missing)} docs obrigatórios presentes"
    else:
        completeness_detail = f"{len(present)}/{len(present)} docs obrigatórios presentes"

    # 2. Validity check (40%) — validate each found doc
    validity_scores: list[int] = []
    validity_details: list[str] = []

    # Find all markdown files in the repo
    doc_files: list[Path] = []
    for pattern in ["**/*.md", "**/*.rst"]:
        for fpath in root.rglob(pattern.lstrip("*").lstrip("/")):
            if not fpath.is_file():
                continue
            if any(part.startswith(".") for part in fpath.parts):
                continue
            doc_files.append(fpath)

    for fpath in doc_files:
        val_result = validate_doc(store, settings, file_path=str(fpath), doc_type="auto")
        if "error" in val_result:
            continue
        score = val_result.get("score", 100)
        validity_scores.append(score)
        for issue in val_result.get("issues", []):
            if issue["severity"] == "error":
                all_issues.append(
                    {
                        "severity": "error",
                        "source": "validity",
                        "file": str(fpath.relative_to(root)),
                        "message": issue["message"],
                    }
                )

        fname = fpath.name
        doc_issues = val_result.get("issues", [])
        errors_count = sum(1 for i in doc_issues if i["severity"] == "error")
        if errors_count > 0:
            validity_details.append(f"{fname}: {errors_count} erros de estrutura")
        else:
            validity_details.append(f"{fname} OK")

    validity_score = int(sum(validity_scores) / len(validity_scores)) if validity_scores else 100
    validity_detail = "; ".join(validity_details[:5]) if validity_details else "Nenhum doc encontrado"

    if validity_score < 80:
        recommendations.append("Corrigir estrutura dos documentos — seções obrigatórias ausentes")

    # 3. Quality check (30%) — lint each markdown file
    quality_scores: list[int] = []
    quality_details: list[str] = []
    total_lint_warnings = 0

    for fpath in doc_files:
        lint_result = lint_markdown(store, settings, file_path=str(fpath))
        if "error" in lint_result:
            continue
        errors_n = lint_result.get("errors", 0)
        warnings_n = lint_result.get("warnings", 0)
        total_lint_warnings += warnings_n

        if errors_n == 0 and warnings_n == 0:
            file_score = 100
        else:
            file_score = max(0, 100 - errors_n * 10 - warnings_n * 3)
        quality_scores.append(file_score)

        for issue in lint_result.get("issues", []):
            if issue["severity"] == "error":
                all_issues.append(
                    {
                        "severity": "warning",
                        "source": "quality",
                        "file": str(fpath.relative_to(root)),
                        "message": issue["message"],
                    }
                )

        if warnings_n > 0 or errors_n > 0:
            quality_details.append(f"{fpath.name}: {warnings_n} warnings de lint")

    quality_score = int(sum(quality_scores) / len(quality_scores)) if quality_scores else 100
    if quality_details:
        quality_detail = "; ".join(quality_details[:3])
    else:
        quality_detail = "Todos os docs passaram no lint"

    if total_lint_warnings > 5:
        recommendations.append(f"Corrigir {total_lint_warnings} warnings de lint nos documentos")

    # 4. Check links in main docs
    for doc_name in ["README.md", "CHANGELOG.md"]:
        doc_path = root / doc_name
        if doc_path.exists():
            link_result = check_links(
                store, settings, file_path=str(doc_path), check_external=False
            )
            if "error" not in link_result and link_result.get("broken", 0) > 0:
                all_issues.append(
                    {
                        "severity": "warning",
                        "source": "links",
                        "file": doc_name,
                        "message": f"{link_result['broken']} link(s) quebrado(s)",
                    }
                )
                recommendations.append(f"Corrigir {link_result['broken']} link(s) quebrado(s) em {doc_name}")

    # Compute overall score
    overall_score = int(
        completeness_score * 0.30
        + validity_score * 0.40
        + quality_score * 0.30
    )
    grade = _grade(overall_score)

    return {
        "repo_path": repo_path,
        "standard": standard,
        "overall_score": overall_score,
        "grade": grade,
        "categories": {
            "completeness": {"score": completeness_score, "details": completeness_detail},
            "validity": {"score": validity_score, "details": validity_detail},
            "quality": {"score": quality_score, "details": quality_detail},
        },
        "issues": all_issues,
        "recommendations": recommendations,
    }
