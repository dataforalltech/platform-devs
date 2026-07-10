"""Fixtures + sys.path shim para os testes do config-mcp-server.

Garante que a raiz do config-mcp-server esteja no sys.path (permite `from src...`
mesmo quando o pytest é invocado de outro cwd, sem depender de `pip install -e .`).
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import pytest  # noqa: E402

from src.knowledge.encryptor import Encryptor  # noqa: E402
from src.knowledge.store import ConfigStore  # noqa: E402


@pytest.fixture()
def encryptor() -> Encryptor:
    from cryptography.fernet import Fernet

    return Encryptor(Fernet.generate_key().decode())


@pytest.fixture()
def store(tmp_path, encryptor) -> ConfigStore:
    return ConfigStore(str(tmp_path / "test_config.enc.json"), encryptor)
