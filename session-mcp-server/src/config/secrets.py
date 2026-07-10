"""Resolução de segredos com fallback gracioso (STD-SEC-004).

``load_secret`` tenta o **Vault** (``platform_crypto.VaultSecretsClient``) SOMENTE
quando ``VAULT_ADDR`` está setado, com import LAZY dentro de ``try/except``. Em
qualquer falha (lib ausente, Vault indisponível, chave inexistente) degrada
graciosamente para a variável de ambiente / default — o boot NUNCA quebra por
causa do Vault. A fonte efetiva do segredo é logada (sem o valor).
"""

from __future__ import annotations

import logging
import os

_log = logging.getLogger(__name__)


def load_secret(key: str, *, env_var: str, default: str = "") -> str:
    """Resolve um segredo: Vault (se ``VAULT_ADDR``) → env → default.

    - ``key``     : caminho lógico no Vault (ex.: ``session-mcp/pg_password``).
    - ``env_var`` : variável de ambiente usada como fallback (ex.: ``SESSION_PG_PASSWORD``).
    - ``default`` : valor final se nem Vault nem env resolverem.

    NUNCA loga o valor do segredo — apenas a fonte efetiva.
    """
    if os.getenv("VAULT_ADDR"):
        try:
            from platform_crypto import VaultSecretsClient  # import lazy (opcional)

            value = VaultSecretsClient().get_secret(key)
            if value:
                _log.info("secret_loaded key=%s source=vault", key)
                return value
        except Exception as exc:  # noqa: BLE001 — degradação graciosa: nunca quebra o boot
            _log.warning("secret_vault_unavailable key=%s falling_back_to_env detail=%s", key, exc)

    env_value = os.getenv(env_var)
    if env_value:
        _log.info("secret_loaded key=%s source=env", key)
        return env_value

    _log.info("secret_loaded key=%s source=default", key)
    return default
