"""Testes de integração do domínio `guardian` (ADR-018 Fase 1) — banco REAL.

Credencial-zero (FID-02): rodam contra um MySQL real via ``get_pool_for_tenant`` e são
SKIPADOS sem ``MYSQL_ROOT_PASSWORD``. Cobrem o núcleo versionado das diretrizes
(``gov_directive`` + ``gov_directive_version``), o vocabulário de referência (kinds/status),
a invariante "exatamente uma versão vigente por uid" e o roteamento via catálogo.
"""

from __future__ import annotations

import os
import socket
from pathlib import Path
from typing import Any

import aiomysql
import pytest
import pytest_asyncio
from platform_core.request_context import reset_tenant_id, set_tenant_id
from platform_database import close_tenant_pools
from platform_database.orm import configure
from platform_database.orm.dialects import dialect_for_pool
from platform_database.orm.tenant import TenantSession
from platform_database.tenant_resolver import get_pool_for_tenant

from src.config.settings import DevteamSettings
from src.domains.guardian.catalog import dispatch
from src.domains.guardian.db.schema import (
    DIRECTIVE_RELATION_TABLE,
    DIRECTIVE_SECTION_TABLE,
    DIRECTIVE_TABLE,
    DIRECTIVE_VERSION_TABLE,
    KIND_CAPABILITY_TABLE,
    LCR_DETAIL_TABLE,
    LCR_SUBSTITUTION_TABLE,
    STATUS_VOCAB_TABLE,
    ensure_schema,
)
from src.domains.guardian.db.store import (
    KIND_CAPABILITIES,
    STATUS_VOCAB,
    GuardianStore,
    GuardianValidationError,
)

_HOST = os.environ.get("PILOT_MYSQL_HOST", "127.0.0.1")
_PORT = int(os.environ.get("PILOT_MYSQL_PORT", "3306"))
_PW = os.environ.get("MYSQL_ROOT_PASSWORD", "")
_TENANT = "devteam_guardian_test"
_ALL_TABLES = (
    DIRECTIVE_RELATION_TABLE,
    DIRECTIVE_SECTION_TABLE,
    LCR_SUBSTITUTION_TABLE,
    LCR_DETAIL_TABLE,
    DIRECTIVE_VERSION_TABLE,
    DIRECTIVE_TABLE,
    STATUS_VOCAB_TABLE,
    KIND_CAPABILITY_TABLE,
)
_configured = False


def _mysql_up() -> bool:
    if not _PW:
        return False
    try:
        with socket.create_connection((_HOST, _PORT), timeout=2):
            return True
    except OSError:
        return False


requires_mysql = pytest.mark.skipif(
    not _mysql_up(),
    reason="MySQL real indisponível (defina MYSQL_ROOT_PASSWORD/PILOT_MYSQL_HOST/PILOT_MYSQL_PORT)",
)


def _settings() -> DevteamSettings:
    return DevteamSettings(
        MCP_TWIN_AUDIENCE="mcp:devteam-mcp",
        URL_ADMIN_TWIN_JWKS="http://admin.local/jwks.json",
        DB_ENGINE="mysql",
        DB_HOST=_HOST,
        DB_PORT=_PORT,
        DB_USER="root",
        DB_PASSWORD=_PW,
        ADMIN_DB_HOST=_HOST,
        ADMIN_DB_PORT=_PORT,
        ADMIN_DB_USER="root",
        ADMIN_DB_PASSWORD=_PW,
    )


async def _lookup(tenant_id: str, _s: Any) -> dict[str, Any] | None:
    if tenant_id != _TENANT:
        return None
    return {
        "tenant_id": tenant_id,
        "db_engine": "mysql",
        "db_host": _HOST,
        "db_port": _PORT,
        "db_name": tenant_id,
        "db_user": "root",
        "db_password": _PW,
    }


async def _root_exec(sql: str) -> None:
    conn = await aiomysql.connect(
        host=_HOST, port=_PORT, user="root", password=_PW, autocommit=True
    )
    try:
        async with conn.cursor() as cur:
            await cur.execute(sql)
    finally:
        conn.close()


async def _make_store() -> tuple[GuardianStore, Any]:
    global _configured
    settings = _settings()
    if not _configured:
        configure(settings)
        _configured = True
    await _root_exec(f"CREATE DATABASE IF NOT EXISTS {_TENANT} CHARACTER SET utf8mb4")
    pool = await get_pool_for_tenant(
        settings, _TENANT, platform_lookup=_lookup, strict=True
    )
    await ensure_schema(pool, engine=dialect_for_pool(pool).name)
    for table in _ALL_TABLES:
        await pool.execute(f"TRUNCATE TABLE {table}")
    token = set_tenant_id(_TENANT)
    return GuardianStore(TenantSession(pool, _TENANT)), token


