"""Acesso a loggers nomeados.

A configuração do root logger (handler + formatter JSON estruturado, STD-OBS-001)
vive em ``src/config/logging.py`` e é instalada uma única vez em ``build_server``
via ``configure_logging(settings)``. Este módulo expõe apenas o atalho
``get_logger`` usado pelos demais módulos (que só obtêm loggers nomeados; nunca
configuram handlers). Logs vão para stderr — stdout é o canal MCP via stdio.
"""

from __future__ import annotations

import logging


def get_logger(name: str) -> logging.Logger:
    """Atalho para obter logger nomeado."""
    return logging.getLogger(name)
