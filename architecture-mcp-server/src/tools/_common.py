"""Helpers determinísticos compartilhados pelos *builders* de artefato.

Estes utilitários (slug, normalização de listas, casamento de heurísticas de
palavra-chave) são as peças puras preservadas das antigas tools `generate_*`: elas
continuam reais e determinísticas — a novidade é que o resultado é **persistido**
pelas tools de CRUD, não devolvido como template efêmero.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from typing import Any


def slug(text: str) -> str:
    """Gera um id estável (slug) a partir de um rótulo livre."""
    s = re.sub(r"[^a-zA-Z0-9]+", "_", (text or "").strip().lower()).strip("_")
    return s or "unnamed"


def as_str_list(value: Any) -> list[str]:
    """Normaliza um input que pode vir como str única, lista ou None em list[str]."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value.strip() else []
    if isinstance(value, (list, tuple, set)):
        return [str(v).strip() for v in value if str(v).strip()]
    return [str(value)]


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


def match_hints(text: str, hints: list[tuple[str, tuple[str, ...]]]) -> list[dict[str, Any]]:
    """Casa palavras-chave (transparente): cada match carrega ``triggered_by``."""
    lowered = text.lower()
    matched: list[dict[str, Any]] = []
    for label, keywords in hints:
        triggers = [kw for kw in keywords if kw in lowered]
        if triggers:
            matched.append({"name": label, "triggered_by": triggers})
    return matched


__all__ = ["slug", "as_str_list", "now_iso", "match_hints"]
