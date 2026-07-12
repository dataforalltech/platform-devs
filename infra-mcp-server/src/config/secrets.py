"""Resolução de segredos com Vault-fallback (STD-SEC-004).

Segredos deste server (todos resolvidos por esta função): as senhas de banco
(``<ns>/db_password`` e ``<ns>/admin_db_password`` — o allocator persiste no ORM
canônico, dual-db, então há credencial de DB de verdade) e o ``INFRA_LEASE_SECRET``
(Fernet key que cifra as chaves SSH privadas por VM).

Padrão de resolução (fail-open p/ env, NUNCA quebra o boot):
  1. Se ``VAULT_ADDR`` estiver setado, tenta ``platform_crypto.VaultSecretsClient``
     (import LAZY dentro de try/except — a lib é opcional e pode não estar instalada).
  2. Qualquer falha de Vault (import, conexão, chave ausente) degrada graciosamente
     para o valor de ambiente já resolvido pelas Settings.
  3. A FONTE efetiva é logada (vault | env | absent) — o VALOR nunca é logado.
"""

from __future__ import annotations

import logging
import os

_log = logging.getLogger(__name__)


def load_secret(name: str, *, env_fallback: str | None = None) -> str | None:
    """Resolve um segredo por nome, preferindo Vault e degradando p/ env.

    Args:
        name: chave lógica do segredo (ex.: ``INFRA_LEASE_SECRET``).
        env_fallback: valor já resolvido do ambiente (Settings), usado se o Vault
            não estiver configurado/disponível ou não tiver a chave.

    Returns:
        O segredo, ou ``env_fallback`` (que pode ser ``None``) se indisponível.
        Nunca levanta — o boot não pode quebrar por causa do Vault.
    """
    if os.environ.get("VAULT_ADDR"):
        try:
            from platform_crypto import VaultSecretsClient  # noqa: PLC0415 — import lazy/opcional

            value = VaultSecretsClient().get_secret(name)
            if value:
                _log.info("secret_resolved", extra={"extras": {"name": name, "source": "vault"}})
                return value
        except Exception as exc:  # noqa: BLE001 — degrada p/ env; boot nunca quebra por Vault
            _log.warning(
                "secret_vault_unavailable",
                extra={"extras": {"name": name, "source": "env", "reason": type(exc).__name__}},
            )
    source = "env" if env_fallback else "absent"
    _log.info("secret_resolved", extra={"extras": {"name": name, "source": source}})
    return env_fallback
