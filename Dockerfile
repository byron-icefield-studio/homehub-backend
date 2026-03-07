# Stage 1: base deps（依赖层，requirements.txt 不变时复用缓存，无需重建）
# Base stage: install pip packages. Only rebuilt when requirements.txt changes.
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Stage 2: app（业务层，每次部署重新 COPY 代码，pip 层从 base 复用）
# App stage: copy source code on top of base. Fast rebuild since pip is cached.
FROM base AS app

WORKDIR /app
COPY app ./app

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
