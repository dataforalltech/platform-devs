"""Testes das tools de logs.

Herméticos: subprocess (docker/journalctl) mockado; arquivos via tmp_path.
"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from src.tools import log_tool
from src.tools.log_tool import (
    _file_logs,
    _journald_logs,
    _resolve_log_source,
    _stream_docker_logs,
    _stream_file_logs,
    get_service_logs,
    search_logs,
)

from .conftest import make_service

# ── _resolve_log_source ───────────────────────────────────────────────────── #


def test_resolve_source_docker():
    info = _resolve_log_source({"container_name": "/my-container"})
    assert info == {"source": "docker", "target": "my-container"}


def test_resolve_source_file(tmp_path):
    logf = tmp_path / "app.log"
    logf.write_text("hello\n", encoding="utf-8")
    info = _resolve_log_source({"metadata": {"log_path": str(logf)}})
    assert info["source"] == "file"
    assert info["target"] == str(logf)


def test_resolve_source_metadata_json_string(tmp_path):
    logf = tmp_path / "app.log"
    logf.write_text("hi\n", encoding="utf-8")
    info = _resolve_log_source({"metadata": json.dumps({"log_path": str(logf)})})
    assert info["source"] == "file"


def test_resolve_source_none():
    info = _resolve_log_source({"type": "remote"})
    assert info["source"] == "none"


def test_resolve_source_journald_on_linux():
    # _resolve_log_source faz `import platform` local; patch na origem do módulo.
    with patch("platform.system", return_value="Linux"):
        info = _resolve_log_source({"type": "process", "name": "mysvc"})
    assert info == {"source": "journald", "target": "mysvc"}


def test_resolve_source_bad_metadata_json():
    # metadata inválido → não quebra; cai para 'none'
    info = _resolve_log_source({"metadata": "{not json", "type": "remote"})
    assert info["source"] == "none"


# ── _journald_logs ────────────────────────────────────────────────────────── #


def test_journald_logs_ok():
    run_result = MagicMock()
    run_result.stdout = "boot\nERROR here\n"
    with patch("src.tools.log_tool.subprocess.run", return_value=run_result):
        ok, lines = _journald_logs("unit", lines=10, grep="error")
    assert ok is True
    assert lines == ["ERROR here"]


def test_journald_logs_not_installed():
    with patch("src.tools.log_tool.subprocess.run", side_effect=FileNotFoundError("no journalctl")):
        ok, lines = _journald_logs("unit")
    assert ok is False


def test_get_logs_journald_source():
    from .conftest import InMemoryServiceStore

    store = InMemoryServiceStore()
    make_service(store, name="svc", port=8080, type_="process")
    run_result = MagicMock()
    run_result.stdout = "l1\nl2\n"
    with (
        patch("platform.system", return_value="Linux"),
        patch("src.tools.log_tool.subprocess.run", return_value=run_result),
    ):
        result = get_service_logs(store, name="svc")
    assert result["source"] == "journald"
    assert result["lines_returned"] == 2


# ── _file_logs ────────────────────────────────────────────────────────────── #


def test_file_logs_tail_and_grep(tmp_path):
    logf = tmp_path / "app.log"
    logf.write_text("a\nb ERROR\nc\nd ERROR\n", encoding="utf-8")
    ok, lines = _file_logs(str(logf), lines=100, grep="error")
    assert ok is True
    assert lines == ["b ERROR", "d ERROR"]


def test_file_logs_missing():
    ok, lines = _file_logs("/no/such.log")
    assert ok is False


# ── get_service_logs ──────────────────────────────────────────────────────── #


def test_get_logs_service_not_found(store):
    result = get_service_logs(store, name="ghost")
    assert result["error"] == "not_found"


def test_get_logs_docker_source(store):
    make_service(store, name="svc", port=8080, type_="docker")
    store.upsert("svc", {"container_name": "svc"})
    run_result = MagicMock()
    run_result.stdout = "line1\nline2\n"
    run_result.stderr = ""
    with patch("src.tools.log_tool.subprocess.run", return_value=run_result):
        result = get_service_logs(store, name="svc", lines=10)
    assert result["source"] == "docker"
    assert result["ok"] is True
    assert result["lines_returned"] == 2


def test_get_logs_docker_grep(store):
    make_service(store, name="svc", port=8080, type_="docker")
    store.upsert("svc", {"container_name": "svc"})
    run_result = MagicMock()
    run_result.stdout = "info ok\nERROR bad\n"
    run_result.stderr = ""
    with patch("src.tools.log_tool.subprocess.run", return_value=run_result):
        result = get_service_logs(store, name="svc", grep="error")
    assert result["logs"] == ["ERROR bad"]


def test_get_logs_docker_not_installed(store):
    make_service(store, name="svc", port=8080, type_="docker")
    store.upsert("svc", {"container_name": "svc"})
    with patch("src.tools.log_tool.subprocess.run", side_effect=FileNotFoundError("no docker")):
        result = get_service_logs(store, name="svc")
    assert result["ok"] is False


def test_get_logs_file_source(store, tmp_path):
    logf = tmp_path / "svc.log"
    logf.write_text("l1\nl2\nl3\n", encoding="utf-8")
    make_service(store, name="svc", port=8080, type_="process")
    store.upsert("svc", {"metadata": {"log_path": str(logf)}})
    result = get_service_logs(store, name="svc", lines=2)
    assert result["source"] == "file"
    assert result["logs"] == ["l2", "l3"]


def test_get_logs_no_source(store):
    make_service(store, name="svc", port=8080, type_="remote")
    result = get_service_logs(store, name="svc")
    assert result["error"] == "no_log_source"


# ── search_logs ───────────────────────────────────────────────────────────── #


def test_search_logs_filters(store):
    make_service(store, name="svc", port=8080, type_="docker")
    store.upsert("svc", {"container_name": "svc"})
    run_result = MagicMock()
    run_result.stdout = "boot\nERROR x\ninfo\nERROR y\n"
    run_result.stderr = ""
    with patch("src.tools.log_tool.subprocess.run", return_value=run_result):
        result = search_logs(store, name="svc", pattern="error")
    assert result["matches"] == 2
    assert result["logs"] == ["ERROR x", "ERROR y"]


def test_search_logs_propagates_error(store):
    result = search_logs(store, name="ghost", pattern="x")
    assert result["error"] == "not_found"


# ── streaming (async generator) ───────────────────────────────────────────── #


@pytest.mark.asyncio
async def test_stream_docker_logs_docker_missing():
    with patch("src.tools.log_tool.asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
        chunks = [c async for c in _stream_docker_logs("svc", lines=5)]
    assert any("docker not found" in c for c in chunks)


@pytest.mark.asyncio
async def test_stream_docker_logs_yields_lines():
    async def fake_readline_factory(lines):
        it = iter(lines)

        async def _readline():
            try:
                return next(it)
            except StopIteration:
                return b""

        return _readline

    proc = MagicMock()
    proc.stderr = MagicMock()
    proc.stdout = MagicMock()
    proc.stderr.readline = await fake_readline_factory([b"log-a\n", b"log-b\n"])
    proc.stdout.readline = await fake_readline_factory([b""])
    proc.kill = MagicMock()

    async def fake_exec(*args, **kwargs):
        return proc

    with patch("src.tools.log_tool.asyncio.create_subprocess_exec", side_effect=fake_exec):
        chunks = [c async for c in log_tool._stream_docker_logs("svc", lines=5)]

    joined = "".join(chunks)
    assert "log-a" in joined
    assert "log-b" in joined
    proc.kill.assert_called_once()


@pytest.mark.asyncio
async def test_stream_file_logs_tail_missing():
    with patch("src.tools.log_tool.asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
        chunks = [c async for c in _stream_file_logs("/some.log", lines=5)]
    assert any("tail not found" in c for c in chunks)


@pytest.mark.asyncio
async def test_stream_file_logs_yields_and_filters():
    lines = iter([b"keep ERROR\n", b"drop info\n", b""])

    async def _readline():
        try:
            return next(lines)
        except StopIteration:
            return b""

    proc = MagicMock()
    proc.stdout = MagicMock()
    proc.stdout.readline = _readline
    proc.kill = MagicMock()

    async def fake_exec(*args, **kwargs):
        return proc

    with patch("src.tools.log_tool.asyncio.create_subprocess_exec", side_effect=fake_exec):
        chunks = [c async for c in _stream_file_logs("/some.log", lines=5, grep="error")]

    joined = "".join(chunks)
    assert "keep ERROR" in joined
    assert "drop info" not in joined
    proc.kill.assert_called_once()
