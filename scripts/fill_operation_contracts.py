#!/usr/bin/env python3
"""Preenche o contrato das Operations do platform-catalog a partir do CÓDIGO.

Problema que resolve: as 307 Operations do catálogo tinham `contract.inputs: {}`,
`contract.outputs: {}` e, em 288 delas, `metadata.description: ''` — e ainda assim
`lifecycle: stable`. A camada Operation-first que agentes e runbooks consultam para
ESCOLHER uma capacidade só carregava o id. Um agente que escolhesse
`development.generate_fastapi_router` não tinha como saber, pelo catálogo, que a
tool devolve um esqueleto com `raise NotImplementedError`.

DUAS FONTES DE VERDADE, nesta ordem de precedência:

  1. `contracts/tools/*.yaml` — os contratos canônicos dos provedores governados.
     Trazem `input_schema` E `output_schema`, então é a única fonte que preenche a
     saída. É também a única que cobre os 3 provedores fora do agregador
     (project-product, contracts, artifact-provenance) — ignorá-los faria este
     script aposentar justamente as 19 tools que funcionam.
  2. `_TOOL_SCHEMAS` do agregador `devteam-mcp` — descrição e schema de entrada
     declarados no próprio código dos 21 domínios.

O que ele NÃO faz, e por quê:
  * não inventa `contract.outputs` para quem não tem contrato canônico. Nenhum
    servidor de persona declara output schema (19 de 946 tools da frota declaram).
    Preencher com um palpite seria a mesma classe de afirmação sem evidência que
    este catálogo já tinha demais.
  * não toca em `spec.provider_id` das Tools. Reapontar os bindings para o runtime
    real depende de uma decisão de modelo ainda pendente (provider por domínio ou
    provider único).
  * não aposenta Operation cujo nome de tool seja AMBÍGUO entre domínios (`status`,
    por exemplo). Escolher um domínio ali seria inventar o binding.

Uso:
    python scripts/fill_operation_contracts.py            # grava
    python scripts/fill_operation_contracts.py --check    # não grava
    python scripts/fill_operation_contracts.py --report   # detalha o que não casou
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
AGREGADOR = ROOT / "devteam-mcp-server"
CATALOGO = ROOT / "platform-catalog"
OPERATIONS = CATALOGO / "catalog" / "operations"
INVENTARIO = CATALOGO / "seed" / "tool_inventory.json"
CONTRATOS = ROOT / "contracts" / "tools"


def _contratos_canonicos() -> dict[str, dict[str, Any]]:
    """`nome_da_tool` -> contrato canônico (com input E output schema)."""
    achados: dict[str, dict[str, Any]] = {}
    for caminho in sorted(CONTRATOS.glob("*.yaml")):
        documento = yaml.safe_load(caminho.read_text(encoding="utf-8")) or {}
        nome = documento.get("name")
        if nome:
            achados[nome] = documento
    return achados


def _tool_schemas_agregador() -> dict[str, dict[str, Any]]:
    anterior = Path.cwd()
    sys.path.insert(0, str(AGREGADOR))
    os.chdir(AGREGADOR)
    # O agregador recusa o boot sem esta chave; aqui só se lê o registro estático.
    os.environ.setdefault("MCP_CONTEXT_SIGNING_KEY", "leitura-estatica")
    try:
        from src.server import mcp_server  # noqa: PLC0415

        return dict(mcp_server._TOOL_SCHEMAS)
    finally:
        os.chdir(anterior)
        sys.path.remove(str(AGREGADOR))


def _dominios_por_server() -> dict[str, str]:
    sys.path.insert(0, str(CATALOGO))
    try:
        from platform_catalog.derive import SERVER_DOMAIN  # noqa: PLC0415

        return dict(SERVER_DOMAIN)
    finally:
        sys.path.remove(str(CATALOGO))


class Resolucao:
    """O que se conseguiu apurar sobre a tool que implementa uma Operation."""

    def __init__(self, descricao: str = "", inputs: dict | None = None,
                 outputs: dict | None = None, estado: str = "ausente") -> None:
        self.descricao = descricao
        self.inputs = inputs or {}
        self.outputs = outputs or {}
        self.estado = estado  # "canonico" | "agregador" | "ambiguo" | "ausente"


def _resolver(nome_tool: str, server: str, canonicos: dict, schemas: dict) -> Resolucao:
    contrato = canonicos.get(nome_tool)
    if contrato:
        return Resolucao(
            descricao=(contrato.get("description") or "").strip(),
            inputs=contrato.get("input_schema") or {},
            outputs=contrato.get("output_schema") or {},
            estado="canonico",
        )

    direto = f"{server.removesuffix('-mcp-server')}_{nome_tool}"
    meta = schemas.get(direto)
    if meta is None:
        # A consolidação moveu tools entre domínios (várias do product-owner foram
        # para o product-manager). Sufixo único ainda identifica a tool.
        candidatos = [k for k in schemas if k.split("_", 1)[-1] == nome_tool]
        if len(candidatos) > 1:
            return Resolucao(estado="ambiguo")
        if len(candidatos) == 1:
            meta = schemas[candidatos[0]]

    if meta is None:
        return Resolucao(estado="ausente")
    return Resolucao(
        descricao=(meta.get("description") or "").strip(),
        inputs=meta.get("schema") or {},
        estado="agregador",
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="não grava")
    parser.add_argument("--report", action="store_true", help="lista o que não casou")
    args = parser.parse_args()

    canonicos = _contratos_canonicos()
    schemas = _tool_schemas_agregador()
    dominios = _dominios_por_server()
    inventario = json.loads(INVENTARIO.read_text(encoding="utf-8"))["tools"]

    # Operation -> resolução da PRIMEIRA tool que a implementa (o gerador do seed
    # também deixa a 1ª ocorrência definir o contrato).
    por_operacao: dict[str, Resolucao] = {}
    for linha in inventario:
        server, tool = linha["server"], linha["tool"]
        op_id = f"{dominios.get(server, 'platform')}.{tool}"
        if op_id not in por_operacao:
            por_operacao[op_id] = _resolver(tool, server, canonicos, schemas)

    contagem = {"canonico": 0, "agregador": 0, "ambiguo": 0, "ausente": 0, "sem_inventario": 0}
    aposentadas: list[str] = []
    ambiguas: list[str] = []
    sem_inventario: list[str] = []
    alterados = 0

    for caminho in sorted(OPERATIONS.glob("*.yaml")):
        documento = yaml.safe_load(caminho.read_text(encoding="utf-8"))
        metadata = documento.setdefault("metadata", {})
        op_id = metadata.get("uid")
        if not op_id:
            continue

        antes = yaml.safe_dump(documento, sort_keys=False, allow_unicode=True)

        resolucao = por_operacao.get(op_id)
        fora_do_inventario = resolucao is None
        if fora_do_inventario:
            # A Operation existe em disco mas o inventário do seed (2026-07-06) não
            # a conhece — é o caso dos 3 provedores governados, promovidos depois.
            # O nome da tool está no próprio uid (`<domínio>.<tool>`), então dá para
            # resolver contra os contratos canônicos sem passar pelo inventário.
            resolucao = _resolver(op_id.split(".", 1)[-1], "", canonicos, schemas)

        if resolucao.estado in {"canonico", "agregador"}:
            contagem[resolucao.estado] += 1
            if resolucao.descricao:
                metadata["description"] = resolucao.descricao
            contrato = documento.setdefault("spec", {}).setdefault("contract", {})
            if resolucao.inputs:
                contrato["inputs"] = resolucao.inputs
            if resolucao.outputs:
                contrato["outputs"] = resolucao.outputs
        elif resolucao.estado == "ambiguo":
            # Não se aposenta nem se preenche: o nome existe em vários domínios e
            # escolher um seria inventar o binding.
            contagem["ambiguo"] += 1
            ambiguas.append(op_id)
        elif fora_do_inventario:
            # Nem o inventário conhece, nem há tool com esse nome. Reportar sem
            # aposentar: a ausência pode ser do inventário, não da capacidade.
            contagem["sem_inventario"] += 1
            sem_inventario.append(op_id)
        else:
            contagem["ausente"] += 1
            aposentadas.append(op_id)
            metadata["lifecycle"] = "retired"
            if not (metadata.get("description") or "").strip():
                metadata["description"] = (
                    "Sem tool correspondente no runtime. Operation mantida como "
                    "registro histórico."
                )

        depois = yaml.safe_dump(documento, sort_keys=False, allow_unicode=True)
        if antes != depois:
            alterados += 1
            if not args.check:
                caminho.write_text(depois, encoding="utf-8", newline="\n")

    total = len(list(OPERATIONS.glob("*.yaml")))
    print(f"Operations em disco: {total}")
    print(f"  contrato canônico (inputs + outputs): {contagem['canonico']}")
    print(f"  do código do agregador (só inputs):   {contagem['agregador']}")
    print(f"  ambíguas — intocadas:                 {contagem['ambiguo']}")
    print(f"  sem implementação — aposentadas:      {contagem['ausente']}")
    if contagem["sem_inventario"]:
        print(f"  fora do inventário do seed:           {contagem['sem_inventario']}")
    print(f"  arquivos alterados: {alterados}")

    if args.report:
        if aposentadas:
            print("\n=== Sem implementação no runtime (lifecycle: retired) ===")
            for op in sorted(aposentadas):
                print(f"  {op}")
        if ambiguas:
            print("\n=== Ambíguas — mesmo nome de tool em vários domínios ===")
            for op in sorted(ambiguas):
                print(f"  {op}")
        if sem_inventario:
            print("\n=== Em disco, mas fora do inventário do seed ===")
            for op in sorted(sem_inventario):
                print(f"  {op}")

    if args.check:
        print("\n(--check: nada foi gravado)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
