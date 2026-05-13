"""Ferramentas de monitoramento de logs de servicos.

Tools (MCP — snapshot)
-----------------------
- get_service_logs  : busca as ultimas N linhas de log de um servico
- search_logs       : busca por padrao regex/substring nos logs recentes

Streaming (HTTP sidecar)
------------------------
Endpoint SSE exposto pelo FastAPI:
  GET /v1/services/{name}/logs/stream?lines=50&grep=<pattern>

Fontes de log (ordem de resolucao)
-----------------------------------
1. Docker container  — se container_name estiver no registry
2. Arquivo de log    — se metadata["log_path"] existir
3. Systemd/journald  — se tipo "process" e Linux
4. /proc/<pid>/fd/1  — fallback para processos Linux

Formato de ``since``
--------------------
Aceita: '30m', '1h', '2h30m', '5s', ou timestamp ISO 8601.
Docker aceita diretamente: '10m', '1h', ISO timestamp.
"""
from __future__ import annotations

import asyncio
import re
import subprocess
import time
from pathlib import Path
from typing import Any, AsyncIterator

from ..db.store import ServiceStore

_log_module_logger = __import__("logging").getLogger(__name__)

# Formatos de since relativo que docker aceita nativamente
_SINCE_RE = re.compile(r"^\d+[smhd]$")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _resolve_log_source(svc: dict) -> dict[str, Any]:
    """Determina a fonte de log a partir do registro do servico.

    Retorna dict com chaves:
      source: "docker" | "file" | "journald" | "none"
      target: container_name | file_path | unit_name
    """
    import json
    meta = svc.get("metadata") or {}
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}

    # 1. Docker container
    container = svc.get("container_name") or meta.get("container_name")
    if container:
        return {"source": "docker", "target": container.lstrip("/")}

    # 2. Arquivo de log
    log_path = meta.get("log_path") or meta.get("LOG_PATH")
    if log_path and Path(log_path).exists():
        return {"source": "file", "target": log_path}

    # 3. Systemd (Linux, type=process)
    import platform
    if svc.get("type") == "process" and platform.system().lower() == "linux":
        name = svc.get("name", "")
        return {"source": "journald", "target": name}

    return {"source": "none", "target": None}


def _docker_logs(
    container: str,
    *,
    lines: int = 100,
    since: str | None = None,
    grep: str | None = None,
    timestamps: bool = False,
    timeout: int = 10,
) -> tuple[bool, list[str]]:
    """Executa docker logs e retorna (ok, linhas)."""
    cmd = ["docker", "logs", "--tail", str(lines)]
    if since:
        cmd += ["--since", since]
    if timestamps:
        cmd += ["--timestamps"]
    cmd.append(container)

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        # docker logs manda para stderr por padrao
        raw = (r.stdout + r.stderr).splitlines()
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return False, [str(exc)]

    if grep:
        pattern = re.compile(grep, re.IGNORECASE)
        raw = [l for l in raw if pattern.search(l)]

    return True, raw


def _file_logs(
    path: str,
    *,
    lines: int = 100,
    grep: str | None = None,
) -> tuple[bool, list[str]]:
    """Le as ultimas N linhas de um arquivo de log."""
    try:
        p = Path(path)
        if not p.exists():
            return False, [f"Arquivo nao encontrado: {path}"]
        content = p.read_text(errors="replace").splitlines()
        raw = content[-lines:]
    except OSError as exc:
        return False, [str(exc)]

    if grep:
        pattern = re.compile(grep, re.IGNORECASE)
        raw = [l for l in raw if pattern.search(l)]

    return True, raw


def _journald_logs(
    unit: str,
    *,
    lines: int = 100,
    since: str | None = None,
    grep: str | None = None,
) -> tuple[bool, list[str]]:
    """Le logs do systemd/journald."""
    cmd = ["journalctl", "-u", unit, "-n", str(lines), "--no-pager"]
    if since:
        cmd += ["--since", since]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        raw = r.stdout.splitlines()
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return False, [str(exc)]

    if grep:
        pattern = re.compile(grep, re.IGNORECASE)
        raw = [l for l in raw if pattern.search(l)]

    return True, raw


# ── Async generator para streaming SSE ───────────────────────────────────────

