"""Validadores de input das tools MCP."""

from __future__ import annotations

from pathlib import Path


def require_non_empty_string(value: object | None, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} é obrigatório e deve ser uma string não-vazia")
    return value.strip()


def normalize_path(value: object | None, field_name: str = "path") -> Path:
    """Aceita string ou None; resolve com expanduser. Falha se vazio."""
    raw = require_non_empty_string(value, field_name)
    return Path(raw).expanduser().resolve()