@pytest_asyncio.fixture
async def store():
    st, token = await _make_store()
    yield st
    reset_tenant_id(token)
    await close_tenant_pools()


# -- referência (seed + leitura) ---------------------------------------------- #


@requires_mysql
@pytest.mark.asyncio
async def test_seed_reference_data_is_idempotent(store: GuardianStore) -> None:
    first = await store.seed_reference_data()
    assert first == {"kinds": len(KIND_CAPABILITIES), "status": len(STATUS_VOCAB)}
    # Idempotente: rodar de novo não duplica (upsert por chave natural).
    await store.seed_reference_data()
    kinds = await store.list_kinds()
    status = await store.list_status_vocab()
    assert len(kinds) == len(KIND_CAPABILITIES)
    assert len(status) == len(STATUS_VOCAB)
    std = next(k for k in kinds if k["kind"] == "standard")
    assert std["allows_rfc2119"] is True and std["layer"] == 3


# -- CRUD do núcleo versionado ------------------------------------------------ #


@requires_mysql
@pytest.mark.asyncio
async def test_create_directive_persists_header_and_v1(store: GuardianStore) -> None:
    out = await store.create_directive(
        directive_uid="STD-SEC-001",
        kind="standard",
        title="Hardening",
        body_context="Contexto",
        body_decision="Decisão",
        author_ref="caio",
    )
    assert out["directive_uid"] == "STD-SEC-001"
    assert out["directive_scope"] == "platform"
    assert out["scope_rank"] == 1
    cur = out["current_version"]
    assert cur["version"] == 1 and cur["is_current"] is True
    assert cur["status"] == "proposto"
    assert cur["content_sha256"]


@requires_mysql
@pytest.mark.asyncio
async def test_create_directive_rejects_bad_kind(store: GuardianStore) -> None:
    with pytest.raises(GuardianValidationError):
        await store.create_directive(directive_uid="X-1", kind="nope", title="T")


@requires_mysql
@pytest.mark.asyncio
async def test_project_scope_requires_project_ref(store: GuardianStore) -> None:
    with pytest.raises(GuardianValidationError):
        await store.create_directive(
            directive_uid="STD-P-1", kind="standard", title="T", scope="project"
        )
    ok = await store.create_directive(
        directive_uid="STD-P-2",
        kind="standard",
        title="T",
        scope="project",
        project_ref="proj-1",
    )
    assert ok["directive_scope"] == "project"
    assert ok["scope_rank"] == 3
    assert ok["project_ref"] == "proj-1"


@requires_mysql
@pytest.mark.asyncio
async def test_duplicate_uid_rejected(store: GuardianStore) -> None:
    await store.create_directive(directive_uid="ADR-0001", kind="adr", title="A")
    with pytest.raises(GuardianValidationError):
        await store.create_directive(
            directive_uid="ADR-0001", kind="adr", title="A dup"
        )


@requires_mysql
@pytest.mark.asyncio
async def test_update_directive_appends_version_and_keeps_one_current(
    store: GuardianStore,
) -> None:
    await store.create_directive(directive_uid="ADR-0002", kind="adr", title="A")
    updated = await store.update_directive(
        directive_uid="ADR-0002",
        status="aceito",
        body_decision="v2",
        change_reason="revisão",
    )
    assert updated["current_version"]["version"] == 2
    assert updated["current_version"]["status"] == "aceito"
    # Invariante: exatamente 1 vigente por uid.
    res = await store._versions.find(
        where={"directive_uid": "ADR-0002", "is_current": True}
    )
    assert len(res.rows()) == 1
    # E existem 2 versões no total (append-only).
    allv = await store._versions.find(where={"directive_uid": "ADR-0002"})
    assert len(allv.rows()) == 2


@requires_mysql
@pytest.mark.asyncio
async def test_set_directive_status(store: GuardianStore) -> None:
    await store.create_directive(
        directive_uid="P-005", kind="principle", title="Least privilege"
    )
    out = await store.set_directive_status(directive_uid="P-005", status="aceito")
    assert out["current_version"]["status"] == "aceito"
    assert out["current_version"]["version"] == 1  # sem nova versão


