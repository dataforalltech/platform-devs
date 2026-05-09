"""Ferramenta de coleta de informações de hardware e sistema operacional."""
from __future__ import annotations

from typing import Any

from ..knowledge.sysinfo import collect_physical_info


def get_physical_info() -> dict[str, Any]:
    """Coleta e retorna informações do ambiente físico atual.

    Inclui: sistema operacional, CPU (cores, frequência, uso), RAM (total/disponível),
    discos (por partição), interfaces de rede com IPs.
    """
    try:
        info = collect_physical_info()
        return {"success": True, **info}
    except Exception as exc:  # noqa: BLE001
        return {"success": False, "error": str(exc)}
