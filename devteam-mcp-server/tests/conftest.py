"""Fixtures base da suíte do devteam-mcp (server AGREGADOR).

Este conftest só garante a raiz do server no ``sys.path`` (permite ``from src...`` de
qualquer cwd). O teste do agregador (`test_aggregator.py`) é de REGISTRO/roteamento e
NÃO toca banco: importa o agregador, monta ``_TOOL_SCHEMAS`` e exercita ``_dispatch``
com uma sessão/Store mockada — nenhuma conexão MySQL é aberta. Testes de integração
(MySQL real, credencial-zero) chegam no fan-out da Fase 2/3, por domínio.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Garante a raiz do server no sys.path (permite `from src...` de qualquer cwd).
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
