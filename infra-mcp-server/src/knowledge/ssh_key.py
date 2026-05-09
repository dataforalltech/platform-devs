"""Geração e armazenamento criptografado de chaves SSH por VM (Phase 2f).

Fluxo por VM provisionada:
  1. `generate_keypair()` — gera par Ed25519 (privada + pública OpenSSH).
  2. Chave pública → injetada na VM via `TF_VAR_ssh_public_key` no terraform.
  3. Chave privada → cifrada com Fernet e armazenada em SQLite (`vm_keys`).
  4. `get_lease_ssh_key()` (tool MCP) → decifra e retorna ao agente via `decrypt_private_key()`.
  5. Chave é deletada quando a VM é terminada.

Algoritmo:
  - Geração: Ed25519 (curva rápida, chaves pequenas, resistente a clock-timing attacks).
  - Cifragem: Fernet = AES-128-CBC + HMAC-SHA256 (autenticado, padrão para dados em repouso).
  - Chave Fernet: fornecida via `INFRA_LEASE_SECRET` (URL-safe base64, 32 bytes).
    Se ausente, gerada aleatoriamente por sessão — chaves SSH perdidas em restart.
"""

from __future__ import annotations

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from cryptography.hazmat.primitives.serialization import (
    Encoding,
    NoEncryption,
    PrivateFormat,
    PublicFormat,
)


def generate_keypair() -> tuple[str, str]:
    """Gera par de chaves Ed25519.

    Returns:
        (private_key_pem, public_key_openssh) onde:
        - ``private_key_pem``: string PEM OpenSSH, entregue ao agente via
          ``get_lease_ssh_key``.
        - ``public_key_openssh``: linha OpenSSH (``ssh-ed25519 AAAA...``),
          injetada na VM como ``TF_VAR_ssh_public_key``.
    """
    private_key = Ed25519PrivateKey.generate()
    private_pem = private_key.private_bytes(
        Encoding.PEM,
        PrivateFormat.OpenSSH,
        NoEncryption(),
    ).decode()
    public_openssh = private_key.public_key().public_bytes(
        Encoding.OpenSSH,
        PublicFormat.OpenSSH,
    ).decode().strip()
    return private_pem, public_openssh


def generate_fernet_key() -> bytes:
    """Gera uma Fernet key aleatória (URL-safe base64, 32 bytes).

    Uso: configurar como ``INFRA_LEASE_SECRET`` para persistência entre restarts.
    """
    return Fernet.generate_key()


def encrypt_private_key(private_pem: str, fernet_key: bytes) -> bytes:
    """Cifra a chave privada PEM com Fernet (AES-128-CBC + HMAC-SHA256).

    Args:
        private_pem: Chave privada em formato PEM OpenSSH.
        fernet_key: URL-safe base64 de 32 bytes (output de ``generate_fernet_key``
                    ou do ``INFRA_LEASE_SECRET``).

    Returns:
        Token Fernet cifrado (bytes), seguro para armazenamento em SQLite.
    """
    return Fernet(fernet_key).encrypt(private_pem.encode())


def decrypt_private_key(encrypted: bytes, fernet_key: bytes) -> str:
    """Decifra e autentica a chave privada PEM.

    Raises:
        cryptography.fernet.InvalidToken: se ``fernet_key`` incorreto ou dado
            corrompido.
    """
    return Fernet(fernet_key).decrypt(encrypted).decode()
