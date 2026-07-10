"""Resolução de segredos com fallback gracioso — STD-SEC-004.

`load_secret` resolve um segredo (ex.: a senha do PostgreSQL) a partir do Vault
QUANDO `VAULT_ADDR` está setado, degradando graciosamente para variável de
ambiente caso contrário (ou em qualquer falha do Vault). O boot NUNCA quebra por
causa do Vault — o import de `platform_crypto` é LAZY (dentro de try/except) e a
indisponibilidade do Vault apenas loga e cai para env.

Contrato (STD-SEC-004):
  - Nenhuma senha/credencial é hard-coded no repositório.
  - Em cloud, a ausência do segredo é barrada por `enforce_security_invariants()`
    (fail-fast), não por um default silencioso aqui.
  - A FONTE efetiva (vault|env) é sempre logada (sem logar o valor).
"""

from __future__ import annotations

import logging
import os

_log = logging.getLogger(__name__)


def load_secret(name: str, *, env_var: str, default: str = "") -> str:
    """Resolve o segredo ``name`` via Vault (se `VAULT_ADDR`) → env `env_var` → default.

    - Vault só é consultado se `VAULT_ADDR` estiver setado; o import de
      `platform_crypto.VaultSecretsClient` é lazy e qualquer falha degrada para env.
    - O valor NUNCA é logado; apenas a fonte e se veio preenchido.
    """
    if os.getenv("VAULT_ADDR", "").strip():
        try:
            from platform_crypto import VaultSecretsClient  # import lazy (opcional)

            value = VaultSecretsClient().get_secret(name)
            if value:
                _log.info("secret_resolved name=%s source=vault", name)
                return value
            _log.warning("secret_empty_in_vault name=%s falling_back_to_env", name)
        except Exception as exc:  # noqa: BLE001 — Vault indisponível NUNCA derruba o boot
            _log.warning(
                "secret_vault_unavailable name=%s falling_back_to_env detail=%s",
                name,
                type(exc).__name__,
            )
    value = os.getenv(env_var, default)
    _log.info("secret_resolved name=%s source=env present=%s", name, bool(value))
    return value
