"""Encriptação Fernet para valores em repouso no ConfigStore."""
from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken


class EncryptionError(RuntimeError):
    """Erro de encriptação/decriptação."""


class Encryptor:
    """Wrapper sobre Fernet para encriptar/decriptar strings."""

    def __init__(self, key: str) -> None:
        try:
            self._fernet = Fernet(key.encode() if isinstance(key, str) else key)
        except (ValueError, Exception) as exc:
            raise EncryptionError(
                f"Chave Fernet inválida: {exc}. "
                "Gere uma com: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
            ) from exc

    def encrypt(self, value: str) -> str:
        """Encripta um valor string e retorna token base64."""
        return self._fernet.encrypt(value.encode()).decode()

    def decrypt(self, token: str) -> str:
        """Decripta um token base64 e retorna o valor original."""
        try:
            return self._fernet.decrypt(token.encode()).decode()
        except InvalidToken as exc:
            raise EncryptionError("Token inválido ou chave incorreta.") from exc

    @staticmethod
    def generate_key() -> str:
        """Gera uma nova chave Fernet aleatória."""
        return Fernet.generate_key().decode()
