"""Testes de coleta de informações físicas (sysinfo) — psutil mockado (hermetico)."""

from __future__ import annotations

import socket
from types import SimpleNamespace

import pytest

import src.knowledge.sysinfo as sysinfo
from src.tools.sysinfo_tool import get_physical_info


def _fake_addr(family, address):
    return SimpleNamespace(family=family, address=address)


@pytest.fixture()
def mocked_psutil(monkeypatch):
    """Substitui todas as chamadas psutil por valores determinísticos."""
    ps = sysinfo.psutil
    monkeypatch.setattr(ps, "cpu_freq", lambda: SimpleNamespace(current=2400.7))
    monkeypatch.setattr(ps, "cpu_count", lambda logical=True: 8 if logical else 4)
    monkeypatch.setattr(ps, "cpu_percent", lambda interval=0.3: 12.5)
    monkeypatch.setattr(
        ps,
        "virtual_memory",
        lambda: SimpleNamespace(
            total=16 * 1024**3,
            available=8 * 1024**3,
            used=8 * 1024**3,
            percent=50.0,
        ),
    )

    part_ok = SimpleNamespace(device="/dev/sda1", mountpoint="/", fstype="ext4")
    part_bad = SimpleNamespace(device="/dev/sdb1", mountpoint="/locked", fstype="ntfs")
    monkeypatch.setattr(ps, "disk_partitions", lambda all=False: [part_ok, part_bad])

    def fake_disk_usage(mountpoint):
        if mountpoint == "/locked":
            raise PermissionError("denied")
        return SimpleNamespace(total=500 * 1024**3, used=250 * 1024**3, free=250 * 1024**3, percent=50.0)

    monkeypatch.setattr(ps, "disk_usage", fake_disk_usage)
    monkeypatch.setattr(
        ps,
        "net_if_addrs",
        lambda: {
            "eth0": [
                _fake_addr(socket.AF_INET, "192.168.0.10"),
                _fake_addr(socket.AF_INET, "127.0.0.1"),
            ],
        },
    )
    return ps


class TestCollectPhysicalInfo:
    def test_structure(self, mocked_psutil):
        info = sysinfo.collect_physical_info()
        assert set(info) == {"os", "cpu", "ram", "disks", "network"}

    def test_cpu_values(self, mocked_psutil):
        info = sysinfo.collect_physical_info()
        assert info["cpu"]["physical_cores"] == 4
        assert info["cpu"]["logical_cores"] == 8
        assert info["cpu"]["frequency_mhz"] == 2400.7
        assert info["cpu"]["usage_percent"] == 12.5

    def test_ram_values(self, mocked_psutil):
        info = sysinfo.collect_physical_info()
        assert info["ram"]["total_gb"] == 16.0
        assert info["ram"]["percent_used"] == 50.0

    def test_disk_skips_permission_error(self, mocked_psutil):
        info = sysinfo.collect_physical_info()
        # only the accessible partition is included
        assert len(info["disks"]) == 1
        assert info["disks"][0]["mountpoint"] == "/"

    def test_network_excludes_loopback(self, mocked_psutil):
        info = sysinfo.collect_physical_info()
        assert info["network"] == {"eth0": "192.168.0.10"}

    def test_cpu_freq_none(self, mocked_psutil, monkeypatch):
        monkeypatch.setattr(mocked_psutil, "cpu_freq", lambda: None)
        info = sysinfo.collect_physical_info()
        assert info["cpu"]["frequency_mhz"] is None

    def test_network_exception_swallowed(self, mocked_psutil, monkeypatch):
        def boom():
            raise RuntimeError("no net")

        monkeypatch.setattr(mocked_psutil, "net_if_addrs", boom)
        info = sysinfo.collect_physical_info()
        assert info["network"] == {}


class TestGetPhysicalInfoTool:
    async def test_success(self, mocked_psutil):
        result = await get_physical_info()
        assert result["success"] is True
        assert "cpu" in result

    async def test_failure_returns_error(self, monkeypatch):
        def boom():
            raise RuntimeError("collector down")

        monkeypatch.setattr("src.tools.sysinfo_tool.collect_physical_info", boom)
        result = await get_physical_info()
        assert result["success"] is False
        assert result["error"] == "collector down"
