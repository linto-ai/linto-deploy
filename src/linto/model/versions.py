"""Version configuration model for LinTO platform."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class ServiceVersion(BaseModel):
    """Service version configuration."""

    image: str = ""
    tag: str = ""  # Empty string means "use platform_version"
    repo: str = ""

    class Config:
        """Pydantic config."""

        extra = "allow"


class LintoVersions(BaseModel):
    """LinTO services versions."""

    studio_api: ServiceVersion = Field(default_factory=ServiceVersion, alias="studio-api")
    studio_frontend: ServiceVersion = Field(default_factory=ServiceVersion, alias="studio-frontend")
    studio_websocket: ServiceVersion = Field(default_factory=ServiceVersion, alias="studio-websocket")
    linto_api_gateway: ServiceVersion = Field(default_factory=ServiceVersion, alias="linto-api-gateway")
    linto_transcription_service: ServiceVersion = Field(
        default_factory=ServiceVersion, alias="linto-transcription-service"
    )
    linto_stt_whisper: ServiceVersion = Field(default_factory=ServiceVersion, alias="linto-stt-whisper")
    linto_diarization_pyannote: ServiceVersion = Field(
        default_factory=ServiceVersion, alias="linto-diarization-pyannote"
    )
    linto_stt_kaldi: ServiceVersion = Field(default_factory=ServiceVersion, alias="linto-stt-kaldi")
    linto_stt_nemo: ServiceVersion = Field(default_factory=ServiceVersion, alias="linto-stt-nemo")
    kyutai_moshi_stt_server_cuda: ServiceVersion = Field(
        default_factory=ServiceVersion, alias="kyutai-moshi-stt-server-cuda"
    )
    llm_gateway: ServiceVersion = Field(default_factory=ServiceVersion, alias="llm-gateway")
    llm_gateway_frontend: ServiceVersion = Field(default_factory=ServiceVersion, alias="llm-gateway-frontend")
    studio_plugins_migration: ServiceVersion = Field(
        default_factory=ServiceVersion, alias="studio-plugins-migration"
    )
    studio_plugins_sessionapi: ServiceVersion = Field(
        default_factory=ServiceVersion, alias="studio-plugins-sessionapi"
    )
    studio_plugins_scheduler: ServiceVersion = Field(
        default_factory=ServiceVersion, alias="studio-plugins-scheduler"
    )
    studio_plugins_transcriber: ServiceVersion = Field(
        default_factory=ServiceVersion, alias="studio-plugins-transcriber"
    )

    class Config:
        """Pydantic config."""

        populate_by_name = True
        extra = "allow"


class DatabaseVersions(BaseModel):
    """Database versions."""

    # Studio
    studio_mongo: ServiceVersion = Field(
        default_factory=lambda: ServiceVersion(image="mongo", tag="6.0.2"),
        alias="studio-mongo",
    )
    # STT
    stt_mongo: ServiceVersion = Field(
        default_factory=lambda: ServiceVersion(image="mongo", tag="6.0.2"),
        alias="stt-mongo",
    )
    stt_redis: ServiceVersion = Field(
        default_factory=lambda: ServiceVersion(image="redis/redis-stack-server", tag="7.4.0-v8"),
        alias="stt-redis",
    )
    # Live
    live_postgres: ServiceVersion = Field(
        default_factory=lambda: ServiceVersion(image="postgres", tag="15-alpine"),
        alias="live-postgres",
    )
    live_mosquitto: ServiceVersion = Field(
        default_factory=lambda: ServiceVersion(image="eclipse-mosquitto", tag="2"),
        alias="live-mosquitto",
    )
    # LLM
    llm_postgres: ServiceVersion = Field(
        default_factory=lambda: ServiceVersion(image="postgres", tag="15-alpine"),
        alias="llm-postgres",
    )
    llm_redis: ServiceVersion = Field(
        default_factory=lambda: ServiceVersion(image="redis/redis-stack-server", tag="7.4.0-v8"),
        alias="llm-redis",
    )

    class Config:
        """Pydantic config."""

        populate_by_name = True
        extra = "allow"


class LLMVersions(BaseModel):
    """LLM service versions."""

    vllm_openai: ServiceVersion = Field(
        default_factory=lambda: ServiceVersion(image="vllm/vllm-openai", tag="latest"),
        alias="vllm-openai",
    )

    class Config:
        """Pydantic config."""

        populate_by_name = True
        extra = "allow"


class VersionsConfig(BaseModel):
    """Complete versions configuration."""

    platform_version: str = Field(default="latest")
    linto: LintoVersions = Field(default_factory=LintoVersions)
    databases: DatabaseVersions = Field(default_factory=DatabaseVersions)
    llm: LLMVersions = Field(default_factory=LLMVersions)

    class Config:
        """Pydantic config."""

        extra = "allow"

    def get_linto_tag(self, image_name: str) -> str:
        """Get version tag for a LinTO image.

        Args:
            image_name: Image name (e.g., 'studio-api', 'linto-stt-whisper')

        Returns:
            Version tag, or platform_version if not specified
        """
        # Convert image-name to attribute name (studio-api -> studio_api)
        attr_name = image_name.replace("-", "_")
        if hasattr(self.linto, attr_name):
            service = getattr(self.linto, attr_name)
            if isinstance(service, ServiceVersion) and service.tag:
                return service.tag
        return self.platform_version

    def get_database_tag(self, image_name: str) -> str:
        """Get version tag for a database image.

        Args:
            image_name: Image name (e.g., 'mongo', 'postgres')

        Returns:
            Version tag
        """
        attr_name = image_name.replace("-", "_")
        if hasattr(self.databases, attr_name):
            service = getattr(self.databases, attr_name)
            if isinstance(service, ServiceVersion) and service.tag:
                return service.tag
        return "latest"

    def get_llm_tag(self, image_name: str) -> str:
        """Get version tag for an LLM service image.

        Args:
            image_name: Image name (e.g., 'vllm-openai')

        Returns:
            Version tag
        """
        attr_name = image_name.replace("-", "_")
        if hasattr(self.llm, attr_name):
            service = getattr(self.llm, attr_name)
            if isinstance(service, ServiceVersion) and service.tag:
                return service.tag
        return "latest"

    @classmethod
    def from_file(cls, path: Path) -> "VersionsConfig":
        """Load versions from a YAML file.

        Args:
            path: Path to versions YAML file

        Returns:
            VersionsConfig instance
        """
        with path.open() as f:
            data = yaml.safe_load(f)

        if not data:
            return cls()

        # Handle the new format where each service has image/tag/repo
        # Convert to the expected format
        return cls.model_validate(data)

    @classmethod
    def from_default_tag(cls, tag: str) -> "VersionsConfig":
        """Create versions config with a default tag for all LinTO images.

        Args:
            tag: Default tag to use (e.g., 'latest', 'platform.2026.01')

        Returns:
            VersionsConfig with platform_version set
        """
        return cls(platform_version=tag)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary with original key names.

        Returns:
            Dictionary representation with hyphenated keys
        """
        return {
            "platform_version": self.platform_version,
            "linto": {
                "studio-api": self.get_linto_tag("studio-api"),
                "studio-frontend": self.get_linto_tag("studio-frontend"),
                "studio-websocket": self.get_linto_tag("studio-websocket"),
                "linto-api-gateway": self.get_linto_tag("linto-api-gateway"),
                "linto-transcription-service": self.get_linto_tag("linto-transcription-service"),
                "linto-stt-whisper": self.get_linto_tag("linto-stt-whisper"),
                "linto-diarization-pyannote": self.get_linto_tag("linto-diarization-pyannote"),
                "linto-stt-kaldi": self.get_linto_tag("linto-stt-kaldi"),
                "linto-stt-nemo": self.get_linto_tag("linto-stt-nemo"),
                "kyutai-moshi-stt-server-cuda": self.get_linto_tag("kyutai-moshi-stt-server-cuda"),
                "llm-gateway": self.get_linto_tag("llm-gateway"),
                "llm-gateway-frontend": self.get_linto_tag("llm-gateway-frontend"),
                "studio-plugins-migration": self.get_linto_tag("studio-plugins-migration"),
                "studio-plugins-sessionapi": self.get_linto_tag("studio-plugins-sessionapi"),
                "studio-plugins-scheduler": self.get_linto_tag("studio-plugins-scheduler"),
                "studio-plugins-transcriber": self.get_linto_tag("studio-plugins-transcriber"),
            },
            "databases": {
                "studio-mongo": self.databases.studio_mongo.tag,
                "stt-mongo": self.databases.stt_mongo.tag,
                "stt-redis": self.databases.stt_redis.tag,
                "live-postgres": self.databases.live_postgres.tag,
                "live-mosquitto": self.databases.live_mosquitto.tag,
                "llm-postgres": self.databases.llm_postgres.tag,
                "llm-redis": self.databases.llm_redis.tag,
            },
            "llm": {
                "vllm-openai": self.llm.vllm_openai.tag,
            },
        }