@requires_mysql
@pytest.mark.asyncio
async def test_supersede_directive(store: GuardianStore) -> None:
    await store.create_directive(directive_uid="STD-OLD", kind="standard", title="Old")
    await store.create_directive(directive_uid="STD-NEW", kind="standard", title="New")
    out = await store.supersede_directive(
        directive_uid="STD-OLD", superseded_by_uid="STD-NEW"
    )
    assert out["superseded_by_uid"] == "STD-NEW"
    assert out["current_version"]["status"] == "substituido"


@requires_mysql
@pytest.mark.asyncio
async def test_list_directives_filters(store: GuardianStore) -> None:
    await store.create_directive(directive_uid="STD-A", kind="standard", title="A")
    await store.create_directive(directive_uid="RB-A", kind="runbook", title="B")
    await store.set_directive_status(directive_uid="STD-A", status="aceito")
    only_std = await store.list_directives(kind="standard")
    assert [d["directive_uid"] for d in only_std] == ["STD-A"]
    accepted = await store.list_directives(status="aceito")
    assert [d["directive_uid"] for d in accepted] == ["STD-A"]
    assert only_std[0]["current_status"] == "aceito"


# -- roteamento via catálogo (contrato do plugin) ----------------------------- #


@requires_mysql
@pytest.mark.asyncio
async def test_dispatch_create_and_get_via_catalog(store: GuardianStore) -> None:
    created = await dispatch(
        "create_directive",
        {
            "directive_uid": "ADR-0009",
            "kind": "adr",
            "title": "Guardian",
            "status": "aceito",
        },
        store,
    )
    assert created["directive_uid"] == "ADR-0009"
    got = await dispatch("get_directive", {"directive_uid": "ADR-0009"}, store)
    assert got["current_version"]["status"] == "aceito"
    listing = await dispatch("list_directives", {"kind": "adr"}, store)
    assert any(d["directive_uid"] == "ADR-0009" for d in listing["directives"])


@requires_mysql
@pytest.mark.asyncio
async def test_dispatch_validation_error_is_enveloped(store: GuardianStore) -> None:
    out = await dispatch(
        "create_directive",
        {"directive_uid": "Z-1", "kind": "bogus", "title": "T"},
        store,
    )
    assert out["error"] == "ValidationError"


@requires_mysql
@pytest.mark.asyncio
async def test_get_missing_directive_returns_not_found(store: GuardianStore) -> None:
    out = await dispatch("get_directive", {"directive_uid": "DOES-NOT-EXIST"}, store)
    assert out["error"] == "not_found"


# -- import_hub / validate_hub (ADR-018 Fase 1b) ------------------------------ #

_HUB_ADR = """---
type: adr
camada: "ADR (Camada 2)"
status: aceito
ultima_atualizacao: 2026-07-15
escopo: plataforma
---

# ADR-0022 — Runtime oficial Docker Swarm

## Contexto

Precisamos de um runtime oficial.

## Decisão

Docker Swarm é o runtime oficial.
"""

_HUB_ADR_V2 = """---
type: adr
camada: "ADR (Camada 2)"
status: aceito
ultima_atualizacao: 2026-08-01
escopo: plataforma
---

# ADR-0022 — Runtime oficial Docker Swarm

## Contexto

Precisamos de um runtime oficial (revisado).

## Decisão

Docker Swarm é o runtime oficial; Kubernetes fica experimental.
"""