async def _stream_docker_logs(
    container: str,
    *,
    lines: int = 50,
    grep: str | None = None,
    timestamps: bool = False,
) -> AsyncIterator[str]:
    """Gera linhas de log em tempo real via docker logs --follow."""
    cmd = ["docker", "logs", "--follow", "--tail", str(lines)]
    if timestamps:
        cmd.append("--timestamps")
    cmd.append(container)

    pattern = re.compile(grep, re.IGNORECASE) if grep else None

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        yield "data: {\"error\": \"docker not found\"}\n\n"
        return

    async def read_stream(stream):
        while True:
            line = await stream.readline()
            if not line:
                break
            yield line.decode(errors="replace").rstrip()

    async def merge():
        # docker logs envia para stderr
        async for line in read_stream(proc.stderr):
            yield line
        async for line in read_stream(proc.stdout):
            yield line

    try:
        async for line in merge():
            if pattern and not pattern.search(line):
                continue
            # SSE format
            escaped = line.replace("\n", " ")
            yield f"data: {escaped}\n\n"
    finally:
        try:
            proc.kill()
        except Exception:
            pass


async def _stream_file_logs(
    path: str,
    *,
    lines: int = 50,
    grep: str | None = None,
) -> AsyncIterator[str]:
    """Segue um arquivo de log com tail -f semantics."""
    cmd = ["tail", "-n", str(lines), "-f", path]
    pattern = re.compile(grep, re.IGNORECASE) if grep else None

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        yield "data: {\"error\": \"tail not found\"}\n\n"
        return

    try:
        while True:
            line_bytes = await asyncio.wait_for(proc.stdout.readline(), timeout=30)
            if not line_bytes:
                break
            line = line_bytes.decode(errors="replace").rstrip()
            if pattern and not pattern.search(line):
                continue
            yield f"data: {line}\n\n"
    except asyncio.TimeoutError:
        yield "data: {\"keepalive\": true}\n\n"
    finally:
        try:
            proc.kill()
        except Exception:
            pass


# ── MCP Tools ─────────────────────────────────────────────────────────────────

def get_service_logs(
    store: ServiceStore,
    *,
    name: str,
    lines: int = 100,
    since: str | None = None,
    grep: str | None = None,
    timestamps: bool = False,
) -> dict[str, Any]:
    """Retorna as ultimas N linhas de log de um servico registrado.

    Suporta servicos Docker (container_name), arquivos de log (metadata.log_path)
    e processos systemd (Linux).

    since: '30m', '1h', '2h', '5s' ou timestamp ISO 8601.
    grep:  filtro regex case-insensitive nas linhas retornadas.
    """
    svc = store.get(name)
    if svc is None:
        return {"error": "not_found", "name": name}

    source_info = _resolve_log_source(svc)
    source = source_info["source"]
    target = source_info["target"]

    t0 = time.monotonic()

    if source == "docker":
        ok, log_lines = _docker_logs(
            target, lines=lines, since=since, grep=grep, timestamps=timestamps
        )
    elif source == "file":
        ok, log_lines = _file_logs(target, lines=lines, grep=grep)
    elif source == "journald":
        ok, log_lines = _journald_logs(target, lines=lines, since=since, grep=grep)
    else:
        return {
            "name": name,
            "error": "no_log_source",
            "detail": (
                "Nenhuma fonte de log encontrada. "
                "Defina container_name no registro ou adicione 'log_path' no metadata."
            ),
        }

    elapsed_ms = round((time.monotonic() - t0) * 1000, 1)

    return {
        "name": name,
        "source": source,
        "target": target,
        "lines_requested": lines,
        "lines_returned": len(log_lines),
        "grep": grep,
        "since": since,
        "elapsed_ms": elapsed_ms,
        "ok": ok,
        "logs": log_lines,
    }


def search_logs(
    store: ServiceStore,
    *,
    name: str,
    pattern: str,
    lines: int = 500,
    since: str | None = None,
) -> dict[str, Any]:
    """Busca por padrao regex nos logs recentes de um servico.

    Retorna apenas as linhas que batem com o padrao.
    lines: quantas linhas recentes vasculhar antes de filtrar.
    """
    result = get_service_logs(store, name=name, lines=lines, since=since, grep=pattern)
    if "error" in result:
        return result

    matched = result.get("logs", [])
    return {
        "name": name,
        "pattern": pattern,
        "lines_searched": lines,
        "matches": len(matched),
        "logs": matched,
        "source": result.get("source"),
        "elapsed_ms": result.get("elapsed_ms"),
    }
