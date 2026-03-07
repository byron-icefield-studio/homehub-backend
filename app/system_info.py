from __future__ import annotations

import psutil

from .schemas import SystemStats


def collect_system_stats() -> SystemStats:
    load_raw = psutil.getloadavg() if hasattr(psutil, "getloadavg") else (0.0, 0.0, 0.0)
    return SystemStats(
        cpu_percent=psutil.cpu_percent(interval=0.2),
        memory_percent=psutil.virtual_memory().percent,
        disk_percent=psutil.disk_usage("/").percent,
        load_avg=[round(x, 2) for x in load_raw],
    )
