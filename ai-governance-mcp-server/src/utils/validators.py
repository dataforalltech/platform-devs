"""Validadores de input das tools MCP.

As tools MCP recebem JSON livre — validamos aqui antes de prosseguir,
falhando com mensagem clara em vez de explodir mais à frente.
"""

from __future__ import annotations

VALID_LAYERS = {
    "frontend",
    "backend",
    "database",
    "integrations",
    "infrastructure",
    "security",
    "observability",
    "testing",
}

VALID_TASK_TYPES = {
    "feature",
    "bugfix",
    "refactor",
    "migration",
    "infra",
    "docs",
    "test",
    "chore",
}

VALID_CONTRACT_TYPES = {"api", "event", "database", "file", "schema"}


def safe_lower(value: object | None) -> str | None:
    """Lowercase strings, devolvendo None para não-strings/None."""
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped.lower() if stripped else None


def normalize_layer(value: object | None) -> str | None:
    """Normaliza nome de camada; aceita None. Levanta ValueError se inválido."""
    lowered = safe_lower(value)
    if lowered is None:
        return None
    if lowered not in VALID_LAYERS:
        raise ValueError(
            f"layer inválida: {value!r}. Opções: {sorted(VALID_LAYERS)}"
        )
    return lowered


def normalize_task_type(value: object | None) -> str | None:
    """Normaliza task_type; aceita None. Não falha em valor desconhecido — apenas devolve a string."""
    lowered = safe_lower(value)
    if lowered is None:
        return None
    return lowered


def normalize_contract_type(value: object | None) -> str:
    """Valida e normaliza contract_type. Obrigatório."""
    lowered = safe_lower(value)
    if lowered is None:
        raise ValueError("contract_type é obrigatório")
    if lowered not in VALID_CONTRACT_TYPES:
        raise ValueError(
            f"contract_type inválido: {value!r}. Opções: {sorted(VALID_CONTRACT_TYPES)}"
        )
    return lowered


def require_non_empty_string(value: object | None, field_name: str) -> str:
    """Garante que o campo é uma string não-vazia."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field_name} é obrigatório e deve ser uma string não-vazia")
    return value.strip()


def coerce_bool(value: object | None, default: bool = False) -> bool:
    """Aceita bool real, ou strings 'true'/'false'/'1'/'0'."""
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1", "yes", "y"}:
            return True
        if lowered in {"false", "0", "no", "n", ""}:
            return False
    return default


def coerce_string_list(value: object | None) -> list[str]:
    """Aceita list[str] ou string única; devolve sempre lista."""
    if value is None:
        return []
    if isinstance(value, str):
        stripped = value.strip()
        return [stripped] if stripped else []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            if isinstance(item, str) and item.strip():
                out.append(item.strip())
        return out
    return []
