#!/usr/bin/env python3
"""Test Doubles Policy scanner (STD-QA-001) — gate de CI.

Proíbe, nos arquivos de teste dos MCP servers, os anti-padrões que mascaram a
autenticação real (bypass de auth, tokens falsos, HS256 em fixtures). A Suíte
Canônica exige RS256 real + verificador real; nunca bypass.

Regras (IDs alinhados ao platform_testkit/policy.py do template):
  T-AUTH-02  bypass flags: AUTH_DEV_BYPASS | LAB_MODE | SKIP_AUTH | DISABLE_AUTH | DEV_BYPASS | USE_MOCK_DATA
  T-AUTH-01  fake bearer:  Bearer test-token | fake-token | dummy | Bearer eyJ...(hardcoded)
  T-AUTH-01  HS* em teste: algorithm(s)=HS256|HS384|HS512
  T-AUTH-03  override de auth: dependency_overrides[...auth...]

Escape hatch p/ testes negativos legítimos: comentário `# testkit: allow <ID>` na mesma linha.

Uso:  python scripts/check_test_doubles.py          # varre */*-mcp-server/tests
      python scripts/check_test_doubles.py path...  # varre paths específicos
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("T-AUTH-02", re.compile(r"\b(AUTH_DEV_BYPASS|LAB_MODE|SKIP_AUTH|DISABLE_AUTH|DEV_BYPASS|USE_MOCK_DATA)\b")),
    ("T-AUTH-01", re.compile(r"Bearer\s+(test-token|fake-token|dummy|eyJ[A-Za-z0-9_\-]{6,})", re.IGNORECASE)),
    ("T-AUTH-01", re.compile(r"algorithms?\s*=\s*\[?\s*['\"]HS(256|384|512)['\"]")),
    ("T-AUTH-03", re.compile(r"dependency_overrides\[[^\]]*auth[^\]]*\]", re.IGNORECASE)),
]

_ALLOW = re.compile(r"#\s*testkit:\s*allow\s+([A-Z0-9\-]+)", re.IGNORECASE)


def scan_file(path: Path) -> list[str]:
    findings: list[str] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return findings
    for lineno, line in enumerate(text.splitlines(), start=1):
        allow = _ALLOW.search(line)
        allowed = allow.group(1).upper() if allow else None
        for rule_id, pat in _RULES:
            if pat.search(line) and allowed != rule_id and allowed != "ALL":
                findings.append(f"{path}:{lineno} [{rule_id}] {line.strip()[:100]}")
    return findings


def main(argv: list[str]) -> int:
    if len(argv) > 1:
        roots = [Path(a) for a in argv[1:]]
    else:
        roots = sorted(Path(".").glob("*-mcp-server/tests"))
    files: list[Path] = []
    for root in roots:
        files.extend(root.rglob("*.py") if root.is_dir() else [root])
    all_findings: list[str] = []
    for f in files:
        all_findings.extend(scan_file(f))
    if all_findings:
        print(f"== Test Doubles Policy: {len(all_findings)} violação(ões) ==")
        for line in all_findings:
            print("  " + line)
        print("\nUse RS256 real (sem bypass). Teste negativo legítimo: `# testkit: allow <ID>`.")
        return 1
    print(f"Test Doubles Policy OK ({len(files)} arquivos de teste varridos).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
