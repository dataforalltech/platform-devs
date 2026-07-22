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


# -- Fase 1c: lib-change-requests / handoffs / specs -------------------------- #

_LCR_BODY = """---
type: lib-change-request
title: "LCR-005 — Atualizar log-uploader"
codigo: LCR-005
camada: lcr
escopo: servico
biblioteca: platform-log-uploader-lib
repositorio: dataforalltech/platform-log-uploader-lib
versao_atual: "v0.1.0"
versao_alvo: "v0.2.0"
tipo: minor
breaking: false
urgencia: high
status: pendente-aprovacao
aprovador: caiog
solicitante: alguem
achado: "CRY-02"
governado_por: "../standards/STD-ARCH-002-shared-libraries.md"
substituido_por:
  - "../standards/STD-SEC-001-hardening.md"
  - "../standards/STD-SEC-002-outro.md"
data_solicitacao: "2026-06-04"
ultima_atualizacao: 2026-07-20
---

# LCR-005 — Atualizar log-uploader

## O que mudar na lib

Bump de versão.
"""

_LCR_DUPLICATE_NUMBER_BODY = """---
type: lib-change-request
title: "LCR-005 — Atualizar ws-ticket"
status: aprovado
data_solicitacao: "2026-06-10"
---

# LCR-005 — Atualizar ws-ticket
"""

_HANDOFF_BODY = """---
type: handoff
title: Handoff da sessão de guardian
---

# Handoff 2026-07-22

Resumo da sessão.
"""

_HANDOFF_NO_STATUS = """# Handoff sem front-matter completo

Só um título, sem front-matter de verdade (nem YAML).
"""

_SPEC_BODY = """---
type: spec
title: Spec de exemplo
---

# Spec — exemplo

Descrição pontual.
"""


def test_parse_lcr_extracts_change_management_fields(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    path = _write(root, "lib-change-requests", "LCR-005-log-uploader.md", _LCR_BODY)
    doc = parse_markdown_doc("lib-change-requests", path, root)
    assert doc.directive_uid == "LCR-005-log-uploader"  # stem inteiro, sem regex
    assert doc.kind == "lib_change_request"
    assert doc.status == "pendente-aprovacao"
    assert doc.lcr_detail is not None
    assert doc.lcr_detail["biblioteca"] == "platform-log-uploader-lib"
    assert doc.lcr_detail["versao_atual"] == "v0.1.0"
    assert doc.lcr_detail["breaking"] is False
    assert doc.lcr_detail["data_solicitacao"] == "2026-06-04"
    assert doc.lcr_substituted_by == (
        "../standards/STD-SEC-001-hardening.md",
        "../standards/STD-SEC-002-outro.md",
    )


def test_lcr_duplicate_number_different_slug_does_not_collide(tmp_path: Path) -> None:
    """Achado real da pesquisa: LCR permite números duplicados com slugs
    diferentes (dois LCR-005 coexistindo). O UID tem que ser o stem inteiro,
    não só o prefixo numérico, senão os dois colidem."""
    root = tmp_path / "docs"
    _write(root, "lib-change-requests", "LCR-005-log-uploader.md", _LCR_BODY)
    _write(
        root,
        "lib-change-requests",
        "LCR-005-ws-ticket.md",
        _LCR_DUPLICATE_NUMBER_BODY,
    )
    docs, errors = scan_hub(root)
    assert errors == []
    uids = {d.directive_uid for d in docs}
    assert uids == {"LCR-005-log-uploader", "LCR-005-ws-ticket"}


def test_parse_handoff_uses_full_stem_as_uid(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    path = _write(root, "handoffs", "2026-07-22-guardian-fase1.md", _HANDOFF_BODY)
    doc = parse_markdown_doc("handoffs", path, root)
    assert doc.directive_uid == "2026-07-22-guardian-fase1"
    assert doc.kind == "handoff"
    assert doc.title == "Handoff da sessão de guardian"
    assert doc.lcr_detail is None
    assert doc.lcr_substituted_by == ()


def test_parse_handoff_without_front_matter_falls_back_to_aceito_status(
    tmp_path: Path,
) -> None:
    """Handoffs/specs não têm front-matter uniformemente exigido pelo hub —
    ausência total de front-matter ainda é um erro (sem seção YAML nenhuma),
    mas status ausente COM front-matter presente cai no fallback 'aceito'."""
    root = tmp_path / "docs"
    path = _write(root, "handoffs", "2026-07-22-sem-status.md", _HANDOFF_NO_STATUS)
    with pytest.raises(ImporterError, match="sem front-matter"):
        parse_markdown_doc("handoffs", path, root)


def test_parse_handoff_with_front_matter_but_no_status_defaults_to_aceito(
    tmp_path: Path,
) -> None:
    root = tmp_path / "docs"
    body = "---\ntype: handoff\n---\n\n# Handoff sem status\n"
    path = _write(root, "handoffs", "2026-07-22-sem-status-field.md", body)
    doc = parse_markdown_doc("handoffs", path, root)
    assert doc.status == "aceito"


def test_parse_spec_uses_stem_as_uid(tmp_path: Path) -> None:
    root = tmp_path / "docs"
    path = _write(root, "specs", "exemplo-de-spec.md", _SPEC_BODY)
    doc = parse_markdown_doc("specs", path, root)
    assert doc.directive_uid == "exemplo-de-spec"
    assert doc.kind == "spec"
    assert doc.title == "Spec de exemplo"  # front-matter tem precedência sobre H1
