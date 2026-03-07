from __future__ import annotations

from pydantic import BaseModel, Field


class ServiceItem(BaseModel):
    id: str
    name: str
    icon: str | None = None
    intranet_url: str
    extranet_url: str | None = None
    open_mode: str = Field(default="auto", pattern="^(auto|internal|external)$")
    tags: list[str] = Field(default_factory=list)


class ServiceGroup(BaseModel):
    id: str
    name: str
    services: list[ServiceItem] = Field(default_factory=list)


class ServicesConfig(BaseModel):
    version: int = 1
    updated_at: str | None = None
    groups: list[ServiceGroup] = Field(default_factory=list)


class DashboardConfig(BaseModel):
    version: int = 1
    title: str = "HomeHub Dashboard"
    subtitle: str = "HomeHub 家庭服务中心"
    theme: str = "light"


class SystemStats(BaseModel):
    cpu_percent: float
    memory_percent: float
    disk_percent: float
    load_avg: list[float]


class ContainerInfo(BaseModel):
    id: str
    name: str
    image: str
    status: str
    state: str
