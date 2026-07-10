"""Fixtures compartilhadas + shim de sys.path.

Garante que a raiz do ai-governance-mcp-server esteja no sys.path (permite
`from src...` mesmo quando o pytest é invocado de outro cwd, sem depender de
`pip install -e .`).

A base de conhecimento faz parte do produto — testar contra ela garante que
qualquer drift entre código e knowledge-base seja detectado.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from src.knowledge.governance_repository import GovernanceRepository  # noqa: E402

PROJECT_ROOT = _ROOT
KB_PATH = PROJECT_ROOT / "knowledge-base"


@pytest.fixture(scope="session")
def repo() -> GovernanceRepository:
    return GovernanceRepository(kb_path=KB_PATH)
