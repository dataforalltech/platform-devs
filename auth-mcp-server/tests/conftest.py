"""Path wiring p/ os testes do AS: auth-mcp-server/ (import authorization_server)
e a raiz do repo (import shared.*)."""
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_AS = os.path.dirname(_HERE)            # auth-mcp-server/
_ROOT = os.path.dirname(_AS)            # raiz do repo (p/ `shared`)
for _p in (_AS, _ROOT):
    if _p not in sys.path:
        sys.path.insert(0, _p)
