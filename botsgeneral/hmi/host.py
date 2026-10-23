"""Host monitoring: Central Processing Unit (CPU), memory, disk, load, uptime."""

from __future__ import annotations

import os
import shutil
import time
from pathlib import Path
from typing import Any

_last_cpu: tuple[float, float] | None = None


def _read_cpu_times() -> tuple[float, float] | None:
    p = Path("/proc/stat")
    if not p.exists():
        return None
    try:
        parts = p.read_text(encoding="utf-8", errors="ignore").splitlines()[0].split()
        nums = [float(x) for x in parts[1:8]]
        idle = nums[3] + (nums[4] if len(nums) > 4 else 0.0)
        total = float(sum(nums))
        return idle, total
    except Exception:
        return None


def cpu_info(sample_sec: float = 0.05) -> dict[str, Any]:
    """Percent busy from /proc/stat (idle+iowait vs total). Falls back to load/nproc."""
    global _last_cpu
    nproc = int(os.cpu_count() or 1)
    now = _read_cpu_times()
    source = "proc_stat"
    pct: float | None = None
    if now is None:
        source = "loadavg"
        load = load_avg()
        load1 = load.get("load1")
        if load1 is not None and nproc > 0:
            pct = round(100.0 * float(load1) / nproc, 1)
    else:
        prev = _last_cpu
        if prev is None:
            time.sleep(max(0.02, float(sample_sec)))
            nxt = _read_cpu_times()
            if nxt is not None:
                prev, now = now, nxt
        if prev is not None:
            idle_d = now[0] - prev[0]
            total_d = now[1] - prev[1]
            if total_d > 1e-9:
                pct = round(100.0 * (1.0 - idle_d / total_d), 1)
        _last_cpu = now
    return {"cpu_pct": pct, "nproc": nproc, "source": source}


def disk_usage(path: str = "/") -> dict[str, Any]:
    try:
        u = shutil.disk_usage(path)
        return {
            "path": path,
            "total_gb": round(u.total / 1e9, 2),
            "used_gb": round(u.used / 1e9, 2),
            "free_gb": round(u.free / 1e9, 2),
            "used_pct": round(100 * u.used / u.total, 1),
        }
    except Exception as e:
        return {"path": path, "error": str(e)}


def mem_info() -> dict[str, Any]:
    try:
        p = Path("/proc/meminfo")
        if not p.exists():
            return {"note": "meminfo unavailable"}
        data: dict[str, int] = {}
        for ln in p.read_text(encoding="utf-8", errors="ignore").splitlines():
            parts = ln.split()
            if len(parts) >= 2:
                data[parts[0].rstrip(":")] = int(parts[1])
        total = data.get("MemTotal", 0)
        avail = data.get("MemAvailable", 0)
        return {
            "total_gb": round(total / 1e6, 2),
            "available_gb": round(avail / 1e6, 2),
            "used_pct": round(100 * (total - avail) / total, 1) if total else None,
        }
    except Exception as e:
        return {"error": str(e)}


def load_avg() -> dict[str, Any]:
    try:
        p = Path("/proc/loadavg")
        if p.exists():
            parts = p.read_text(encoding="utf-8", errors="ignore").split()
            return {
                "load1": float(parts[0]),
                "load5": float(parts[1]),
                "load15": float(parts[2]),
            }
    except Exception:
        pass
    return {}


def uptime_info() -> dict[str, Any]:
    try:
        p = Path("/proc/uptime")
        if p.exists():
            sec = float(p.read_text(encoding="utf-8", errors="ignore").split()[0])
            return {"uptime_sec": int(sec), "uptime_days": round(sec / 86400.0, 2)}
    except Exception:
        pass
    return {}


def host_metrics(disk_path: str | None = None) -> dict[str, Any]:
    path = disk_path or ("/" if os.name != "nt" else "C:\\")
    return {
        "cpu": cpu_info(),
        "memory": mem_info(),
        "disk": disk_usage(path),
        "load": load_avg(),
        "uptime": uptime_info(),
        "nproc": int(os.cpu_count() or 1),
    }
