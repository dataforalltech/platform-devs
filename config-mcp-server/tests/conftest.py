"""Fixtures para testes do config-mcp-server."""
from __future__ import annotations

import pytest

from src.knowledge.encryptor import Encryptor
from src.knowledge.store import ConfigStore


@pytest.fixture()
def encryptor() -> Encryptor:
    from cryptography.fernet import Fernet
    return Encryptor(Fernet.generate_key().decode())


@pytest.fixture()
def store(tmp_path, encryptor) -> ConfigStore:
    return ConfigStore(str(tmp_path / "test_config.enc.json"), encryptor)
