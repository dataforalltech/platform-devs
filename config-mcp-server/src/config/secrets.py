"""Resolução de segredos com fallback Vault → env (STD-SEC-004).

`load_secret` tenta o Vault (``platform_crypto.VaultSecretsClient``) SOMENTE quando
``VAULT_ADDR`` está setado, com import **lazy** e **degradação graciosa**: qualquer
falha (lib ausente, Vault indisponível, chave não encontrada) cai para o valor de
ambiente já resolvido pelo caller (o campo do Settings). O boot NUNCA quebra por
causa do Vault. Apenas a FONTE efetiva é logada — nunca o valor do segredo
(STD-SEC-004 / STD-OBS-001).
"""

from __future__ import annotations

import logging
import os

_log = logging.getLogger(__name__)


def load_secret(env_var: str, env_value: str = "", *, vault_key: str | None = None) -> str:
    """Resolve um segredo preferindo o Vault quando ``VAULT_ADDR`` está setado.

    Ordem: Vault (se ``VAULT_ADDR`` e a lib disponíveis) → ``env_value`` (já
    resolvido do env pelo caller, ex.: o campo do Settings). ``env_var`` é usado
    apenas para logar a fonte e como chave default no Vault. Retorna "" se nenhuma
    fonte tiver o valor (o caller decide se é fatal).
    """
    if not os.getenv("VAULT_ADDR"):
        return env_value

    key = vault_key or env_var
    try:
        from platform_crypto import VaultSecretsClient  # import lazy (opt-in de cloud)

        value = VaultSecretsClient().get_secret(key)
        if value:
            _log.info("secret_resolved source=vault key=%s", env_var)
            return value
        _log.warning("secret_vault_empty key=%s — fallback env", env_var)
    except Exception as exc:  # noqa: BLE001 — degradação graciosa: Vault nunca quebra o boot
        _log.warning("secret_vault_unavailable key=%s detail=%s — fallback env", env_var, type(exc).__name__)

    if env_value:
        _log.info("secret_resolved source=env key=%s", env_var)
    return env_value
