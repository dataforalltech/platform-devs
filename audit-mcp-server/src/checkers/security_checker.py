import re
from pathlib import Path
from typing import Any

# Diretórios que nunca contêm código-fonte do repositório auditado. A exclusão é
# por NOME de diretório, e não por "começa com ponto": a regra antiga descartava
# `.env` — justamente o arquivo de maior valor para credencial hardcoded.
_SKIP_DIRS = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        ".tox",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "__pycache__",
        "node_modules",
        "dist",
        "build",
        ".next",
        ".terraform",
    }
)

# Sufixos de arquivo varridos. `.env` NÃO entra aqui: `Path('.env').suffix` é ''
# e `Path('.env.local').suffix` é '.local'. Os nomes de arquivo de ambiente são
# tratados à parte, em _is_env_file.
_SCAN_SUFFIXES = frozenset({".py", ".yaml", ".yml", ".conf", ".ini", ".toml", ".sh"})


def _is_env_file(file_path: Path) -> bool:
    """Reconhece `.env`, `.env.local`, `.env.production`, `env.sh`… pelo NOME."""
    name = file_path.name
    return name == ".env" or name.startswith(".env.") or name.endswith(".env")


class SecurityChecker:
    """Verifica segurança: credenciais hardcoded, vulnerabilidades.

    Contrato de honestidade: um item que NÃO foi executado é reportado com
    ``executed=False`` e fica FORA do denominador do score. Nunca é reportado
    como ``passed=True`` — um check que não rodou não é evidência de nada, e
    tratá-lo como aprovação cria um piso artificial no score que alimenta o
    ``auto_approve_if_score`` do run_audit.
    """

    CREDENTIAL_PATTERNS = [
        (r"password\s*=\s*['\"]([^'\"]+)['\"]", "hardcoded_password"),
        (r"api_key\s*=\s*['\"]([^'\"]+)['\"]", "hardcoded_api_key"),
        (r"token\s*=\s*['\"]([^'\"]+)['\"]", "hardcoded_token"),
        (r"secret\s*=\s*['\"]([^'\"]+)['\"]", "hardcoded_secret"),
        (r"GITHUB_TOKEN\s*=\s*['\"]([^'\"]+)['\"]", "hardcoded_github_token"),
        (r"AWS_ACCESS_KEY\s*=\s*['\"]([^'\"]+)['\"]", "hardcoded_aws_key"),
        (r"private_key\s*=\s*['\"]([^'\"]+)['\"]", "hardcoded_private_key"),
    ]

    @staticmethod
    def run(repo_path: str, env: str = "dev") -> dict[str, Any]:
        """Retorna resultado de checagens de segurança."""
        repo = Path(repo_path)
        items: list[dict[str, Any]] = []

        # Check: no_hardcoded_credentials — o único que roda de verdade hoje.
        found_creds, truncated = SecurityChecker._scan_for_credentials(repo)

        if truncated:
            # Varredura truncada não sustenta a afirmação "não há credencial":
            # o arquivo ofensor pode estar entre os que não foram abertos.
            # Inconclusivo, e não aprovado.
            items.append(
                {
                    "category": "security",
                    "name": "no_hardcoded_credentials",
                    "required": True,
                    "executed": False,
                    "passed": False,
                    "details": (
                        "INCONCLUSIVO: varredura atingiu o teto de arquivos e foi truncada; "
                        f"{len(found_creds)} padrão(ões) encontrado(s) até o corte. "
                        "Aumente max_files ou reduza o escopo."
                    ),
                }
            )
        else:
            items.append(
                {
                    "category": "security",
                    "name": "no_hardcoded_credentials",
                    "required": True,
                    "executed": True,
                    "passed": len(found_creds) == 0,
                    "details": (
                        f"Found {len(found_creds)} credential patterns"
                        if found_creds
                        else "No hardcoded credentials detected"
                    ),
                }
            )

        # Checks de vulnerabilidade: NÃO IMPLEMENTADOS.
        # Reportados como não executados — nunca como aprovados. Enquanto não
        # houver pip-audit/safety no pipeline, `no_critical_vulnerabilities` é um
        # requisito obrigatório sem evidência, e o run_audit deve recusar a
        # auto-aprovação por causa disso (ver audit_tool._has_unexecuted_required).
        for name, required in (
            ("no_critical_vulnerabilities", True),
            ("no_high_vulnerabilities", False),
        ):
            items.append(
                {
                    "category": "security",
                    "name": name,
                    "required": required,
                    "executed": False,
                    "passed": False,
                    "details": (
                        "NÃO EXECUTADO: varredura de vulnerabilidades não implementada "
                        "(pip-audit/safety ausentes do pipeline)."
                    ),
                }
            )

        # O score reflete apenas o que foi EXECUTADO. Um check não executado não
        # entra nem como acerto nem como erro: ele entra como bloqueio de
        # auto-aprovação, que é onde a ausência de evidência deve doer.
        executed = [i for i in items if i.get("executed", True)]
        passed_count = sum(1 for i in executed if i["passed"])
        total = len(executed)

        return {
            "category": "security",
            "items": items,
            "score": passed_count / total if total > 0 else 0.0,
        }

    @staticmethod
    def _scan_for_credentials(
        repo_path: Path, max_files: int = 5000
    ) -> tuple[list[str], bool]:
        """Escaneia o repositório à procura de padrões de credencial.

        Returns:
            ``(achados, truncado)``. ``truncado`` é True quando o teto de
            ``max_files`` foi atingido — nesse caso a ausência de achados NÃO
            significa ausência de credencial, e o caller deve tratar o resultado
            como inconclusivo em vez de aprovado.
        """
        found: list[str] = []
        file_count = 0
        truncated = False

        for file_path in repo_path.rglob("*"):
            if file_count >= max_files:
                truncated = True
                break
            if not file_path.is_file():
                continue

            # Exclusão por nome de diretório conhecido — jamais por "começa com
            # ponto", que descartaria o próprio `.env`.
            if any(part in _SKIP_DIRS for part in file_path.parts):
                continue

            if file_path.suffix not in _SCAN_SUFFIXES and not _is_env_file(file_path):
                continue

            try:
                with open(file_path, encoding="utf-8", errors="ignore") as f:
                    content = f.read()

                    for pattern, cred_type in SecurityChecker.CREDENTIAL_PATTERNS:
                        if re.search(pattern, content, re.IGNORECASE):
                            found.append(f"{file_path}: {cred_type}")

                file_count += 1
            except OSError:
                # Arquivo ilegível não é evidência de ausência de credencial, mas
                # também não é achado: segue adiante sem contar no teto.
                continue

        return found, truncated
