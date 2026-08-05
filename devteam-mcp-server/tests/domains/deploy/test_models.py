# Portado de `deploy-mcp-server/tests/test_models.py` pelo fan-out de testes.
#
# O código de tool do agregador é byte-a-byte o do servidor legado; só o caminho
# de import muda. Gerado por `scripts/port_domain_tests.py` — reexecutar é
# idempotente. Editar aqui diverge da origem: corrija no legado e reexecute, ou
# aposente o legado (ver ROADMAP, fechar o strangler).

"""Testes para os modelos pydantic de deploy-mcp-server."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.domains.deploy.models.deploy import (
    CheckRun,
    FileChange,
    PRInfo,
)


def test_file_change_requires_path_and_content():
    fc = FileChange(path="src/main.py", content="print('hi')")
    assert fc.path == "src/main.py"
    with pytest.raises(ValidationError):
        FileChange(path="only-path")  # type: ignore[call-arg]


def test_check_run_optional_conclusion():
    cr = CheckRun(name="ci", status="completed", url="http://x")
    assert cr.conclusion is None


def test_pr_info_defaults():
    pr = PRInfo(
        number=1,
        title="t",
        state="open",
        url="http://x",
        head="feature/x",
        base="develop",
        head_sha="abc1234",
    )
    assert pr.draft is False
    assert pr.checks == []
    assert pr.mergeable is None


