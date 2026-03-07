from __future__ import annotations

import psutil

from .schemas import SystemStats


def collect_system_stats() -> SystemStats:
    load_raw = psutil.getloadavg() if hasattr(psutil, "getloadavg") else (0.0, 0.0, 0.0)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    return SystemStats(
        cpu_percent=psutil.cpu_percent(interval=0.2),
        memory_percent=memory.percent,
        memory_used_bytes=memory.used,
        memory_total_bytes=memory.total,
        disk_percent=disk.percent,
        disk_used_bytes=disk.used,
        disk_total_bytes=disk.total,
        load_avg=[round(x, 2) for x in load_raw],
    )
