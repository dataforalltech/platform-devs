"""Testes unitários do importador markdown→DB do guardian (ADR-018 Fase 1b).

Puramente de parsing — sem banco (contraste com `test_guardian.py`, que cobre a
persistência). Usa arquivos sintéticos em `tmp_path` para não depender do repo
`platform-service-template` estar clonado no ambiente de CI.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.domains.guardian.importer import (
    ImporterError,
    discover_hub_files,
    parse_markdown_doc,
    scan_hub,
)

_ADR_BODY = """---
type: adr
camada: "ADR (Camada 2)"
status: aceito
ultima_atualizacao: 2026-07-15
escopo: plataforma
---

# ADR-0022 — Runtime oficial Docker Swarm

## Status

Aceito.

## Contexto

Precisamos de um runtime oficial.

## Decisão

Docker Swarm é o runtime oficial; Kubernetes fica experimental.

## Consequências

Positivas: simplicidade. Negativas: menos ecossistema.
"""

_PRINCIPLE_BODY = """---
type: architecture-principle
camada: 1
status: aceito
ultima_atualizacao: 2026-07-15
escopo: servico
---

# Cloud-native first

## Enunciado

Serviços devem ser cloud-native por padrão.
"""

_RUNBOOK_VIGENTE = """---
type: runbook
camada: 5
status: vigente
ultima_atualizacao: 2026-07-15
escopo: plataforma
---

# Rollback

## Procedimento

1. Reverter o deploy.
"""

_NO_FRONT_MATTER = "# Sem front matter\n\nCorpo qualquer.\n"

_BAD_STATUS = """---
type: adr
camada: "ADR (Camada 2)"
status: inventado-nao-existe
ultima_atualizacao: 2026-07-15
escopo: plataforma
---

# ADR-9999 — Teste
"""


def _write(root: Path, layer: str, name: str, content: str) -> Path:
    layer_dir = root / layer
    layer_dir.mkdir(parents=True, exist_ok=True)
    path = layer_dir / name
    path.write_text(content, encoding="utf-8")
    return path


def test_parse_adr_derives_uid_title_and_splits_body(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    path = _write(root, "adr", "0022-runtime-swarm.md", _ADR_BODY)
    doc = parse_markdown_doc("adr", path, root)
    assert doc.directive_uid == "ADR-0022"
    assert doc.kind == "adr"
    assert doc.title == "Runtime oficial Docker Swarm"
    assert doc.scope == "platform"
    assert doc.status == "aceito"
    assert doc.body_context is not None and "## Contexto" in doc.body_context
    assert doc.body_decision is not None and "## Decisão" in doc.body_decision
    assert "Consequências" not in doc.body_context


def test_parse_principle_uid_from_filename(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    path = _write(root, "principles", "P-001-cloud-native-first.md", _PRINCIPLE_BODY)
    doc = parse_markdown_doc("principles", path, root)
    assert doc.directive_uid == "P-001"
    assert doc.kind == "principle"
    assert doc.title == "Cloud-native first"
    # Sem heading de decisão conhecido -> tudo vira body_context, nada se perde.
    assert doc.body_decision is None
    assert doc.body_context is not None and "Enunciado" in doc.body_context


def test_parse_runbook_status_vigente_is_aliased_to_aceito(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    path = _write(root, "runbooks", "RUNBOOK-rollback.md", _RUNBOOK_VIGENTE)
    doc = parse_markdown_doc("runbooks", path, root)
    assert doc.directive_uid == "RUNBOOK-rollback"
    assert doc.status == "aceito"


def test_decisions_layer_uses_platform_adr_namespace_to_avoid_collision(
    tmp_path: Path,
) -> None:
    root = tmp_path / "docs"
    path = _write(root, "decisions", "adr-0001.md", _ADR_BODY)
    doc = parse_markdown_doc("decisions", path, root)
    assert doc.directive_uid == "PLATFORM-ADR-0001"
    assert doc.kind == "platform_decision"


def test_missing_front_matter_raises_importer_error(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    path = _write(root, "adr", "0001-sem-front-matter.md", _NO_FRONT_MATTER)
    with pytest.raises(ImporterError, match="sem front-matter"):
        parse_markdown_doc("adr", path, root)


def test_unrecognized_filename_convention_raises_importer_error(
    tmp_path: Path,
) -> None:
    root = tmp_path / "docs"
    path = _write(root, "adr", "sem-numero.md", _ADR_BODY)
    with pytest.raises(ImporterError, match="convenção"):
        parse_markdown_doc("adr", path, root)


def test_discover_hub_files_excludes_readme(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    _write(root, "adr", "0022-runtime-swarm.md", _ADR_BODY)
    _write(root, "adr", "README.md", "# índice\n")
    found = discover_hub_files(root)
    assert len(found) == 1
    assert found[0][1].name == "0022-runtime-swarm.md"


def test_scan_hub_does_not_validate_status_vocabulary(tmp_path: Path) -> None:
    """O importer só exige que o campo exista — a validação contra o
    vocabulário (STATUS_VOCAB) acontece na persistência (store.import_directive
    -> create_directive/update_directive), não no parsing."""
    root = tmp_path / "docs"
    _write(root, "adr", "0022-runtime-swarm.md", _ADR_BODY)
    _write(root, "adr", "0099-status-invalido.md", _BAD_STATUS)
    docs, errors = scan_hub(root)
    assert len(docs) == 2
    assert errors == []
    bad = next(d for d in docs if d.directive_uid == "ADR-0099")
    assert bad.status == "inventado-nao-existe"


def test_scan_hub_aborts_file_on_missing_front_matter_only(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    _write(root, "adr", "0022-runtime-swarm.md", _ADR_BODY)
    _write(root, "adr", "0001-sem-front-matter.md", _NO_FRONT_MATTER)
    docs, errors = scan_hub(root)
    assert len(docs) == 1
    assert docs[0].directive_uid == "ADR-0022"
    assert len(errors) == 1
    assert errors[0]["path"] == "adr\\0001-sem-front-matter.md" or errors[0][
        "path"
    ].endswith("0001-sem-front-matter.md")


def test_scan_hub_empty_root_returns_nothing(tmp_path: Path) -> None:
    docs, errors = scan_hub(tmp_path / "docs")
    assert docs == []
    assert errors == []
