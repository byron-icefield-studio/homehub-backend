# Stage 1: base deps（uv 依赖层，pyproject.toml + uv.lock 不变时复用缓存）
# Base stage: uv dependency layer. Only rebuilt when pyproject.toml or uv.lock changes.
FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_NO_CACHE=1

WORKDIR /app

# 仅复制依赖声明文件，充分利用层缓存
# Copy only dependency manifests to maximize layer cache reuse
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# Stage 2: app（业务层，每次部署重新 COPY 代码）
# App stage: copy source code on top of base. Fast rebuild since uv cache is reused.
FROM base AS app

WORKDIR /app
COPY app ./app

# 安装项目本身（跳过依赖，已在 base 层安装）
# Install the project itself (deps already installed in base stage)
RUN uv sync --frozen --no-dev

EXPOSE 8000
CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
