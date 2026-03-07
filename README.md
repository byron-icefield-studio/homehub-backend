# HomeHub Backend

GitHub: https://github.com/byron-icefield-studio/HomeHub-backend

HomeHub 后端项目（FastAPI），负责：

- 配置读写（JSON 文件持久化）
- 系统状态采集（CPU/内存/磁盘/负载）
- Docker 容器列表、日志、资源占用缓存接口
- 图标候选抓取
- 配置导出

## Tech Stack

- FastAPI
- Pydantic v2
- psutil
- docker SDK for Python

## Data Persistence

默认持久化目录：

- `/data/config/services.json`
- `/data/config/dashboard.json`

通过挂载数据目录实现“容器重建后恢复配置”。

环境变量：

- `DATA_ROOT`（默认 `/data`）

## API Summary

- `GET /healthz`
- `GET /api/system/stats`
- `GET /api/docker/containers`
- `GET /api/docker/containers/stats`
- `GET /api/docker/containers/{name}/logs`
- `GET /api/config/services`
- `PUT /api/config/services`
- `GET /api/config/dashboard`
- `PUT /api/config/dashboard`
- `GET /api/icons/suggestions?url=...`
- `GET /api/config/export`
- `GET /api/config/raw`
- `POST /api/config/raw`

## Docker Stats Design

`/api/docker/containers/stats` 使用后台线程做缓存刷新（默认每 3 秒），接口直接返回缓存，避免每次请求实时采样导致响应慢。

## Run (Dev)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

## Deployment

## 1) Docker build

```bash
docker build -t homehub-backend .
```

## 2) Docker run (example)

```bash
docker run -d \
  --name homehub-backend \
  -e DATA_ROOT=/data \
  -v /path/to/data:/data \
  --restart unless-stopped \
  homehub-backend
```

如需 Docker 容器状态能力，后端必须可访问 Docker API。推荐通过 `docker-socket-proxy` 暴露最小权限接口，而不是直接裸挂 Docker socket。

## 3) Nginx reverse proxy (example)

将 nginx 的 `/api/` 反代到该服务，例如：

```nginx
location /api/ {
    proxy_pass http://homehub-backend:8000;
    proxy_http_version 1.1;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

## Config Recovery

只要数据目录（`/data/config`）持续挂载，容器重启或重建后会自动读取已有配置恢复。

## Related Repo

- Frontend: https://github.com/byron-icefield-studio/HomeHub-frontend
