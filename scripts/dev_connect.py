#!/usr/bin/env python3
"""dev_connect.py — emite tokens de teste e monta os comandos `claude mcp add` dos DevTeam.

Fluxo de teste local (ver deploy/dev/README.md):
  1. docker compose -f deploy/dev/docker-compose.dev.yml up -d --build
  2. python scripts/dev_connect.py            # imprime os comandos claude mcp add
     python scripts/dev_connect.py --run       # executa os comandos (registra os MCPs)
     python scripts/dev_connect.py --scope user # escopo da config (user|project|local)

Emite um token por DevTeam via client_credentials no auth-mcp de dev (client 'security-dev',
com escopo de todos os DevTeam). Cada token tem aud = RESOURCE do DevTeam — o DevTeam rejeita
tokens de aud diferente, então é um token por DevTeam.

Sem dependências externas (usa urllib). Rode com PYTHONUTF8=1 no Windows.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.parse
import urllib.request

AS_TOKEN_URL = "http://localhost:7103/oauth/token"
CLIENT_ID = "security-dev"
CLIENT_SECRET = "dev-secret-change-me"  # client de DEMO do modo dev (não é segredo real)

# nome do MCP → (porta, escopos a pedir)
DEVTEAM = {
    "security": (7125, "security:read security:scan security:model"),
    "qa-engineer": (7124, "qa-engineer:read qa-engineer:write"),
    "architecture": (7118, "architecture:read architecture:write"),
    "backend": (7119, "backend:read backend:write"),
    "frontend": (7120, "frontend:read frontend:write"),
    "devops": (7121, "devops:read devops:write"),
    "product-owner": (7122, "product-owner:read product-owner:write"),
    "product-manager": (7123, "product-manager:read product-manager:write"),
}


def mint_token(resource: str, scope: str) -> str:
    data = urllib.parse.urlencode({
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "resource": resource,
        "scope": scope,
    }).encode()
    req = urllib.request.Request(AS_TOKEN_URL, data=data,
                                headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read())["access_token"]


def main() -> int:
    ap = argparse.ArgumentParser(description="Conecta os DevTeam de dev ao Claude Code")
    ap.add_argument("--run", action="store_true", help="executa os comandos claude mcp add")
    ap.add_argument("--scope", default="user", choices=["user", "project", "local"],
                    help="escopo da config do Claude Code (default: user)")
    args = ap.parse_args()

    try:
        urllib.request.urlopen("http://localhost:7103/v1/health", timeout=5)
    except Exception as e:
        print(f"ERRO: auth-mcp não responde em http://localhost:7103 ({e}).", file=sys.stderr)
        print("Suba o stack de dev antes:\n"
              "  docker compose -f deploy/dev/docker-compose.dev.yml up -d --build", file=sys.stderr)
        return 1

    print("# Comandos para registrar os DevTeam no Claude Code (transporte HTTP + Bearer):\n")
    failures = 0
    for name, (port, scope) in DEVTEAM.items():
        resource = f"http://localhost:{port}/mcp"
        try:
            token = mint_token(resource, scope)
        except Exception as e:
            print(f"# [FALHA] {name}: não consegui emitir token ({e})", file=sys.stderr)
            failures += 1
            continue
        cmd = ["claude", "mcp", "add", "--transport", "http", "--scope", args.scope,
               name, resource, "--header", f"Authorization: Bearer {token}"]
        print(" ".join(f'"{c}"' if " " in c else c for c in cmd))
        if args.run:
            r = subprocess.run(cmd)
            if r.returncode != 0:
                failures += 1

    print()
    if args.run:
        print("Feito. Verifique com:  claude mcp list")
    else:
        print("Rode com --run para registrar automaticamente, ou cole os comandos acima.")
    print("Tokens válidos por ~1 dia (AS_TOKEN_TTL do dev). Re-rode este script para renovar.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
