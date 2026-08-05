"""Fixtures sem banco do domínio ai-governance.

Portadas de `ai-governance-mcp-server/tests/conftest.py`. O `GovernanceRepository`
é compute puro sobre a knowledge-base em disco — não abre conexão.

O domínio tem hífen no nome, então o import usa `importlib.import_module` com o
caminho como string, exatamente como o agregador faz em `src/domains/__init__.py`.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

_repositorio = importlib.import_module(
    "src.domains.ai-governance.knowledge.governance_repository"
)
GovernanceRepository = _repositorio.GovernanceRepository

# A knowledge-base veio junto com o domínio no fan-out.
KB_PATH = Path(__file__).resolve().parents[3] / "src" / "domains" / "ai-governance" / "knowledge-base"


@pytest.fixture(scope="session")
def repo() -> GovernanceRepository:
    return GovernanceRepository(kb_path=KB_PATH)
