#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Gate estático de CI do "Definition of Done" (DoD) dos MCPs.

Impõe o "Definition of Done" descrito em MCP_SERVICE_STANDARD.md §11 — o conjunto de
critérios que todo servidor MCP DEVE atender para ir a produção. Este checker é
ESTÁTICO: não sobe nenhum servidor. Ele analisa o código-fonte via AST/regex e faz
parse dos pyproject.toml, comparando cada MCP migrado contra o padrão canônico
estabelecido por security/qa-engineer (FastMCP, build_app/build_mcp, BearerAuthMiddleware,
TOOL_REGISTRY + escopo por ferramenta, rotas /v1/health e
/.well-known/oauth-protected-resource, deps de segurança pinadas e ZERO tokens de
teste hardcoded).

Como os critérios do §11 viram checagens estáticas:
  §11 "Fala Streamable HTTP via SDK oficial"      -> usa FastMCP( e define build_app(/build_mcp(
  §11 "Publica /.well-known/oauth-protected-..."  -> registra a rota via custom_route
  §11 "Health público responde"                   -> registra /v1/health via custom_route
  §11 "qualquer rota sem token responde 401"       -> usa BearerAuthMiddleware no /mcp
  §11 "cada ferramenta declara scope mínimo"       -> TOOL_REGISTRY + _scope_for_request
  §11 "Zero token/segredo hardcoded"               -> ausência de test-*-token no dir inteiro
  (infra/deps)                                      -> pyproject declara mcp>=1.10 + pyjwt/cryptography/bcrypt

Uso:
    python scripts/check_mcp_dod.py            # relatório humano (pt-BR)
    python scripts/check_mcp_dod.py --json     # saída estruturada (JSON)

Escopo do gate
--------------
O DoD §11 vale para MCPs que rodam sob o padrão da plataforma (Streamable HTTP + auth
do gateway). Nem todos os diretorios *-mcp-server/ ja foram migrados: pelo roadmap
(§12), apenas os 8 "DevTeam" (security, qa-engineer, architecture, backend, frontend,
devops, product-owner, product-manager) estao no template novo; os demais (audit, config,
deploy, docs, infra, pipeline, qa, services, session, dev-twin, ai-governance, test)
ainda usam o servidor REST legado (mcp.server.Server + FastAPI, sem shared.mcp_auth).

Para o gate ser util (e nao ficar vermelho para sempre por causa de legado ainda nao
migrado), ele distingue os dois casos pelo marcador tecnico do template novo — o uso de
`BearerAuthMiddleware` (import de shared.mcp_auth) no mcp_server.py:
  - MCP MIGRADO  -> avaliado; DEVE cumprir TODOS os criterios ou o gate falha.
  - MCP LEGADO   -> reportado como PENDENTE (nao migrado); nao derruba o gate.
Assim o CI trava regressoes nos MCPs migrados e mostra o backlog de migracao, sem
bloquear o desenvolvimento do que ainda nao foi portado.

Exit code: 0 se TODOS os MCPs MIGRADOS passam; 1 se qualquer MCP migrado falha em
algum criterio (ou se o gateway tiver token de teste no codigo-fonte).

Nota de encoding: o console Windows costuma ser cp1252. Rode com
PYTHONIOENCODING=utf-8 PYTHONUTF8=1 para evitar UnicodeEncodeError.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from pathlib import Path

# Raiz do repositório (scripts/ fica um nível abaixo da raiz).
ROOT = Path(__file__).resolve().parent.parent

# Tokens de teste que jamais podem aparecer em código de produção (§11 "zero segredo hardcoded").
FORBIDDEN_TOKENS = ("test-admin-token", "test-developer-token", "test-readonly-token")

# Dependências de segurança que o pyproject de cada MCP deve declarar.
REQUIRED_DEPS = ("pyjwt", "cryptography", "bcrypt")


# ── Helpers ────────────────────────────────────────────────────────────────── #
def _read(path: Path) -> str:
    """Lê um arquivo texto ignorando erros de decode (arquivos podem ter bytes exóticos)."""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _iter_dir_files(directory: Path):
    """Itera arquivos de texto relevantes de um diretório (ignora binários/venv/cache)."""
    skip_parts = {"__pycache__", ".venv", "venv", "node_modules", ".git", "dist", "build"}
    for path in directory.rglob("*"):
        if not path.is_file():
            continue
        if any(part in skip_parts for part in path.parts):
            continue
        if path.suffix in {".py", ".toml", ".yml", ".yaml", ".json", ".env", ".md", ".txt", ".cfg", ".ini"} \
                or path.name.startswith(".env"):
            yield path


def _find_forbidden_tokens(directory: Path, ignore_tests: bool = False) -> list[str]:
    """Procura tokens de teste em qualquer arquivo do diretório.

    Se ignore_tests=True, arquivos sob uma pasta chamada 'tests' são ignorados
    (asserções de teste que verificam a REJEIÇÃO desses tokens são permitidas).
    """
    hits: list[str] = []
    for path in _iter_dir_files(directory):
        if ignore_tests and "tests" in path.parts:
            continue
        content = _read(path)
        for token in FORBIDDEN_TOKENS:
            if token in content:
                rel = path.relative_to(ROOT).as_posix()
                hits.append(f"{token} @ {rel}")
    return hits


# ── Parse de pyproject.toml ──────────────────────────────────────────────────── #
try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None


def _load_dependencies(pyproject: Path) -> list[str]:
    """Retorna a lista de dependências declaradas em [project].dependencies.

    Usa tomllib quando disponível; cai para um regex tolerante caso contrário.
    """
    text = _read(pyproject)
    if not text:
        return []
    if tomllib is not None:
        try:
            data = tomllib.loads(text)
            deps = data.get("project", {}).get("dependencies", [])
            if isinstance(deps, list):
                return [str(d) for d in deps]
        except Exception:
            pass
    # Fallback: extrai strings entre aspas dentro do bloco dependencies = [ ... ]
    m = re.search(r"dependencies\s*=\s*\[(.*?)\]", text, re.DOTALL)
    if not m:
        return []
    return re.findall(r'["\']([^"\']+)["\']', m.group(1))


def _mcp_version_ok(deps: list[str]) -> bool:
    """Verifica se 'mcp' está declarado com versão mínima >= 1.10."""
    for dep in deps:
        # Normaliza: separa nome do resto (extras, specifiers).
        name = re.split(r"[<>=!~\[\s]", dep.strip(), 1)[0].lower()
        if name != "mcp":
            continue
        m = re.search(r">=\s*(\d+)\.(\d+)", dep)
        if not m:
            # 'mcp' declarado mas sem >= x.y explícito → não satisfaz o critério.
            return False
        major, minor = int(m.group(1)), int(m.group(2))
        return (major, minor) >= (1, 10)
    return False


def _dep_present(deps: list[str], target: str) -> bool:
    """Verifica se uma dependência (por nome, ignorando specifier/extras) está presente."""
    target = target.lower()
    for dep in deps:
        name = re.split(r"[<>=!~\[\s]", dep.strip(), 1)[0].lower()
        if name == target:
            return True
    return False


# ── Análise AST do mcp_server.py ─────────────────────────────────────────────── #
def _analyze_server_source(source: str) -> dict[str, bool]:
    """Extrai os sinais estáticos do mcp_server.py.

    Combina AST (nomes de funções, chamadas) com verificação textual para as
    rotas registradas via decorator @mcp.custom_route(...).
    """
    facts = {
        "usa_fastmcp": False,
        "define_build_app": False,
        "define_build_mcp": False,
        "usa_bearer_auth": False,
        "rota_prm": False,
        "rota_health": False,
        "tem_tool_registry": False,
        "tem_scope_for_request": False,
        # padrão de baixo nível (MCPs legados migrados via shared.mcp_auth):
        "usa_mount_helper": False,   # mount_lowlevel_streamable_http(...)
        "tem_scope_for_tool": False, # dict SCOPE_FOR_TOOL
    }

    try:
        tree = ast.parse(source)
    except SyntaxError:
        return facts

    for node in ast.walk(tree):
        # def build_app / build_mcp / _scope_for_request
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == "build_app":
                facts["define_build_app"] = True
            elif node.name == "build_mcp":
                facts["define_build_mcp"] = True
            elif node.name == "_scope_for_request":
                facts["tem_scope_for_request"] = True
        # Chamadas: FastMCP(...) e BearerAuthMiddleware(...)
        if isinstance(node, ast.Call):
            fn = node.func
            fn_name = None
            if isinstance(fn, ast.Name):
                fn_name = fn.id
            elif isinstance(fn, ast.Attribute):
                fn_name = fn.attr
            if fn_name == "FastMCP":
                facts["usa_fastmcp"] = True
            elif fn_name == "BearerAuthMiddleware":
                facts["usa_bearer_auth"] = True
            elif fn_name == "mount_lowlevel_streamable_http":
                facts["usa_mount_helper"] = True
        # TOOL_REGISTRY / SCOPE_FOR_TOOL como alvo de atribuição (com ou sem anotação)
        targets = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        for tgt in targets:
            if isinstance(tgt, ast.Name) and tgt.id == "TOOL_REGISTRY":
                facts["tem_tool_registry"] = True
            if isinstance(tgt, ast.Name) and tgt.id == "SCOPE_FOR_TOOL":
                facts["tem_scope_for_tool"] = True

    # Rotas registradas via custom_route: checagem textual robusta (decorator).
    facts["rota_prm"] = "/.well-known/oauth-protected-resource" in source and "custom_route" in source
    facts["rota_health"] = "/v1/health" in source and "custom_route" in source

    return facts


# ── Definição dos critérios (rótulo pt-BR + como avaliar) ────────────────────── #
def _evaluate_mcp(mcp_dir: Path) -> dict:
    """Avalia um diretório *-mcp-server contra os critérios do DoD §11."""
    server_file = mcp_dir / "src" / "server" / "mcp_server.py"
    pyproject = mcp_dir / "pyproject.toml"

    source = _read(server_file)
    facts = _analyze_server_source(source)
    deps = _load_dependencies(pyproject)
    token_hits = _find_forbidden_tokens(mcp_dir, ignore_tests=False)

    # Dois padrões válidos: FastMCP (devteam) OU mount_lowlevel_streamable_http (legados).
    # O helper de baixo nível já fornece auth + PRM + health internamente.
    helper = facts["usa_mount_helper"]
    criteria: list[tuple[str, bool, str]] = [
        (
            "Streamable HTTP via SDK (FastMCP+build_app/build_mcp OU mount_lowlevel_streamable_http)",
            (facts["usa_fastmcp"] and facts["define_build_app"] and facts["define_build_mcp"])
            or (helper and facts["define_build_app"]),
            "",
        ),
        (
            "Auth no /mcp (BearerAuthMiddleware direto ou via helper)",
            facts["usa_bearer_auth"] or helper,
            "",
        ),
        (
            "Publica /.well-known/oauth-protected-resource",
            facts["rota_prm"] or helper,
            "",
        ),
        (
            "Health publico /v1/health",
            facts["rota_health"] or helper,
            "",
        ),
        (
            "Escopo por ferramenta (TOOL_REGISTRY+_scope_for_request OU SCOPE_FOR_TOOL)",
            (facts["tem_tool_registry"] and facts["tem_scope_for_request"])
            or (facts["tem_scope_for_tool"] and helper),
            "",
        ),
        (
            "Zero token de teste hardcoded",
            not token_hits,
            ("; ".join(token_hits) if token_hits else ""),
        ),
        (
            "pyproject declara mcp>=1.10",
            _mcp_version_ok(deps),
            "",
        ),
        (
            "pyproject declara deps de seguranca (pyjwt, cryptography, bcrypt)",
            all(_dep_present(deps, d) for d in REQUIRED_DEPS),
            (
                "faltam: " + ", ".join(d for d in REQUIRED_DEPS if not _dep_present(deps, d))
                if not all(_dep_present(deps, d) for d in REQUIRED_DEPS)
                else ""
            ),
        ),
    ]

    results = [
        {"criterio": label, "ok": bool(ok), "detalhe": detail}
        for (label, ok, detail) in criteria
    ]
    # MCP migrado = usa o template novo: FastMCP+BearerAuthMiddleware (devteam) OU o
    # helper mount_lowlevel_streamable_http (legados). Legado REST antigo fica PENDENTE.
    migrado = facts["usa_bearer_auth"] or facts["usa_mount_helper"]
    return {
        "nome": mcp_dir.name,
        "migrado": migrado,
        "passou": all(r["ok"] for r in results),
        "criterios": results,
    }


def _evaluate_gateway() -> dict | None:
    """Avalia o gateway: sem tokens de teste no codigo-fonte (tests/ ignorado)."""
    gw_dir = ROOT / "mcp-gateway"
    if not gw_dir.is_dir():
        return None
    token_hits = _find_forbidden_tokens(gw_dir, ignore_tests=True)
    results = [
        {
            "criterio": "Zero token de teste no codigo-fonte (tests/ ignorado)",
            "ok": not token_hits,
            "detalhe": "; ".join(token_hits) if token_hits else "",
        }
    ]
    return {
        "nome": "mcp-gateway",
        "migrado": True,  # gateway esta sempre no escopo do gate
        "passou": all(r["ok"] for r in results),
        "criterios": results,
    }


# ── Descoberta dos MCPs ──────────────────────────────────────────────────────── #
def _discover_mcp_dirs() -> list[Path]:
    """Todos os diretorios *-mcp-server/ que tenham src/server/mcp_server.py."""
    dirs = []
    for path in sorted(ROOT.glob("*-mcp-server")):
        if (path / "src" / "server" / "mcp_server.py").is_file():
            dirs.append(path)
    return dirs


# ── Saída ────────────────────────────────────────────────────────────────────── #
def _print_human(reports: list[dict]) -> None:
    print("=" * 72)
    print("  Gate do Definition of Done (DoD) dos MCPs  -  MCP_SERVICE_STANDARD.md §11")
    print("=" * 72)

    migrados = [r for r in reports if r["migrado"]]
    legados = [r for r in reports if not r["migrado"]]

    for rep in migrados:
        status = "OK  " if rep["passou"] else "FALHA"
        print(f"\n[{status}] {rep['nome']}")
        for c in rep["criterios"]:
            mark = "  OK  " if c["ok"] else "  X   "
            line = f"{mark}{c['criterio']}"
            if c["detalhe"] and not c["ok"]:
                line += f"  ({c['detalhe']})"
            print(line)

    if legados:
        print("\n" + "." * 72)
        print("PENDENTES de migracao (servidor legado, fora do escopo do gate):")
        for rep in legados:
            print(f"  -  {rep['nome']}")

    total = len(migrados)
    passaram = sum(1 for r in migrados if r["passou"])
    falharam = total - passaram
    print("\n" + "-" * 72)
    print(f"Resumo (MCPs migrados): {passaram}/{total} passaram, {falharam} falharam.")
    if legados:
        print(f"Pendentes de migracao (nao avaliados): {len(legados)}.")
    if falharam:
        nomes = ", ".join(r["nome"] for r in migrados if not r["passou"])
        print(f"Falharam: {nomes}")
    print("-" * 72)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Gate estatico do Definition of Done (§11) dos MCPs."
    )
    parser.add_argument("--json", action="store_true", help="saida estruturada em JSON")
    args = parser.parse_args()

    reports: list[dict] = []
    for mcp_dir in _discover_mcp_dirs():
        reports.append(_evaluate_mcp(mcp_dir))

    gw = _evaluate_gateway()
    if gw is not None:
        reports.append(gw)

    # O gate so considera MCPs migrados; legado fica como pendente (nao derruba o CI).
    migrados = [r for r in reports if r["migrado"]]
    all_ok = all(r["passou"] for r in migrados)

    if args.json:
        payload = {
            "ok": all_ok,
            "total_migrados": len(migrados),
            "passaram": sum(1 for r in migrados if r["passou"]),
            "pendentes_migracao": [r["nome"] for r in reports if not r["migrado"]],
            "relatorios": reports,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_human(reports)

    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
