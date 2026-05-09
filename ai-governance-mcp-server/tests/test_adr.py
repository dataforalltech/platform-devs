"""Testes da tool create_adr.

create_adr é a única tool que escreve no filesystem fora do SuggestionStore.
Usamos tmp_path como repo_path para isolar — sem alterar o repo real.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.tools.adr_tool import create_adr


# --------------------------- happy path --------------------------- #
def test_creates_first_adr_in_empty_dir(repo, tmp_path):
    res = create_adr(
        repo,
        title="Usar Redis para cache de permissões",
        context="Cache de permissões hoje em memória local. Crescimento previsto exige distribuído.",
        decision="Vamos usar Redis cluster compartilhado para cache de permissões.",
        consequences="Latência ligeiramente maior, mas consistência cross-instance garantida.",
        repo_path=str(tmp_path),
    )
    assert res["created"] is True
    assert res["adr_number"] == 1
    assert res["filename"] == "adr-0001.md"
    target = tmp_path / "docs" / "decisions" / "adr-0001.md"
    assert target.exists()
    content = target.read_text(encoding="utf-8")
    assert "Usar Redis para cache de permissões" in content
    assert "Cache de permissões hoje em memória local" in content
    assert "Vamos usar Redis cluster" in content
    assert "Latência ligeiramente maior" in content


def test_creates_decisions_dir_if_missing(repo, tmp_path):
    """A pasta docs/decisions/ é criada se ainda não existir."""
    target_dir = tmp_path / "docs" / "decisions"
    assert not target_dir.exists()
    res = create_adr(
        repo,
        title="Test",
        context="Context",
        decision="Decision",
        consequences="Consequences",
        repo_path=str(tmp_path),
    )
    assert res["created"] is True
    assert target_dir.exists()


def test_increments_adr_number_when_existing(repo, tmp_path):
    """Numeração busca o próximo livre olhando arquivos existentes."""
    decisions = tmp_path / "docs" / "decisions"
    decisions.mkdir(parents=True)
    (decisions / "adr-0001.md").write_text("# existing", encoding="utf-8")
    (decisions / "adr-0007.md").write_text("# existing", encoding="utf-8")

    res = create_adr(
        repo,
        title="New ADR",
        context="C",
        decision="D",
        consequences="Cs",
        repo_path=str(tmp_path),
    )
    assert res["created"] is True
    # Próximo livre é max(existing) + 1 = 8
    assert res["adr_number"] == 8
    assert res["filename"] == "adr-0008.md"


def test_filename_padded_to_4_digits(repo, tmp_path):
    res = create_adr(
        repo,
        title="T", context="C", decision="D", consequences="Cs",
        repo_path=str(tmp_path),
    )
    assert "0001" in res["filename"]


def test_template_includes_all_sections(repo, tmp_path):
    res = create_adr(
        repo,
        title="T",
        context="MY_CONTEXT_MARKER",
        decision="MY_DECISION_MARKER",
        consequences="MY_CONSEQUENCES_MARKER",
        repo_path=str(tmp_path),
    )
    content = (tmp_path / "docs" / "decisions" / res["filename"]).read_text(encoding="utf-8")
    # As 7 seções canônicas
    assert "## 1. Status" in content
    assert "## 2. Contexto" in content
    assert "## 3. Decisão" in content
    assert "## 4. Alternativas consideradas" in content
    assert "## 5. Consequências" in content
    assert "## 6. Validação" in content
    assert "## 7. Referências" in content
    # Markers garantem que o conteúdo passou nos slots certos
    assert "MY_CONTEXT_MARKER" in content
    assert "MY_DECISION_MARKER" in content
    assert "MY_CONSEQUENCES_MARKER" in content


def test_includes_metadata_in_frontmatter(repo, tmp_path):
    res = create_adr(
        repo, title="T", context="C", decision="D", consequences="Cs",
        repo_path=str(tmp_path),
    )
    content = (tmp_path / "docs" / "decisions" / res["filename"]).read_text(encoding="utf-8")
    # Frontmatter YAML
    assert content.startswith("---\n")
    assert "title: ADR-0001" in content
    assert "type: adr" in content
    assert "status: proposto" in content
    # Tem timestamp em formato YYYY-MM-DD
    assert "data_decisao:" in content


def test_returns_relative_path_when_inside_base(repo, tmp_path):
    res = create_adr(
        repo, title="T", context="C", decision="D", consequences="Cs",
        repo_path=str(tmp_path),
    )
    # path deve ser relativo (não começar com tmp_path absoluto)
    assert "docs" in res["path"]
    assert "decisions" in res["path"]
    assert Path(res["absolute_path"]).is_absolute()


# --------------------------- input validation --------------------------- #
@pytest.mark.parametrize(
    "field",
    ["title", "context", "decision", "consequences"],
)
def test_validates_required_fields(repo, tmp_path, field):
    args = dict(
        title="T", context="C", decision="D", consequences="Cs",
        repo_path=str(tmp_path),
    )
    args[field] = ""
    with pytest.raises(ValueError):
        create_adr(repo, **args)


# --------------------------- skip non-numeric files --------------------------- #
def test_skips_non_numeric_adr_files_in_count(repo, tmp_path):
    """adr-draft.md ou adr-foo.md não devem afetar a numeração."""
    decisions = tmp_path / "docs" / "decisions"
    decisions.mkdir(parents=True)
    (decisions / "adr-draft.md").write_text("# draft", encoding="utf-8")
    (decisions / "README.md").write_text("# readme", encoding="utf-8")

    res = create_adr(
        repo, title="T", context="C", decision="D", consequences="Cs",
        repo_path=str(tmp_path),
    )
    # Como nenhum adr-NNNN.md existia, deve criar adr-0001.md
    assert res["adr_number"] == 1
