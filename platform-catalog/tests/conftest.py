import sys
from pathlib import Path

# garante que o pacote platform_catalog seja importável ao rodar pytest da raiz do subprojeto
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