_HUB_PRINCIPLE = """---
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


def _write_hub_file(root: Path, layer: str, name: str, content: str) -> None:
    layer_dir = root / layer
    layer_dir.mkdir(parents=True, exist_ok=True)
    (layer_dir / name).write_text(content, encoding="utf-8")


@requires_mysql
@pytest.mark.asyncio
async def test_import_hub_creates_directives_from_markdown(
    store: GuardianStore, tmp_path: Path
) -> None:
    hub = tmp_path / "docs"
    _write_hub_file(hub, "adr", "0022-runtime-swarm.md", _HUB_ADR)
    _write_hub_file(hub, "principles", "P-001-cloud-native.md", _HUB_PRINCIPLE)

    out = await dispatch("import_hub", {"hub_root": str(hub)}, store)
    assert out["created"] == 2
    assert out["updated"] == 0
    assert out["parse_errors"] == []

    adr = await store.get_directive("ADR-0022")
    assert adr is not None
    assert adr["current_version"]["status"] == "aceito"
    principle = await store.get_directive("P-001")
    assert principle is not None and principle["kind"] == "principle"


@requires_mysql
@pytest.mark.asyncio
async def test_import_hub_is_idempotent_and_versions_on_change(
    store: GuardianStore, tmp_path: Path
) -> None:
    hub = tmp_path / "docs"
    _write_hub_file(hub, "adr", "0022-runtime-swarm.md", _HUB_ADR)

    first = await dispatch("import_hub", {"hub_root": str(hub)}, store)
    assert first["created"] == 1

    # Reimport sem mudança nenhuma -> no-op.
    second = await dispatch("import_hub", {"hub_root": str(hub)}, store)
    assert second["created"] == 0
    assert second["updated"] == 0
    assert second["unchanged"] == 1

    # Conteúdo mudou -> nova versão (append-only), não sobrescreve.
    _write_hub_file(hub, "adr", "0022-runtime-swarm.md", _HUB_ADR_V2)
    third = await dispatch("import_hub", {"hub_root": str(hub)}, store)
    assert third["updated"] == 1
    adr = await store.get_directive("ADR-0022")
    assert adr["current_version"]["version"] == 2
    assert "Kubernetes" in adr["current_version"]["body_decision"]


@requires_mysql
@pytest.mark.asyncio
async def test_import_hub_reports_parse_errors_without_aborting(
    store: GuardianStore, tmp_path: Path
) -> None:
    hub = tmp_path / "docs"
    _write_hub_file(hub, "adr", "0022-runtime-swarm.md", _HUB_ADR)
    _write_hub_file(hub, "adr", "sem-front-matter.md", "# Sem front matter\n")

    out = await dispatch("import_hub", {"hub_root": str(hub)}, store)
    assert out["created"] == 1
    assert len(out["parse_errors"]) == 1
    assert "sem-front-matter" in out["parse_errors"][0]["path"]


@requires_mysql
@pytest.mark.asyncio
async def test_validate_hub_reports_drift_without_writing(
    store: GuardianStore, tmp_path: Path
) -> None:
    hub = tmp_path / "docs"
    _write_hub_file(hub, "adr", "0022-runtime-swarm.md", _HUB_ADR)

    before = await dispatch("validate_hub", {"hub_root": str(hub)}, store)
    assert before["in_sync"] is False
    assert any(d["drift"] == "missing_in_db" for d in before["drift"])
    # validate_hub é dry-run: nada foi persistido.
    assert await store.get_directive("ADR-0022") is None

    await dispatch("import_hub", {"hub_root": str(hub)}, store)
    after_import = await dispatch("validate_hub", {"hub_root": str(hub)}, store)
    assert after_import["in_sync"] is True
    assert after_import["drift"] == []

    # Diretiva órfã: existe no DB mas o arquivo sumiu do hub.
    (hub / "adr" / "0022-runtime-swarm.md").unlink()
    after_delete = await dispatch("validate_hub", {"hub_root": str(hub)}, store)
    assert after_delete["in_sync"] is False
    assert any(
        d["directive_uid"] == "ADR-0022" for d in after_delete["orphan_directives"]
    )


# -- LCR: metadados de gestão de mudança + validação kind-scoped (ADR-018 Fase 1c) #

_LCR_HUB_BODY = """---
type: lib-change-request
title: "LCR-005 — Atualizar log-uploader"
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
substituido_por:
  - "../standards/STD-SEC-001-hardening.md"
data_solicitacao: "2026-06-04"
---

