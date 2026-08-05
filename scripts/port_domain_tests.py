#!/usr/bin/env python3
"""Porta para o agregador os testes de TOOL dos servidores legados.

Contexto: o fan-out de 2026-07-17 copiou tools, models, checkers e db dos ~20
servidores byte-a-byte para `devteam-mcp-server/src/domains/`, mas **não migrou os
testes**. O resultado é 401 de 451 tools despachaveis sem teste — o bloqueio nº 1
da promoção do `devteam-mcp` de `experimental` para `active`.

Como o código é idêntico, os testes que exercitam APENAS a lógica de tool valem
sem alteração de conteúdo: muda só o prefixo de import
(`src.tools.x` → `src.domains.<domínio>.tools.x`).

CRITÉRIO DE PORTABILIDADE — deliberadamente estreito:
  * importa somente de `tools.`, `checkers.`, `models.`, `knowledge.` ou `db.schema`;
  * não toca banco (`requires_mysql`, `.conftest`, `aiomysql`, `get_pool_for_tenant`);
  * não é de settings/compliance — o agregador tem os seus, com invariantes próprios,
    e duplicá-los criaria duas fontes divergentes para a mesma regra;
  * não importa `server.` — a ponte HTTP do agregador é outra, com contrato próprio
    (ver tests/test_http_transport.py).

Os que ficam de fora NÃO são dívida escondida: os de banco dependem de MySQL real
(que este repositório não tem executor de CI para prover) e estão contados no
BACKLOG.

Uso:
    python scripts/port_domain_tests.py --dry-run          # só relata
    python scripts/port_domain_tests.py --domain architecture
    python scripts/port_domain_tests.py                    # todos
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AGREGADOR = ROOT / "devteam-mcp-server"
DOMINIOS_DIR = AGREGADOR / "src" / "domains"
DESTINO_BASE = AGREGADOR / "tests" / "domains"

# Domínios cuja cobertura já nasceu no agregador.
JA_COBERTOS = {"guardian", "session"}

# Domínios cujo código DIVERGIU do servidor legado além do `__init__.py`. Portar
# teste daqui faria o agregador ser cobrado pelo comportamento ANTIGO. Medido com
# comparação byte-a-byte de `src/` (excluindo config/ e server/, que são do
# esqueleto de cada servidor):
#   pipeline — db/store.py, tools/gate_tool.py, tools/pipeline_tool.py
#              (o ledger fail-closed de 2026-08-03 mudou o comportamento aqui)
# `deploy`, `session` e `infra` também divergem em alguns arquivos, mas os testes
# portados deles passam verde contra o agregador — a divergência não alcança o que
# esses testes exercitam. O portão final (`--prune-failing`) é quem decide.
DIVERGENTES = {"pipeline"}

# Arquivos que não devem ser sobrescritos pelo port: fixtures escritas à mão.
PRESERVAR = {"conftest.py", "__init__.py"}

RE_TESTE = re.compile(r"^\s*(?:async )?def (test_\w+)", re.M)
RE_IMPORT = re.compile(r"^from src\.([\w.]+) import", re.M)
PREFIXOS_OK = ("tools.", "checkers.", "models.", "knowledge.", "db.schema")
MARCAS_DE_BANCO = re.compile(r"requires_mysql|from \.conftest|aiomysql|get_pool_for_tenant")


RE_IMPORT_NOMES = re.compile(
    r"^from src\.([\w.]+) import\s+(?:\(([^)]*)\)|([^\n(]+))", re.M
)


def _simbolos_importados(texto: str) -> list[tuple[str, list[str]]]:
    """[(módulo, [nomes])] para cada `from src.<módulo> import ...`."""
    achados = []
    for modulo, entre_parens, em_linha in RE_IMPORT_NOMES.findall(texto):
        bruto = entre_parens or em_linha
        nomes = []
        for parte in bruto.replace("\n", " ").split(","):
            parte = parte.strip()
            if not parte:
                continue
            nomes.append(parte.split(" as ")[0].strip())
        achados.append((modulo, nomes))
    return achados


def _existe_no_agregador(dominio: str, modulo: str, nomes: list[str]) -> str:
    """'' se o módulo e todos os nomes existem no domínio; senão, o que falta.

    É o que impede portar um teste escrito contra uma versão do código que o
    agregador não tem. As duas cópias NÃO são idênticas em todos os domínios —
    deploy, pipeline, session e infra divergiram —, e um teste da versão antiga
    passaria a cobrar do agregador um comportamento que ele deliberadamente mudou.
    """
    import importlib

    caminho = f"src.domains.{dominio}.{modulo}"
    try:
        mod = importlib.import_module(caminho)
    except Exception as exc:  # noqa: BLE001 — qualquer falha desqualifica o port
        return f"módulo indisponível ({type(exc).__name__})"
    ausentes = [n for n in nomes if not hasattr(mod, n)]
    return f"símbolo ausente no agregador: {', '.join(ausentes)}" if ausentes else ""


def _portavel(caminho: Path, dominio: str) -> tuple[bool, str]:
    texto = caminho.read_text(encoding="utf-8", errors="ignore")
    if MARCAS_DE_BANCO.search(texto):
        return False, "depende de banco real"
    if "settings" in caminho.name or "compliance" in caminho.name:
        return False, "settings/compliance — o agregador tem o seu"
    modulos = RE_IMPORT.findall(texto)
    if not modulos:
        return False, "não importa nada de src/ — não exercita o domínio"
    fora = [m for m in modulos if not m.startswith(PREFIXOS_OK)]
    if fora:
        return False, f"importa fora do escopo de tool: {', '.join(sorted(set(fora)))}"
    for modulo, nomes in _simbolos_importados(texto):
        problema = _existe_no_agregador(dominio, modulo, nomes)
        if problema:
            return False, f"DIVERGÊNCIA — {problema}"
    return True, ""


def _reescreve(texto: str, dominio: str) -> str:
    """Reaponta os imports para o pacote do domínio dentro do agregador.

    Domínio SEM hífen: troca simples de prefixo, e o arquivo continua igual ao
    original a menos do caminho.

    Domínio COM hífen (`ai-governance`, `dev-twin`, `product-manager`,
    `product-owner`, `qa-engineer`): hífen não é identificador Python, então
    `from src.domains.dev-twin.x import y` é erro de sintaxe. Emitimos
    `importlib.import_module` com o caminho como STRING — que é exatamente como o
    próprio agregador carrega esses domínios (`src/domains/__init__.py`).

    A alternativa — registrar aliases com underscore em `sys.modules` — foi testada
    e descartada: quando o Python importa `a.b.c`, ele registra o submódulo sob o
    `__name__` REAL do pacote pai, então o alias teria de cobrir a subárvore
    inteira, e qualquer módulo que falhasse ao importar sumiria do alias em
    silêncio. Trocar sintaxe por uma chamada explícita é mais simples e não tem
    estado global.
    """
    # Caminhos em STRING (`monkeypatch.setattr("src.tools.x.Y", ...)`) também
    # precisam ser reapontados — não são instruções de import, então nenhuma regra
    # de import os alcança, e o teste falharia com ModuleNotFoundError só na
    # execução. Vale para domínio com ou sem hífen: aqui o hífen não incomoda,
    # porque `setattr` resolve o alvo por string.
    texto = re.sub(
        r'(["\'])src\.(?!domains\.)((?:tools|checkers|models|knowledge|db|config)\.)',
        rf"\g<1>src.domains.{dominio}.\g<2>",
        texto,
    )

    if "-" not in dominio:
        return re.sub(
            r"^(from |import )src\.(?!domains\.)",
            rf"\1src.domains.{dominio}.",
            texto,
            flags=re.M,
        )

    base = f"src.domains.{dominio}"
    precisa_importlib = False

    def _from(m: re.Match[str]) -> str:
        nonlocal precisa_importlib
        precisa_importlib = True
        modulo, bruto = m.group(1), (m.group(2) or m.group(3))
        alvo = f"{base}.{modulo}"
        pares = []
        for parte in bruto.replace("\n", " ").split(","):
            parte = parte.strip()
            if not parte:
                continue
            if " as " in parte:
                nome, apelido = (p.strip() for p in parte.split(" as ", 1))
            else:
                nome = apelido = parte
            pares.append((apelido, nome))
        var = "_mod_" + modulo.replace(".", "_")
        linhas = [f'{var} = importlib.import_module("{alvo}")']
        linhas += [f"{apelido} = {var}.{nome}" for apelido, nome in pares]
        return "\n".join(linhas)

    texto = re.sub(
        r"^from src\.([\w.]+) import\s+(?:\(([^)]*)\)|([^\n(]+))",
        _from,
        texto,
        flags=re.M,
    )

    def _import(m: re.Match[str]) -> str:
        nonlocal precisa_importlib
        precisa_importlib = True
        modulo, apelido = m.group(1), m.group(2)
        return f'{apelido} = importlib.import_module("{base}.{modulo}")'

    texto = re.sub(r"^import src\.([\w.]+) as (\w+)", _import, texto, flags=re.M)

    if precisa_importlib:
        # Depois do `from __future__`, que precisa ser a primeira instrução.
        if "\nfrom __future__ import" in texto:
            texto = re.sub(
                r"^(from __future__ import [^\n]+\n)",
                r"\1\nimport importlib\n",
                texto,
                count=1,
                flags=re.M,
            )
        else:
            texto = "import importlib\n\n" + texto
    return texto


# Comentário, e não docstring: o arquivo de origem já tem o seu, e um segundo
# docstring empurraria o `from __future__ import annotations` para longe do topo,
# que é erro de sintaxe.
CABECALHO = """\
# Portado de `{origem}` pelo fan-out de testes.
#
# O código de tool do agregador é byte-a-byte o do servidor legado; só o caminho
# de import muda. Gerado por `scripts/port_domain_tests.py` — reexecutar é
# idempotente. Editar aqui diverge da origem: corrija no legado e reexecute, ou
# aposente o legado (ver ROADMAP, fechar o strangler).

