"""Garante que a raiz do security-mcp-server esteja no sys.path.

Permite `from src.tools...` mesmo quando o pytest é invocado de outro cwd,
sem depender de `pip install -e .` (embora este também funcione).
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
