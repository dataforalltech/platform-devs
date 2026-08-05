# Portado de `config-mcp-server/tests/test_encryptor.py` pelo fan-out de testes.
#
# O código de tool do agregador é byte-a-byte o do servidor legado; só o caminho
# de import muda. Gerado por `scripts/port_domain_tests.py` — reexecutar é
# idempotente. Editar aqui diverge da origem: corrija no legado e reexecute, ou
# aposente o legado (ver ROADMAP, fechar o strangler).

"""Testes do Encryptor (Fernet)."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from src.domains.config.knowledge.encryptor import EncryptionError, Encryptor


class TestEncryptor:
    def test_roundtrip(self):
        enc = Encryptor(Fernet.generate_key().decode())
        token = enc.encrypt("hello world")
        assert token != "hello world"
        assert enc.decrypt(token) == "hello world"

    def test_accepts_bytes_key(self):
        key = Fernet.generate_key()  # bytes
        enc = Encryptor(key.decode())
        assert enc.decrypt(enc.encrypt("x")) == "x"

    def test_invalid_key_raises_encryption_error(self):
        with pytest.raises(EncryptionError):
            Encryptor("not-a-valid-fernet-key")

    def test_decrypt_invalid_token_raises(self):
        enc = Encryptor(Fernet.generate_key().decode())
        with pytest.raises(EncryptionError):
            enc.decrypt("garbage-token")

    def test_decrypt_with_wrong_key_raises(self):
        enc1 = Encryptor(Fernet.generate_key().decode())
        enc2 = Encryptor(Fernet.generate_key().decode())
        token = enc1.encrypt("secret")
        with pytest.raises(EncryptionError):
            enc2.decrypt(token)

    def test_generate_key_is_usable(self):
        key = Encryptor.generate_key()
        assert isinstance(key, str)
        enc = Encryptor(key)
        assert enc.decrypt(enc.encrypt("ok")) == "ok"

    def test_unicode_value(self):
        enc = Encryptor(Fernet.generate_key().decode())
        value = "配置ção-áéí-🔐"
        assert enc.decrypt(enc.encrypt(value)) == value
