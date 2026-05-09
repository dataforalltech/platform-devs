from __future__ import annotations

import pytest

from src.config.settings import QASettings
from src.db.store import QAStore


@pytest.fixture
def store():
    s = QAStore(db_path=":memory:")
    yield s
    s.close()


@pytest.fixture
def settings():
    return QASettings(
        db_path=":memory:",
        screenshots_dir="/tmp/qa-test-screenshots",
        baselines_dir="/tmp/qa-test-baselines",
        http_timeout=5.0,
        subprocess_timeout=30,
    )
