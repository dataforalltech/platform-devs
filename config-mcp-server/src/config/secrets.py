"""Resolução de segredos pelo bootstrap do STD-SEC-004.

Em ``cloud`` a fonte é o Vault e **só** o Vault: qualquer falha de auth/fetch
levanta ``SecretResolutionError`` e o serviço não sobe — "a ausência ou invalidez
de uma credencial exigida MUST falhar fechada" (STD-SEC-002, §MUST). O valor de
env/.env é deliberadamente ignorado em cloud, senão o bootstrap degrada em
silêncio para uma fonte que o standard não admite ali.

Em ``local`` o Vault é opcional — só é consultado quando ``VAULT_ADDR`` está
setado — e qualquer falha degrada para env, que é o "fallback local controlado"
que o STD-SEC-004 permite.

Apenas a FONTE efetiva é logada — nunca o valor do segredo (STD-OBS-001).
"""

from __future__ import annotations

import logging
import os

_log = logging.getLogger(__name__)

# Espaço de segredos deste serviço no Vault (path dataforall/<SERVICE>/<name>).
# Duplicado do NAMESPACE de settings.py de propósito: settings.py importa este
# módulo, então importar de lá seria circular.
SERVICE = "config-mcp"


class SecretResolutionError(RuntimeError):
    """Segredo obrigatório não pôde ser resolvido pela fonte aprovada."""


def load_secret(
    env_var: str,
    env_value: str = "",
    *,
    vault_key: str | None = None,
    runtime_env: str = "local",
    required: bool = False,
) -> str:
    """Resolve um segredo pelo bootstrap aprovado.

    ``env_var`` nomeia a variável (usado no log e como chave default no Vault);
    ``env_value`` é o valor já resolvido do ambiente pelo caller. ``required``
    decide o que fazer com valor AUSENTE; falha de comunicação em cloud levanta
    independentemente dele.
    """
    is_cloud = runtime_env == "cloud"
    key = vault_key or env_var
    if not is_cloud and not os.getenv("VAULT_ADDR"):
        if required and not env_value:
            raise SecretResolutionError(
                f"segredo obrigatório '{key}' ausente no runtime local"
            )
        return env_value

    try:
        from platform_crypto import VaultSecretsClient  # import lazy (opt-in de cloud)

        # `service` é o espaço de segredos do serviço; `name` é a chave lógica
        # dentro dele. Construir o cliente sem `service` — como fazia a versão
        # anterior — nem sequer satisfaz a assinatura da lib.
        value = VaultSecretsClient(service=SERVICE).get(key)
    except Exception as exc:  # noqa: BLE001 — fronteira de bootstrap, mensagem sanitizada
        if is_cloud:
            raise SecretResolutionError(
                f"segredo obrigatório '{key}' não pôde ser resolvido do Vault "
                f"({type(exc).__name__})"
            ) from exc
        _log.warning(
            "secret_vault_unavailable key=%s detail=%s — fallback env",
            env_var,
            type(exc).__name__,
        )
        if required and not env_value:
            raise SecretResolutionError(
                f"segredo obrigatório '{key}' indisponível"
            ) from exc
        return env_value

    if value:
        _log.info("secret_resolved source=vault key=%s service=%s", env_var, SERVICE)
        return value
    if is_cloud:
        if required:
            raise SecretResolutionError(f"segredo obrigatório '{key}' vazio no Vault")
        _log.warning("secret_vault_empty key=%s — source=absent", env_var)
        return ""
    _log.warning("secret_vault_empty key=%s — fallback env", env_var)
    if required and not env_value:
        raise SecretResolutionError(f"segredo obrigatório '{key}' ausente")
    if env_value:
        _log.info("secret_resolved source=env key=%s", env_var)
    return env_value
