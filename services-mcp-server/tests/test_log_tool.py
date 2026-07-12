"""Logs: get_service_logs / search_logs + resolução da fonte de log.

Banco real (FID-02); docker/journald são o único duplo (arquivos de log são reais).
"""

from __future__ import annotations

import pytest

from src.tools import log_tool
from src.tools.log_tool import _resolve_log_source, get_service_logs, search_logs

from .conftest import requires_mysql


class _FakeProc:
    def __init__(self, returncode: int = 0, stdout: str = "", stderr: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


# ── _resolve_log_source (hermético) ───────────────────────────────────────────
def test_resolve_source_docker():
    src = _resolve_log_source({"container_name": "/ctr", "type": "docker"})
    assert src == {"source": "docker", "target": "ctr"}


def test_resolve_source_file(tmp_path):
    logf = tmp_path / "app.log"
    logf.write_text("line\n", encoding="utf-8")
    src = _resolve_log_source({"metadata": {"log_path": str(logf)}})
    assert src["source"] == "file"
    assert src["target"] == str(logf)


def test_resolve_source_metadata_json_string(tmp_path):
    logf = tmp_path / "app.log"
    logf.write_text("x\n", encoding="utf-8")
    import json

    src = _resolve_log_source({"metadata": json.dumps({"log_path": str(logf)})})
    assert src["source"] == "file"


def test_resolve_source_journald(monkeypatch):
    import platform

    monkeypatch.setattr(platform, "system", lambda: "Linux")
    src = _resolve_log_source({"type": "process", "name": "svc"})
    assert src == {"source": "journald", "target": "svc"}


def test_resolve_source_none():
    assert _resolve_log_source({"type": "remote"})["source"] == "none"


# ── get_service_logs ──────────────────────────────────────────────────────────
@pytest.mark.integration
@requires_mysql
async def test_get_logs_not_found(store_a):
    assert (await get_service_logs(store_a, name="ghost"))["error"] == "not_found"


@pytest.mark.integration
@requires_mysql
async def test_get_logs_docker(store_a, monkeypatch):
    monkeypatch.setattr(
        log_tool.subprocess,
        "run",
        lambda *a, **k: _FakeProc(stdout="line-a\nline-b ERROR\n"),
    )
    await store_a.upsert("svc", {"container_name": "ctr", "type": "docker"})
    result = await get_service_logs(store_a, name="svc", lines=10)
    assert result["source"] == "docker"
    assert result["lines_returned"] == 2
    assert result["ok"] is True


@pytest.mark.integration
@requires_mysql
async def test_get_logs_docker_grep(store_a, monkeypatch):
    monkeypatch.setattr(
        log_tool.subprocess,
        "run",
        lambda *a, **k: _FakeProc(stdout="info line\nERROR boom\n"),
    )
    await store_a.upsert("svc", {"container_name": "ctr", "type": "docker"})
    result = await get_service_logs(store_a, name="svc", grep="error")
    assert result["lines_returned"] == 1
    assert "ERROR" in result["logs"][0]


@pytest.mark.integration
@requires_mysql
async def test_get_logs_file(store_a, tmp_path):
    logf = tmp_path / "app.log"
    logf.write_text("a\nb\nc\n", encoding="utf-8")
    await store_a.upsert("svc", {"metadata": {"log_path": str(logf)}})
    result = await get_service_logs(store_a, name="svc", lines=2)
    assert result["source"] == "file"
    assert result["logs"] == ["b", "c"]


@pytest.mark.integration
@requires_mysql
async def test_get_logs_no_source(store_a):
    await store_a.upsert("svc", {"type": "remote"})
    result = await get_service_logs(store_a, name="svc")
    assert result["error"] == "no_log_source"


# ── search_logs ───────────────────────────────────────────────────────────────
@pytest.mark.integration
@requires_mysql
async def test_search_logs_matches(store_a, monkeypatch):
    monkeypatch.setattr(
        log_tool.subprocess,
        "run",
        lambda *a, **k: _FakeProc(stdout="ok\nERROR one\nERROR two\n"),
    )
    await store_a.upsert("svc", {"container_name": "ctr", "type": "docker"})
    result = await search_logs(store_a, name="svc", pattern="error")
    assert result["matches"] == 2
    assert result["source"] == "docker"


@pytest.mark.integration
@requires_mysql
async def test_search_logs_not_found(store_a):
    result = await search_logs(store_a, name="ghost", pattern="x")
    assert result["error"] == "not_found"
