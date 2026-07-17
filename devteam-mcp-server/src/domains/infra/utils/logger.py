"""Acesso a loggers do stdlib.

A configuração do root handler (formato JSON estruturado, STD-OBS-001) vive em
``src/config/logging.py`` (``configure_logging``), chamada em ``build_server()``.
Aqui só expomos ``get_logger`` — um thin wrapper sobre ``logging.getLogger`` — para
que os módulos (db/server/utils) obtenham loggers nomeados que propagam para o root.
"""

from __future__ import annotations

import logging


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
