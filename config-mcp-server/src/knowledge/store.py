"""ConfigStore — armazenamento hierárquico encriptado de credenciais e configurações.

Estrutura do JSON armazenado (valores são encriptados individualmente):
{
    "credentials.acr": {
        "ACR_USERNAME": "<fernet_token>",
        "ACR_PASSWORD": "<fernet_token>"
    },
    "credentials.github": {
        "GITHUB_TOKEN": "<fernet_token>"
    },
    "env.dev": {
        "DATABASE_URL": "<fernet_token>"
    },
    "tenants.tenant_abc": {
        "DATABASE_URL": "<fernet_token>"
    }
}

Namespaces convencionais:
  credentials.<service>  — credenciais de serviços externos (acr, github, portainer, etc.)
  env.<environment>      — variáveis de ambiente por perfil (dev, staging, production)
  tenants.<tenant_id>    — variáveis de ambiente por tenant
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from .encryptor import Encryptor, EncryptionError

_log = logging.getLogger(__name__)


class StoreError(RuntimeError):
    """Erro de operação no ConfigStore."""


class ConfigStore:
    """Store encriptado baseado em arquivo JSON."""

    def __init__(self, store_path: str, encryptor: Encryptor) -> None:
        self._path = Path(store_path).expanduser().resolve()
        self._enc = encryptor
        self._data: dict[str, dict[str, str]] = {}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._load()

        # Initialize PostgreSQL sync layer
        self._postgres_sync = None
        if os.getenv("POSTGRES_SYNC_ENABLED", "false").lower() == "true":
            try:
                from db.postgres_sync import ConfigPostgresSync
                postgres_config = {
                    "host": os.getenv("POSTGRES_HOST", "claude-dev"),
                    "port": int(os.getenv("POSTGRES_PORT", "5432")),
                    "user": os.getenv("POSTGRES_USER", "postgres"),
                    "password": os.getenv("POSTGRES_PASSWORD", "postgres_password_local_dev"),
                    "database": os.getenv("POSTGRES_DB", "app"),
                }
                self._postgres_sync = ConfigPostgresSync(postgres_config, enabled=True)
                _log.info("✅ ConfigStore: PostgreSQL sync enabled")
            except Exception as e:
                _log.warning(f"⚠️  ConfigStore: PostgreSQL sync disabled: {e}")

    # ── I/O ───────────────────────────────────────────────────────────────── #

    def _load(self) -> None:
        if self._path.exists():
            try:
                with open(self._path, encoding="utf-8") as f:
                    self._data = json.load(f)
                _log.info("config_store_loaded path=%s namespaces=%d", self._path, len(self._data))
            except (json.JSONDecodeError, OSError) as exc:
                raise StoreError(f"Erro ao carregar store '{self._path}': {exc}") from exc
        else:
            _log.info("config_store_new path=%s", self._path)

    def _save(self) -> None:
        try:
            with open(self._path, "w", encoding="utf-8") as f:
                json.dump(self._data, f, indent=2, ensure_ascii=False)
        except OSError as exc:
            raise StoreError(f"Erro ao salvar store '{self._path}': {exc}") from exc

    # ── CRUD ──────────────────────────────────────────────────────────────── #

    def get(self, namespace: str, key: str) -> str | None:
        """Retorna o valor decriptado ou None se não existir."""
        token = self._data.get(namespace, {}).get(key)
        if token is None:
            return None
        try:
            return self._enc.decrypt(token)
        except EncryptionError as exc:
            raise StoreError(f"Erro ao decriptar {namespace}.{key}: {exc}") from exc

    def set(self, namespace: str, key: str, value: str) -> None:
        """Armazena um valor encriptado."""
        if namespace not in self._data:
            self._data[namespace] = {}
        self._data[namespace][key] = self._enc.encrypt(value)
        self._save()
        _log.info("config_store_set ns=%s key=%s", namespace, key)

        # Sync to PostgreSQL (metadata only, encrypted value stays in file)
        if self._postgres_sync:
            try:
                self._postgres_sync.sync_credential_created(namespace, key)
            except Exception as e:
                _log.warning(f"Failed to sync credential to PostgreSQL: {e}")

    def delete(self, namespace: str, key: str) -> bool:
        """Remove uma chave. Retorna True se existia."""
        if namespace in self._data and key in self._data[namespace]:
            del self._data[namespace][key]
            if not self._data[namespace]:
                del self._data[namespace]
            self._save()
            _log.info("config_store_deleted ns=%s key=%s", namespace, key)

            # Sync to PostgreSQL
            if self._postgres_sync:
                try:
                    self._postgres_sync.sync_credential_deleted(namespace, key)
                except Exception as e:
                    _log.warning(f"Failed to sync credential deletion to PostgreSQL: {e}")

            return True
        return False

    def delete_namespace(self, namespace: str) -> bool:
        """Remove um namespace inteiro. Retorna True se existia."""
        if namespace in self._data:
            del self._data[namespace]
            self._save()
            _log.info("config_store_ns_deleted ns=%s", namespace)
            return True
        return False

    # ── Leitura em lote ───────────────────────────────────────────────────── #

    def get_namespace(self, namespace: str) -> dict[str, str]:
        """Retorna todos os pares key→value decriptados de um namespace."""
        result: dict[str, str] = {}
        for key, token in self._data.get(namespace, {}).items():
            try:
                result[key] = self._enc.decrypt(token)
            except EncryptionError:
                result[key] = "<decrypt_error>"
        return result

    def list_keys(self, namespace: str | None = None) -> dict[str, list[str]]:
        """Lista chaves (nunca valores). namespace=None → todos os namespaces."""
        if namespace:
            return {namespace: sorted(self._data.get(namespace, {}).keys())}
        return {ns: sorted(keys.keys()) for ns, keys in sorted(self._data.items())}

    def list_namespaces(self) -> list[str]:
        return sorted(self._data.keys())

    def namespace_exists(self, namespace: str) -> bool:
        return namespace in self._data
