"""Resolução de segredos com Vault-fallback (STD-SEC-004).

Segredos deste server (todos resolvidos por esta função): as senhas de banco
(``<ns>/db_password`` e ``<ns>/admin_db_password`` — o allocator persiste no ORM
canônico, dual-db, então há credencial de DB de verdade) e o ``INFRA_LEASE_SECRET``
(Fernet key que cifra as chaves SSH privadas por VM).

Padrão de resolução (STD-SEC-002 §MUST — falha fechada):
  1. Em ``cloud`` a fonte é o Vault e SÓ o Vault: qualquer falha de auth/fetch
     levanta ``SecretResolutionError`` e o serviço não sobe. O valor de env é
     deliberadamente ignorado ali — degradar em silêncio para uma fonte que o
     standard não admite é o modo de falha que esta função existe para impedir.
  2. Em ``local`` o Vault é opcional (só é consultado quando ``VAULT_ADDR`` está
     setado) e qualquer falha degrada para env — o "fallback local controlado"
     que o STD-SEC-004 permite.
  3. A FONTE efetiva é logada (vault | env | absent) — o VALOR nunca é logado.
"""

from __future__ import annotations

import logging
import os

_log = logging.getLogger(__name__)

# Espaço de segredos deste serviço no Vault (path dataforall/<SERVICE>/<name>).
# Duplicado do NAMESPACE de settings.py de propósito: settings.py importa este
# módulo, então importar de lá seria circular.
SERVICE = "infra-mcp"


class SecretResolutionError(RuntimeError):
    """Segredo obrigatório não pôde ser resolvido pela fonte aprovada."""


def load_secret(
    name: str,
    *,
    env_fallback: str | None = None,
    runtime_env: str = "local",
    required: bool = False,
) -> str | None:
    """Resolve um segredo por nome pelo bootstrap aprovado.

    Args:
        name: chave lógica do segredo (ex.: ``infra_lease_secret``).
        env_fallback: valor já resolvido do ambiente (Settings). Usado apenas no
            runtime local; em cloud é ignorado.
        runtime_env: ``local`` ou ``cloud``.
        required: decide o que fazer com valor AUSENTE. Falha de comunicação em
            cloud levanta independentemente dele.

    Returns:
        O segredo, ou ``env_fallback`` (que pode ser ``None``) quando indisponível
        e não obrigatório.

    Raises:
        SecretResolutionError: em cloud, se o Vault não responder; em qualquer
            ambiente, se ``required`` e nenhuma fonte tiver o valor.
    """
    is_cloud = runtime_env == "cloud"
    if not is_cloud and not os.environ.get("VAULT_ADDR"):
        if required and not env_fallback:
            raise SecretResolutionError(
                f"segredo obrigatório '{name}' ausente no runtime local"
            )
        _log.info(
            "secret_resolved",
            extra={"extras": {"name": name, "source": "env" if env_fallback else "absent"}},
        )
        return env_fallback

    try:
        from platform_crypto import VaultSecretsClient  # noqa: PLC0415 — import lazy/opcional

        # `service` é o espaço de segredos do serviço; `name` é a chave lógica
        # dentro dele. Construir o cliente sem `service` — como fazia a versão
        # anterior — nem sequer satisfaz a assinatura da lib.
        value = VaultSecretsClient(service=SERVICE).get(name)
    except Exception as exc:  # noqa: BLE001 — fronteira de bootstrap, mensagem sanitizada
        if is_cloud:
            raise SecretResolutionError(
                f"segredo obrigatório '{name}' não pôde ser resolvido do Vault "
                f"({type(exc).__name__})"
            ) from exc
        _log.warning(
            "secret_vault_unavailable",
            extra={"extras": {"name": name, "source": "env", "reason": type(exc).__name__}},
        )
        if required and not env_fallback:
            raise SecretResolutionError(
                f"segredo obrigatório '{name}' indisponível"
            ) from exc
        return env_fallback

    if value:
        _log.info(
            "secret_resolved",
            extra={"extras": {"name": name, "source": "vault", "service": SERVICE}},
        )
        return value
    if is_cloud:
        if required:
            raise SecretResolutionError(f"segredo obrigatório '{name}' vazio no Vault")
        _log.warning("secret_vault_empty", extra={"extras": {"name": name, "source": "absent"}})
        return None
    if required and not env_fallback:
        raise SecretResolutionError(f"segredo obrigatório '{name}' ausente")
    _log.info(
        "secret_resolved",
        extra={"extras": {"name": name, "source": "env" if env_fallback else "absent"}},
    )
    return env_fallback
