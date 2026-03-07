from __future__ import annotations

import io
import re
import tarfile
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

import docker
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from .config_store import CONFIG_DIR, get_dashboard, get_services, save_dashboard, save_services
from .schemas import ContainerInfo, DashboardConfig, ServicesConfig
from .system_info import collect_system_stats

app = FastAPI(title="HomeHub Service API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _docker_client() -> docker.DockerClient:
    return docker.from_env()


def _discover_icons(target_url: str) -> list[str]:
    parsed = urlparse(target_url)
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(status_code=400, detail="url must start with http:// or https://")

    request = Request(
        target_url,
        headers={
            "User-Agent": "HomeHub/0.1 (+icon-discovery)",
        },
    )
    with urlopen(request, timeout=6) as response:
        html = response.read(200_000).decode("utf-8", errors="ignore")
        base_url = response.geturl()

    candidates = []
    pattern = re.compile(
        r"""<link[^>]+rel=["'][^"']*(?:icon|apple-touch-icon)[^"']*["'][^>]+href=["']([^"']+)["']""",
        re.IGNORECASE,
    )
    for href in pattern.findall(html):
        candidates.append(urljoin(base_url, href))

    root = f"{parsed.scheme}://{parsed.netloc}"
    candidates.extend(
        [
            urljoin(base_url, "/favicon.ico"),
            urljoin(base_url, "/apple-touch-icon.png"),
            urljoin(root, "/favicon.ico"),
        ]
    )

    seen: set[str] = set()
    deduped = []
    for item in candidates:
        if item and item not in seen:
            seen.add(item)
            deduped.append(item)
    return deduped[:8]


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True}


@app.get("/api/config/services", response_model=ServicesConfig)
def get_services_config() -> ServicesConfig:
    return get_services()


@app.put("/api/config/services", response_model=ServicesConfig)
def put_services_config(payload: ServicesConfig) -> ServicesConfig:
    return save_services(payload)


@app.get("/api/config/dashboard", response_model=DashboardConfig)
def get_dashboard_config() -> DashboardConfig:
    return get_dashboard()


@app.put("/api/config/dashboard", response_model=DashboardConfig)
def put_dashboard_config(payload: DashboardConfig) -> DashboardConfig:
    return save_dashboard(payload)


@app.get("/api/system/stats")
def get_system_stats() -> dict:
    return collect_system_stats().model_dump()


@app.get("/api/docker/containers", response_model=list[ContainerInfo])
def list_containers() -> list[ContainerInfo]:
    try:
        client = _docker_client()
        items = []
        for c in client.containers.list(all=True):
            items.append(
                ContainerInfo(
                    id=c.short_id,
                    name=(c.name or "").lstrip("/"),
                    image=(c.image.tags[0] if c.image.tags else "<none>"),
                    status=c.status,
                    state=c.attrs.get("State", {}).get("Status", c.status),
                )
            )
        return items
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"docker query failed: {exc}") from exc


@app.get("/api/docker/containers/{name}/logs")
def container_logs(name: str, tail: int = 200) -> dict:
    try:
        client = _docker_client()
        container = client.containers.get(name)
        logs = container.logs(tail=tail).decode("utf-8", errors="replace")
        return {"name": name, "tail": tail, "logs": logs}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=404, detail=f"container not found or logs unavailable: {exc}") from exc


@app.get("/api/icons/suggestions")
def icon_suggestions(url: str) -> dict:
    try:
        return {"icons": _discover_icons(url)}
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=f"icon discovery failed: {exc}") from exc


@app.get("/api/config/export")
def export_config() -> StreamingResponse:
    if not CONFIG_DIR.exists():
        raise HTTPException(status_code=404, detail="config directory not found")

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for p in CONFIG_DIR.rglob("*"):
            if p.is_file():
                tar.add(p, arcname=str(Path("config") / p.relative_to(CONFIG_DIR)))
    buf.seek(0)

    headers = {"Content-Disposition": "attachment; filename=HomeHub-config.tar.gz"}
    return StreamingResponse(buf, media_type="application/gzip", headers=headers)


@app.get("/api/config/raw")
def raw_config() -> dict:
    return {
        "dashboard": get_dashboard().model_dump(),
        "services": get_services().model_dump(),
    }


@app.post("/api/config/raw")
def save_raw_config(payload: dict) -> dict:
    dashboard = DashboardConfig.model_validate(payload.get("dashboard", {}))
    services = ServicesConfig.model_validate(payload.get("services", {}))

    saved_dashboard = save_dashboard(dashboard)
    saved_services = save_services(services)

    return {
        "dashboard": saved_dashboard.model_dump(),
        "services": saved_services.model_dump(),
    }
