"""Vault-only cloud secret bootstrap with local env fallback."""

from __future__ import annotations

import logging
from functools import lru_cache

from pydantic import SecretStr

logger = logging.getLogger(__name__)


class SecretResolutionError(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _vault_client():
    from platform_crypto import VaultSecretsClient

    return VaultSecretsClient(service="platform-project-product")


def resolve_secret(
    name: str, *, runtime_env: str, local_value: SecretStr | None, required: bool = True
) -> SecretStr | None:
    if runtime_env not in {"local", "cloud"}:
        raise ValueError("RUNTIME_ENV must be local or cloud")
    if runtime_env == "local":
        value = local_value.get_secret_value() if local_value else ""
        if value:
            return SecretStr(value)
        if required:
            raise SecretResolutionError(f"required local secret {name!r} is missing")
        return None
    try:
        value = _vault_client().get(name, field="value")
    except Exception as exc:
        raise SecretResolutionError(
            f"required cloud secret {name!r} is unavailable ({type(exc).__name__})"
        ) from exc
    if not value:
        if required:
            raise SecretResolutionError(f"required cloud secret {name!r} is empty")
        return None
    logger.info("secret_resolved name=%s source=vault", name)
    return SecretStr(str(value))
