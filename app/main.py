from __future__ import annotations

import hashlib
import io
import mimetypes
import re
import tarfile
import threading
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen

import docker
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles

from .config_store import CONFIG_DIR, DATA_ROOT, get_dashboard, get_services, save_dashboard, save_services
from .schemas import ContainerInfo, ContainerStats, DashboardConfig, ServicesConfig
from .system_info import collect_system_stats

# 本地图标存储目录 / Local icon storage directory
ICONS_DIR = DATA_ROOT / "icons"

app = FastAPI(title="HomeHub Service API", version="0.1.0")


def _ensure_icons_dir() -> None:
    """确保图标目录存在 / Ensure icons directory exists"""
    ICONS_DIR.mkdir(parents=True, exist_ok=True)


_ensure_icons_dir()
# 挂载静态图标文件服务 / Mount static icon file serving
app.mount("/api/icons/static", StaticFiles(directory=str(ICONS_DIR)), name="icons-static")

_stats_lock = threading.Lock()
_stats_stop = threading.Event()
_stats_cache: dict[str, ContainerStats] = {}
_STATS_REFRESH_SECONDS = 3.0

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


def _docker_client() -> docker.DockerClient:
    return docker.from_env()


def _container_stats(container: docker.models.containers.Container) -> dict[str, float | int]:
    stats = container.stats(stream=False)
    cpu_stats = stats.get("cpu_stats", {})
    precpu_stats = stats.get("precpu_stats", {})
    cpu_total = cpu_stats.get("cpu_usage", {}).get("total_usage", 0)
    precpu_total = precpu_stats.get("cpu_usage", {}).get("total_usage", 0)
    system_total = cpu_stats.get("system_cpu_usage", 0)
    presystem_total = precpu_stats.get("system_cpu_usage", 0)
    online_cpus = cpu_stats.get("online_cpus") or len(cpu_stats.get("cpu_usage", {}).get("percpu_usage") or []) or 1

    cpu_percent = 0.0
    cpu_delta = cpu_total - precpu_total
    system_delta = system_total - presystem_total
    if cpu_delta > 0 and system_delta > 0:
        cpu_percent = round((cpu_delta / system_delta) * online_cpus * 100, 1)

    memory = stats.get("memory_stats", {})
    usage = int(memory.get("usage") or 0)
    cache = int((memory.get("stats") or {}).get("cache") or 0)
    limit = int(memory.get("limit") or 0)
    working_set = max(usage - cache, 0)
    memory_percent = round((working_set / limit) * 100, 1) if limit > 0 else 0.0

    return {
        "cpu_percent": cpu_percent,
        "memory_usage_bytes": working_set,
        "memory_limit_bytes": limit,
        "memory_percent": memory_percent,
    }


def _refresh_container_stats_cache() -> None:
    while not _stats_stop.is_set():
        next_cache: dict[str, ContainerStats] = {}
        try:
            client = _docker_client()
            for c in client.containers.list(all=True):
                name = (c.name or "").lstrip("/")
                if c.status != "running":
                    next_cache[name] = ContainerStats(name=name)
                    continue
                stats = _container_stats(c)
                next_cache[name] = ContainerStats(
                    name=name,
                    cpu_percent=stats["cpu_percent"],
                    memory_usage_bytes=stats["memory_usage_bytes"],
                    memory_limit_bytes=stats["memory_limit_bytes"],
                    memory_percent=stats["memory_percent"],
                )
        except Exception:  # noqa: BLE001
            pass

        with _stats_lock:
            _stats_cache.clear()
            _stats_cache.update(next_cache)

        _stats_stop.wait(_STATS_REFRESH_SECONDS)


@app.on_event("startup")
def startup_event() -> None:
    _stats_stop.clear()
    worker = threading.Thread(target=_refresh_container_stats_cache, name="docker-stats-cache", daemon=True)
    worker.start()
    app.state.docker_stats_worker = worker


@app.on_event("shutdown")
def shutdown_event() -> None:
    _stats_stop.set()


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


@app.get("/api/docker/containers/stats", response_model=list[ContainerStats])
def list_container_stats() -> list[ContainerStats]:
    with _stats_lock:
        return list(_stats_cache.values())


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


def _save_icon_bytes(data: bytes, mime_type: str) -> str:
    """将图标字节保存到本地，返回静态访问路径
    Save icon bytes to local storage, return static access path"""
    _ensure_icons_dir()
    # 使用内容哈希作为文件名，避免重复存储 / Use content hash as filename to avoid duplicates
    content_hash = hashlib.sha256(data).hexdigest()[:16]
    ext = mimetypes.guess_extension(mime_type.split(";")[0].strip()) or ".ico"
    # 某些 MIME 映射到奇怪扩展名，做修正 / Fix some odd extension mappings
    if ext in {".jpe", ".jpeg"}:
        ext = ".jpg"
    filename = f"{content_hash}{ext}"
    dest = ICONS_DIR / filename
    if not dest.exists():
        dest.write_bytes(data)
    return f"/api/icons/static/{filename}"


@app.post("/api/icons/fetch")
def fetch_icon_to_local(payload: dict) -> dict:
    """下载远程图标 URL 到本地存储，返回本地路径
    Download a remote icon URL to local storage, return local path"""
    url = payload.get("url", "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="url is required")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise HTTPException(status_code=400, detail="url must start with http:// or https://")

    try:
        req = Request(url, headers={"User-Agent": "HomeHub/0.1 (+icon-fetch)"})
        with urlopen(req, timeout=10) as resp:
            data = resp.read(512 * 1024)  # 最多读取 512KB / Read up to 512KB
            content_type = resp.headers.get("Content-Type", "image/x-icon")
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"failed to fetch icon: {exc}") from exc

    local_path = _save_icon_bytes(data, content_type)
    return {"path": local_path}


@app.post("/api/icons/upload")
async def upload_icon(file: UploadFile = File(...)) -> dict:
    """接收上传的图标文件并保存到本地，返回本地路径
    Accept uploaded icon file and save to local storage, return local path"""
    # 限制只接受图片类型 / Only accept image types
    content_type = file.content_type or "application/octet-stream"
    if not content_type.startswith("image/"):
        raise HTTPException(status_code=400, detail="only image files are accepted")

    data = await file.read(512 * 1024)  # 最多读取 512KB / Read up to 512KB
    if not data:
        raise HTTPException(status_code=400, detail="empty file")

    local_path = _save_icon_bytes(data, content_type)
    return {"path": local_path}


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
