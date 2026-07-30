"""Pydantic models for the Gateway API."""

from __future__ import annotations

import enum
from datetime import datetime

from pydantic import BaseModel, Field


class SandboxStatus(str, enum.Enum):
    creating = "creating"
    running = "running"
    terminated = "terminated"


class ResourceProfile(BaseModel):
    cpu_request: str = "1"
    memory_request: str = "2Gi"
    cpu_limit: str = "4"
    memory_limit: str = "8Gi"
    ephemeral_storage: str = "20Gi"


class SandboxEnvironment(BaseModel):
    id: str
    name: str
    container_image: str
    resource_profile: ResourceProfile = Field(default_factory=ResourceProfile)
    max_ttl_seconds: int = 3600


class CreateSandboxRequest(BaseModel):
    environment_id: str = "default"
    # Optional: use as both sandbox id and relay SESSION_ID so session↔sandbox are linked
    id: str | None = Field(default=None, min_length=4, max_length=64)


class SandboxResponse(BaseModel):
    id: str
    user_id: str
    environment_id: str | None
    status: SandboxStatus
    pod_name: str | None = None
    namespace: str | None = None
    pod_phase: str | None = None
    created_at: datetime
    expires_at: datetime | None = None
    terminated_at: datetime | None = None


class SandboxListResponse(BaseModel):
    sandboxes: list[SandboxResponse]
    total: int


class SandboxFileInfo(BaseModel):
    path: str
    size: int
    mtime: float


class SandboxFileListResponse(BaseModel):
    files: list[SandboxFileInfo]
    prefix: str
    total: int


class SandboxUploadResponse(BaseModel):
    uploaded: list[str]
    dest: str
    count: int
