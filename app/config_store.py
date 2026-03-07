from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .schemas import DashboardConfig, ServicesConfig

DATA_ROOT = Path(os.getenv("DATA_ROOT", "/data"))
CONFIG_DIR = DATA_ROOT / "config"

SERVICES_PATH = CONFIG_DIR / "services.json"
DASHBOARD_PATH = CONFIG_DIR / "dashboard.json"


DEFAULT_SERVICES = ServicesConfig(
    groups=[
        {
            "id": "default",
            "name": "默认分组",
            "services": [],
        }
    ]
)

DEFAULT_DASHBOARD = DashboardConfig()


def _ensure_dirs() -> None:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def _atomic_write_json(path: Path, payload: dict) -> None:
    _ensure_dirs()
    fd, temp_path = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)


def _read_or_init(path: Path, default_payload: dict) -> dict:
    _ensure_dirs()
    if not path.exists():
        _atomic_write_json(path, default_payload)
        return default_payload

    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def get_services() -> ServicesConfig:
    raw = _read_or_init(SERVICES_PATH, DEFAULT_SERVICES.model_dump())
    return ServicesConfig.model_validate(raw)


def save_services(config: ServicesConfig) -> ServicesConfig:
    payload = config.model_dump()
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    _atomic_write_json(SERVICES_PATH, payload)
    return ServicesConfig.model_validate(payload)


def get_dashboard() -> DashboardConfig:
    raw = _read_or_init(DASHBOARD_PATH, DEFAULT_DASHBOARD.model_dump())
    docker_urls = raw.get("docker_urls", {})
    if isinstance(docker_urls, dict):
        migrated = {}
        changed = False
        for key, value in docker_urls.items():
            if isinstance(value, str):
                migrated[key] = {
                    "name": "",
                    "intranet_url": value,
                    "extranet_url": "",
                    "icon": "",
                }
                changed = True
            elif isinstance(value, dict):
                migrated[key] = {
                    "name": str(value.get("name", "")),
                    "intranet_url": str(value.get("intranet_url", "")),
                    "extranet_url": str(value.get("extranet_url", "")),
                    "icon": str(value.get("icon", "")),
                }
            else:
                changed = True
        if changed:
            raw["docker_urls"] = migrated
    return DashboardConfig.model_validate(raw)


def save_dashboard(config: DashboardConfig) -> DashboardConfig:
    payload = config.model_dump()
    _atomic_write_json(DASHBOARD_PATH, payload)
    return DashboardConfig.model_validate(payload)