"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--domain", help="porta só este domínio")
    parser.add_argument("--dry-run", action="store_true", help="não escreve")
    args = parser.parse_args()

    dominios = sorted(p.name for p in DOMINIOS_DIR.iterdir() if p.is_dir() and not p.name.startswith("__"))
    if args.domain:
        dominios = [d for d in dominios if d == args.domain]
        if not dominios:
            print(f"domínio desconhecido: {args.domain}", file=sys.stderr)
            return 1

    # O `_existe_no_agregador` importa de dentro do pacote do agregador.
    sys.path.insert(0, str(AGREGADOR))
    os.environ.setdefault("MCP_CONTEXT_SIGNING_KEY", "leitura-estatica")

    portados = ignorados = funcs = 0
    divergentes: list[str] = []
    for dominio in dominios:
        if dominio in JA_COBERTOS:
            continue
        if dominio in DIVERGENTES:
            divergentes.append(
                f"{dominio}/* : domínio inteiro — o código do agregador divergiu do legado"
            )
            # Remove resíduo de execuções anteriores, quando o domínio ainda não
            # estava marcado como divergente.
            residuo = DESTINO_BASE / dominio.replace("-", "_")
            if residuo.is_dir() and not args.dry_run:
                for arquivo in residuo.glob("test_*.py"):
                    arquivo.unlink()
            continue
        legado = ROOT / f"{dominio}-mcp-server" / "tests"
        if not legado.is_dir():
            continue

        aceitos: list[Path] = []
        for caminho in sorted(legado.glob("test_*.py")):
            ok, motivo = _portavel(caminho, dominio)
            if ok:
                aceitos.append(caminho)
            else:
                ignorados += 1
                if motivo.startswith("DIVERGÊNCIA"):
                    divergentes.append(f"{dominio}/{caminho.name}: {motivo}")
                elif args.dry_run:
                    print(f"    - {dominio}/{caminho.name}: {motivo}")
        if not aceitos:
            continue

        # Diretório de destino com underscore: `tests/domains/dev-twin/` não é nome
        # de pacote Python válido, e o pytest precisa importar o diretório como
        # pacote para que arquivos de mesmo nome em domínios diferentes
        # (test_tools_unit.py em seis deles) não colidam.
        destino = DESTINO_BASE / dominio.replace("-", "_")
        if not args.dry_run:
            destino.mkdir(parents=True, exist_ok=True)
            init = destino / "__init__.py"
            if not init.exists():
                init.write_text("", encoding="utf-8", newline="\n")
            # Remove ports antigos, preservando as fixtures escritas à mão.
            for obsoleto in destino.glob("test_*.py"):
                if obsoleto.name not in PRESERVAR:
                    obsoleto.unlink()

        for caminho in aceitos:
            texto = caminho.read_text(encoding="utf-8")
            n = len(RE_TESTE.findall(texto))
            funcs += n
            portados += 1
            origem = f"{dominio}-mcp-server/tests/{caminho.name}"
            conteudo = CABECALHO.format(origem=origem) + _reescreve(texto, dominio)
            print(f"  {'[dry] ' if args.dry_run else ''}{dominio}/{caminho.name} ({n} testes)")
            if not args.dry_run:
                (destino / caminho.name).write_text(conteudo, encoding="utf-8", newline="\n")

    if not args.dry_run and portados:
        DESTINO_BASE.mkdir(parents=True, exist_ok=True)
        (DESTINO_BASE / "__init__.py").write_text("", encoding="utf-8", newline="\n")

    print(f"\nportados: {portados} arquivos / {funcs} funções de teste")
    print(f"ignorados: {ignorados} arquivos")
    if divergentes:
        print(f"\n=== NÃO portados por DIVERGÊNCIA entre as cópias ({len(divergentes)}) ===")
        print("O teste legado cobra um símbolo que o agregador não tem. Portá-lo faria")
        print("o agregador ser cobrado por um comportamento que ele mudou de propósito.")
        for item in divergentes:
            print(f"  {item}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
