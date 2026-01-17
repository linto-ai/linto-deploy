"""Service definition models."""

from typing import Literal

from pydantic import BaseModel, Field


class VolumeMount(BaseModel):
    """Volume mount configuration."""

    source: str
    target: str
    read_only: bool = Field(default=False)


class HealthcheckConfig(BaseModel):
    """Health check configuration."""

    test: list[str]
    interval: str = Field(default="30s")
    timeout: str = Field(default="10s")
    retries: int = Field(default=3)
    start_period: str = Field(default="30s")


class RestartPolicy(BaseModel):
    """Restart policy for Swarm deploy."""

    condition: str = Field(default="on-failure")
    delay: str | None = Field(default=None)
    max_attempts: int | None = Field(default=None)
    window: str | None = Field(default=None)


class ResourceSpec(BaseModel):
    """Resource limits/reservations for Swarm deploy."""

    cpus: str | None = Field(default=None)
    memory: str | None = Field(default=None)


class Resources(BaseModel):
    """Resource configuration for Swarm deploy."""

    limits: ResourceSpec | None = Field(default=None)
    reservations: ResourceSpec | None = Field(default=None)


class DeployConfig(BaseModel):
    """Swarm deploy configuration."""

    mode: str = Field(default="replicated")
    replicas: int = Field(default=1)
    placement_constraints: list[str] = Field(default_factory=list)
    resources: Resources | None = Field(default=None)
    labels: list[str] = Field(default_factory=list)
    restart_policy: RestartPolicy | None = Field(default=None)


class ServiceDefinition(BaseModel):
    """Definition of a Docker service."""

    name: str
    category: Literal["studio", "stt", "infra", "live", "llm"]
    image: str
    depends_on: list[str] = Field(default_factory=list)
    networks: list[str] = Field(default_factory=list)
    volumes: list[VolumeMount] = Field(default_factory=list)
    environment: dict[str, str] = Field(default_factory=dict)
    ports: list[str] = Field(default_factory=list)
    expose: list[str] = Field(default_factory=list)  # Internal ports for Swarm
    command: list[str] | str | None = Field(default=None)
    traefik_endpoint: str | None = Field(default=None)
    traefik_strip_prefix: bool = Field(default=False)
    traefik_server_port: int = Field(default=80)
    healthcheck: HealthcheckConfig | None = Field(default=None)
    restart: str = Field(default="unless-stopped")
    deploy: DeployConfig | None = Field(default=None)
    gpu_required: bool = Field(default=False)
    extra_labels: list[str] = Field(default_factory=list)
