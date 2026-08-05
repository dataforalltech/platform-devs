"""Resolução de segredos pelo bootstrap do STD-SEC-004.

`load_secret` resolve um segredo (ex.: a credencial/DSN do PostgreSQL) pela fonte
aprovada para o ambiente. Em ``cloud`` a fonte é o Vault e SÓ o Vault: qualquer
falha de auth/fetch levanta ``SecretResolutionError`` e o serviço não sobe — "a
ausência ou invalidez de uma credencial exigida MUST falhar fechada"
(STD-SEC-002, §MUST). Em ``local`` o Vault é opcional e qualquer falha degrada
para env, o "fallback local controlado" que o STD-SEC-004 permite.

Contrato (STD-SEC-004):
  - Nenhuma senha/DSN com credencial é hard-coded no repositório.
  - Em cloud, credencial não resolvida recusa o boot AQUI, e não mais adiante:
    `enforce_security_invariants()` continua valendo como segunda barreira, mas
    não é a única.
  - A FONTE efetiva (vault|env|absent) é sempre logada (sem logar o valor).
"""

from __future__ import annotations

import logging
import os

_log = logging.getLogger(__name__)

# Espaço de segredos deste serviço no Vault (path dataforall/<SERVICE>/<name>).
# Duplicado do NAMESPACE de settings.py de propósito: settings.py importa este
# módulo, então importar de lá seria circular.
SERVICE = "qa-mcp"


class SecretResolutionError(RuntimeError):
    """Segredo obrigatório não pôde ser resolvido pela fonte aprovada."""


def load_secret(
    name: str,
    *,
    env_var: str,
    default: str = "",
    runtime_env: str = "local",
    required: bool = False,
) -> str:
    """Resolve o segredo ``name`` pelo bootstrap aprovado para ``runtime_env``.

    - Em cloud: Vault apenas. Falha de comunicação levanta sempre; valor vazio
      levanta quando ``required``.
    - Em local: Vault só é consultado se `VAULT_ADDR` estiver setado, e qualquer
      falha degrada para a env ``env_var`` (ou ``default``).
    - O valor NUNCA é logado; apenas a fonte e se veio preenchido.
    """
    is_cloud = runtime_env == "cloud"
    if not is_cloud and not os.getenv("VAULT_ADDR", "").strip():
        value = os.getenv(env_var, default)
        if required and not value:
            raise SecretResolutionError(
                f"segredo obrigatório '{name}' ausente no runtime local"
            )
        _log.info("secret_resolved name=%s source=env present=%s", name, bool(value))
        return value

    try:
        from platform_crypto import VaultSecretsClient  # import lazy (opcional)

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
            "secret_vault_unavailable name=%s falling_back_to_env detail=%s",
            name,
            type(exc).__name__,
        )
        value = os.getenv(env_var, default)
        if required and not value:
            raise SecretResolutionError(
                f"segredo obrigatório '{name}' indisponível"
            ) from exc
        _log.info("secret_resolved name=%s source=env present=%s", name, bool(value))
        return value

    if value:
        _log.info("secret_resolved name=%s source=vault service=%s", name, SERVICE)
        return value
    if is_cloud:
        if required:
            raise SecretResolutionError(f"segredo obrigatório '{name}' vazio no Vault")
        _log.warning("secret_empty_in_vault name=%s source=absent", name)
        return ""
    _log.warning("secret_empty_in_vault name=%s falling_back_to_env", name)
    value = os.getenv(env_var, default)
    if required and not value:
        raise SecretResolutionError(f"segredo obrigatório '{name}' ausente")
    _log.info("secret_resolved name=%s source=env present=%s", name, bool(value))
    return value
