#!/usr/bin/env python3
"""Regrava `platform-catalog/catalog/index.json` a partir dos YAMLs EM DISCO.

Por que não usar `platform_catalog.generate_seed`: o `main()` dele apaga e
reescreve operations/, tools/ e providers/ inteiros a partir do inventário de
origem. Isso é o certo para semear o catálogo do zero, e é demais para corrigir
uma contagem — qualquer edição feita nos YAMLs desde a semeadura seria perdida.

Este script não escreve nada além do índice. Ele apenas conta o que existe e
deriva a portabilidade pelo mesmo critério do gerador: uma Operation é portável
quando mais de uma Tool declara `spec.operation_id` apontando para ela.

Uso:
    python scripts/reindex_platform_catalog.py            # regrava o índice
    python scripts/reindex_platform_catalog.py --check    # só reporta a divergência
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "platform-catalog" / "catalog"
API_VERSION = "catalog.platform.dev/v1"


def _contar(sub: str) -> list[Path]:
    diretorio = CATALOG / sub
    return sorted(diretorio.glob("*.yaml")) if diretorio.is_dir() else []


def construir_indice() -> dict:
    operations = _contar("operations")
    tools = _contar("tools")
    providers = _contar("providers")

    # Portabilidade: quantas Tools implementam cada Operation. Mesmo critério do
    # generate_seed (bindings_per_op), mas lido do disco.
    por_operacao: Counter[str] = Counter()
    for caminho in tools:
        try:
            documento = yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}
        except yaml.YAMLError as exc:
            raise SystemExit(f"YAML inválido em {caminho}: {exc}") from exc
        operation_id = (documento.get("spec") or {}).get("operation_id")
        if operation_id:
            por_operacao[operation_id] += 1

    portaveis = {op: n for op, n in sorted(por_operacao.items()) if n > 1}

    return {
        "apiVersion": API_VERSION,
        "counts": {
            "operations": len(operations),
            "tools": len(tools),
            "providers": len(providers),
        },
        "portability": {
            "operations_with_multiple_tools": len(portaveis),
            "examples": portaveis,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--check",
        action="store_true",
        help="não escreve; sai com 1 se o índice versionado divergir do disco",
    )
    args = parser.parse_args()

    destino = CATALOG / "index.json"
    novo = construir_indice()
    atual = json.loads(destino.read_text(encoding="utf-8")) if destino.is_file() else None

    if atual == novo:
        print("OK: index.json corresponde ao catálogo em disco")
        return 0

    if args.check:
        antes = (atual or {}).get("counts", {})
        print("ERRO: index.json diverge do catálogo em disco")
        print(f"  índice: {antes}")
        print(f"  disco:  {novo['counts']}")
        return 1

    destino.write_text(json.dumps(novo, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"WROTE: {destino.relative_to(ROOT)} -> {novo['counts']}")
    print(f"  portabilidade: {novo['portability']['operations_with_multiple_tools']} operations com >1 tool")
    return 0


if __name__ == "__main__":
    sys.exit(main())
