"""Runner de subprocess centralizado.

Toda chamada a CLI externa (terraform, checkov, infracost, az) passa por aqui.
Garante:

- timeout uniforme (`subprocess.run(..., timeout=...)`)
- captura de stdout + stderr separados
- truncamento de output (defesa contra explosão de response MCP)
- erros tipados (BinaryNotFound, CommandTimeout) que o server converte em payload JSON estruturado
- log estruturado de cada invocação (cmd, cwd, exit code, duração)
- nunca expõe stderr de credentials no log (heurística simples — qualquer linha
  com 'token', 'secret', 'password' é redacted)

Não faz shell=True. Sempre lista de args.
"""

from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

from .logger import get_logger

_log = get_logger(__name__)

_REDACT_RE = re.compile(
    r"(token|secret|password|key|credential)[\s:=\"']*\S+",
    re.IGNORECASE,
)


@dataclass
class CommandResult:
    """Resultado estruturado de uma execução."""

    cmd: list[str]
    cwd: str
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    truncated: bool = False


class BinaryNotFound(RuntimeError):
    """CLI binário não encontrado no PATH."""


class CommandTimeout(RuntimeError):
    """Comando excedeu o timeout."""


def _redact(line: str) -> str:
    """Mascara tokens/secrets em logs."""
    return _REDACT_RE.sub(r"\1=***", line)


def _truncate(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars] + "\n…(truncated)", True


def run_command(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    timeout: int,
    output_max_chars: int,
    env_extra: dict[str, str] | None = None,
) -> CommandResult:
    """Executa `cmd` com timeout. Retorna CommandResult.

    Não levanta para exit codes != 0 — terraform plan retorna 2 quando há
    mudanças (`-detailed-exitcode`), o caller decide o que fazer.
    """
    if not cmd:
        raise ValueError("cmd vazio")

    binary = cmd[0]
    cwd_str = str(cwd) if cwd is not None else None

    import os
    import shutil

    if shutil.which(binary) is None:
        # Tenta caminho explícito antes de desistir.
        if not Path(binary).is_file():
            raise BinaryNotFound(
                f"Binário '{binary}' não encontrado no PATH. "
                "Configure via INFRA_<TOOL>_BIN ou instale a CLI no host."
            )

    env = None
    if env_extra:
        env = {**os.environ, **env_extra}

    started = time.monotonic()
    _log.info(
        "subprocess_start",
        extra={"extras": {"cmd": cmd[0], "args_count": len(cmd) - 1, "cwd": cwd_str}},
    )

    try:
        proc = subprocess.run(  # noqa: S603 — args como lista, sem shell
            cmd,
            cwd=cwd_str,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
    except subprocess.TimeoutExpired as e:
        duration_ms = int((time.monotonic() - started) * 1000)
        _log.warning(
            "subprocess_timeout",
            extra={"extras": {"cmd": binary, "timeout_s": timeout, "duration_ms": duration_ms}},
        )
        raise CommandTimeout(
            f"'{binary}' excedeu {timeout}s (decorrido {duration_ms}ms antes do kill)"
        ) from e

    duration_ms = int((time.monotonic() - started) * 1000)
    stdout, t1 = _truncate(proc.stdout or "", output_max_chars)
    stderr, t2 = _truncate(proc.stderr or "", output_max_chars)

    _log.info(
        "subprocess_done",
        extra={
            "extras": {
                "cmd": binary,
                "exit": proc.returncode,
                "duration_ms": duration_ms,
                "stdout_chars": len(stdout),
                "stderr_chars": len(stderr),
                "truncated": t1 or t2,
            }
        },
    )
    if stderr:
        # Log redacted stderr line-by-line para visibility, sem vazar segredo.
        for line in stderr.splitlines()[:20]:
            _log.debug("subprocess_stderr", extra={"extras": {"line": _redact(line)}})

    return CommandResult(
        cmd=cmd,
        cwd=cwd_str or "",
        exit_code=proc.returncode,
        stdout=stdout,
        stderr=stderr,
        duration_ms=duration_ms,
        truncated=t1 or t2,
    )
