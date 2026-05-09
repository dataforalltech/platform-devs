"""Fixtures compartilhadas: usa a knowledge-base real do repositório.

A base de conhecimento faz parte do produto — testar contra ela garante que
qualquer drift entre código e knowledge-base seja detectado.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.knowledge.governance_repository import GovernanceRepository

PROJECT_ROOT = Path(__file__).resolve().parents[1]
KB_PATH = PROJECT_ROOT / "knowledge-base"


@pytest.fixture(scope="session")
def repo() -> GovernanceRepository:
    return GovernanceRepository(kb_path=KB_PATH)
