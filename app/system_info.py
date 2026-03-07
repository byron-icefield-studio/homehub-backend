from __future__ import annotations

import psutil

from .schemas import SystemStats


def collect_system_stats() -> SystemStats:
    load_raw = psutil.getloadavg() if hasattr(psutil, "getloadavg") else (0.0, 0.0, 0.0)
    memory = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    cpu_percents = psutil.cpu_percent(interval=0.2, percpu=True)
    return SystemStats(
        cpu_percent=round(sum(cpu_percents) / len(cpu_percents), 1) if cpu_percents else 0.0,
        cpu_percents=[round(value, 1) for value in cpu_percents],
        memory_percent=memory.percent,
        memory_used_bytes=memory.used,
        memory_total_bytes=memory.total,
        disk_percent=disk.percent,
        disk_used_bytes=disk.used,
        disk_total_bytes=disk.total,
        load_avg=[round(x, 2) for x in load_raw],
    )
