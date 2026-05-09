"""Coleta informações de hardware e sistema operacional."""
from __future__ import annotations

import platform
import socket
from typing import Any

import psutil


def collect_physical_info() -> dict[str, Any]:
    """Retorna snapshot do hardware e OS atual."""

    # ── CPU ───────────────────────────────────────────────────────────────── #
    freq = psutil.cpu_freq()
    cpu: dict[str, Any] = {
        "physical_cores": psutil.cpu_count(logical=False),
        "logical_cores": psutil.cpu_count(logical=True),
        "frequency_mhz": round(freq.current, 1) if freq else None,
        "usage_percent": psutil.cpu_percent(interval=0.3),
        "architecture": platform.machine(),
        "processor": platform.processor() or platform.machine(),
    }

    # ── RAM ───────────────────────────────────────────────────────────────── #
    vm = psutil.virtual_memory()
    ram: dict[str, Any] = {
        "total_gb": round(vm.total / 1024**3, 2),
        "available_gb": round(vm.available / 1024**3, 2),
        "used_gb": round(vm.used / 1024**3, 2),
        "percent_used": vm.percent,
    }

    # ── Disk ──────────────────────────────────────────────────────────────── #
    disks: list[dict[str, Any]] = []
    for part in psutil.disk_partitions(all=False):
        try:
            usage = psutil.disk_usage(part.mountpoint)
            disks.append({
                "device": part.device,
                "mountpoint": part.mountpoint,
                "fstype": part.fstype,
                "total_gb": round(usage.total / 1024**3, 2),
                "used_gb": round(usage.used / 1024**3, 2),
                "free_gb": round(usage.free / 1024**3, 2),
                "percent_used": usage.percent,
            })
        except (PermissionError, OSError):
            pass

    # ── OS ────────────────────────────────────────────────────────────────── #
    os_info: dict[str, Any] = {
        "system": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "hostname": socket.gethostname(),
        "python_version": platform.python_version(),
        "node": platform.node(),
    }

    # ── Network ───────────────────────────────────────────────────────────── #
    net: dict[str, str] = {}
    try:
        for iface, addrs in psutil.net_if_addrs().items():
            for addr in addrs:
                if addr.family == socket.AF_INET and not addr.address.startswith("127."):
                    net[iface] = addr.address
    except Exception:  # noqa: BLE001
        pass

    return {"os": os_info, "cpu": cpu, "ram": ram, "disks": disks, "network": net}