# LCR-005 — Atualizar log-uploader
"""


@requires_mysql
@pytest.mark.asyncio
async def test_set_and_get_lcr_detail(store: GuardianStore) -> None:
    await store.create_directive(
        directive_uid="LCR-005-log-uploader",
        kind="lib_change_request",
        title="LCR-005",
        status="pendente-aprovacao",
    )
    out = await store.set_lcr_detail(
        directive_uid="LCR-005-log-uploader",
        biblioteca="platform-log-uploader-lib",
        versao_atual="v0.1.0",
        versao_alvo="v0.2.0",
        tipo="minor",
        breaking=False,
        urgencia="high",
        data_solicitacao="2026-06-04",
    )
    assert out["biblioteca"] == "platform-log-uploader-lib"
    assert out["breaking"] is False
    got = await store.get_lcr_detail("LCR-005-log-uploader")
    assert got is not None and got["versao_alvo"] == "v0.2.0"

    # Upsert idempotente: reaplicar não duplica, só atualiza.
    await store.set_lcr_detail(
        directive_uid="LCR-005-log-uploader", versao_alvo="v0.3.0"
    )
    updated = await store.get_lcr_detail("LCR-005-log-uploader")
    assert updated["versao_alvo"] == "v0.3.0"


@requires_mysql
@pytest.mark.asyncio
async def test_lcr_substitution_edges_are_idempotent(store: GuardianStore) -> None:
    await store.create_directive(
        directive_uid="LCR-006",
        kind="lib_change_request",
        title="T",
        status="pendente-aprovacao",
    )
    await store.add_lcr_substitution(
        lcr_directive_uid="LCR-006", target_ref="../standards/STD-SEC-001.md"
    )
    await store.add_lcr_substitution(
        lcr_directive_uid="LCR-006", target_ref="../standards/STD-SEC-001.md"
    )  # idempotente — não duplica
    await store.add_lcr_substitution(
        lcr_directive_uid="LCR-006", target_ref="../standards/STD-SEC-002.md"
    )
    subs = await store.list_lcr_substitutions("LCR-006")
    assert subs == ["../standards/STD-SEC-001.md", "../standards/STD-SEC-002.md"]


@requires_mysql
@pytest.mark.asyncio
async def test_lcr_status_rejected_for_non_lcr_kind(store: GuardianStore) -> None:
    with pytest.raises(GuardianValidationError):
        await store.create_directive(
            directive_uid="STD-X",
            kind="standard",
            status="pendente-aprovacao",
            title="T",
        )


@requires_mysql
@pytest.mark.asyncio
async def test_generic_status_rejected_via_update_and_set_status_kind_scope(
    store: GuardianStore,
) -> None:
    await store.create_directive(
        directive_uid="LCR-007",
        kind="lib_change_request",
        title="T",
        status="pendente-aprovacao",
    )
    # "proposto" é kind-agnóstico (applies_to_kind=None) -> permitido em qualquer kind.
    ok = await store.update_directive(directive_uid="LCR-007", status="proposto")
    assert ok["current_version"]["status"] == "proposto"
    # "aceito" também é kind-agnóstico.
    ok2 = await store.set_directive_status(directive_uid="LCR-007", status="aceito")
    assert ok2["current_version"]["status"] == "aceito"


@requires_mysql
@pytest.mark.asyncio
async def test_import_hub_syncs_lcr_detail_and_substitutions(
    store: GuardianStore, tmp_path: Path
) -> None:
    hub = tmp_path / "docs"
    _write_hub_file(
        hub, "lib-change-requests", "LCR-005-log-uploader.md", _LCR_HUB_BODY
    )

    out = await dispatch("import_hub", {"hub_root": str(hub)}, store)
    assert out["created"] == 1

    detail = await dispatch(
        "get_lcr_detail", {"directive_uid": "LCR-005-log-uploader"}, store
    )
    assert detail["biblioteca"] == "platform-log-uploader-lib"
    assert detail["data_solicitacao"] == "2026-06-04"

    subs = await dispatch(
        "list_lcr_substitutions", {"directive_uid": "LCR-005-log-uploader"}, store
    )
    assert subs["substitutions"] == ["../standards/STD-SEC-001-hardening.md"]

    directive = await store.get_directive("LCR-005-log-uploader")
    assert directive["current_version"]["status"] == "pendente-aprovacao"


# -- Fase 2: escopo archetype, seções tipadas, relações ------------------------ #


@requires_mysql
@pytest.mark.asyncio
async def test_archetype_scope_requires_archetype_ref(store: GuardianStore) -> None:
    with pytest.raises(GuardianValidationError):
        await store.create_directive(
            directive_uid="STD-ARQ-1", kind="standard", title="T", scope="archetype"
        )
    ok = await store.create_directive(
        directive_uid="STD-ARQ-2",
        kind="standard",
        title="T",
        scope="archetype",
        archetype_ref="frontend-produto",
    )
    assert ok["directive_scope"] == "archetype"
    assert ok["scope_rank"] == 2
    assert ok["archetype_ref"] == "frontend-produto"


@requires_mysql
@pytest.mark.asyncio
async def test_project_ref_rejected_outside_project_scope(
    store: GuardianStore,
) -> None:
    with pytest.raises(GuardianValidationError):
        await store.create_directive(
            directive_uid="STD-X",
            kind="standard",
            title="T",
            scope="platform",
            project_ref="proj-1",  # project_ref só faz sentido com scope='project'
        )


@requires_mysql
@pytest.mark.asyncio
async def test_replace_sections_upserts_in_place(store: GuardianStore) -> None:
    await store.create_directive(
        directive_uid="IT-001", kind="work_instruction", title="T"
    )
    first = await store.replace_sections(
        directive_uid="IT-001",
        version=1,
        sections=[
            {
                "order_index": 0,
                "section_key": "pre_requisitos",
                "heading": "Pré-requisitos",
                "content": "A",
            },
            {
                "order_index": 1,
                "section_key": "procedimento",
                "heading": "Procedimento",
                "content": "B",
            },
        ],
    )
    assert [s["heading"] for s in first] == ["Pré-requisitos", "Procedimento"]

    # Reimportação do MESMO conjunto de índices -> upsert em cima (idempotente).
    second = await store.replace_sections(
        directive_uid="IT-001",
        version=1,
        sections=[
            {
                "order_index": 0,
                "section_key": "pre_requisitos",
                "heading": "Pré-requisitos",
                "content": "A2",
            },
            {
                "order_index": 1,
                "section_key": "procedimento",
                "heading": "Procedimento",
                "content": "B2",
            },
        ],
    )
    assert [s["content"] for s in second] == ["A2", "B2"]

    # Limitação DOCUMENTADA: reimportar com MENOS seções não remove o
    # order_index extra da rodada anterior (fica stale até ser sobrescrito) —
    # o MySQL não tem índice único parcial, então soft-delete colidiria com a
    # constraint natural ao reinserir a mesma chave.
    third = await store.replace_sections(
        directive_uid="IT-001",
        version=1,
        sections=[
            {
                "order_index": 0,
                "section_key": "pre_requisitos",
                "heading": "Pré-requisitos",
                "content": "A3",
            },
        ],
    )
    assert [s["content"] for s in third] == ["A3", "B2"]  # index 1 = stale, não sumiu

    listed = await store.list_sections("IT-001")  # sem version -> vigente (1)
    assert listed == third


@requires_mysql
@pytest.mark.asyncio
async def test_relations_add_list_remove_are_idempotent(store: GuardianStore) -> None:
    await store.create_directive(
        directive_uid="IT-002", kind="work_instruction", title="T"
    )
    await store.add_relation(
        from_uid="IT-002", to_ref="STD-ARCH-001", relation_type="governed_by"
    )
    await store.add_relation(  # idempotente — não duplica
        from_uid="IT-002", to_ref="STD-ARCH-001", relation_type="governed_by"
    )
    await store.add_relation(
        from_uid="IT-002", to_ref="STD-DATA-001", relation_type="governed_by"
    )
    rels = await store.list_relations("IT-002")
    assert [r["to_ref"] for r in rels] == ["STD-ARCH-001", "STD-DATA-001"]

    await store.remove_relation(
        from_uid="IT-002", to_ref="STD-ARCH-001", relation_type="governed_by"
    )
    remaining = await store.list_relations("IT-002")
    assert [r["to_ref"] for r in remaining] == ["STD-DATA-001"]


@requires_mysql
@pytest.mark.asyncio
async def test_add_relation_rejects_unknown_relation_type(
    store: GuardianStore,
) -> None:
    with pytest.raises(GuardianValidationError):
        await store.add_relation(
            from_uid="IT-003", to_ref="STD-X", relation_type="bogus_relation"
        )


_IT_HUB_BODY = """---
type: instrucao-de-trabalho
title: IT-001 — Criar novo serviço
status: aceito
governado_por: STD-ARCH-001, STD-DATA-001
---

# IT-001 — Criar novo serviço

## Pré-requisitos

Ter acesso ao repo.

## Procedimento

1. Clonar.
"""


@requires_mysql
@pytest.mark.asyncio
async def test_import_hub_syncs_sections_and_governed_by(
    store: GuardianStore, tmp_path: Path
) -> None:
    hub = tmp_path / "docs"
    _write_hub_file(hub, "it", "IT-001-criar-servico.md", _IT_HUB_BODY)

    out = await dispatch("import_hub", {"hub_root": str(hub)}, store)
    assert out["created"] == 1

    sections = await dispatch("list_sections", {"directive_uid": "IT-001"}, store)
    assert [s["heading"] for s in sections["sections"]] == [
        "Pré-requisitos",
        "Procedimento",
    ]

    relations = await dispatch("list_relations", {"from_uid": "IT-001"}, store)
    assert [r["to_ref"] for r in relations["relations"]] == [
        "STD-ARCH-001",
        "STD-DATA-001",
    ]
