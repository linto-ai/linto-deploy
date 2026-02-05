"""Profile configuration model."""

from enum import Enum

from pydantic import BaseModel, Field, field_validator, model_validator


class DeploymentBackend(str, Enum):
    """Deployment backend type."""

    COMPOSE = "compose"
    SWARM = "swarm"
    K3S = "k3s"


class TLSMode(str, Enum):
    """TLS mode for deployment."""

    OFF = "off"
    MKCERT = "mkcert"
    ACME = "acme"
    CUSTOM = "custom"


class StreamingSTTVariant(str, Enum):
    """Streaming STT model variants."""

    WHISPER = "whisper"
    KALDI_FRENCH = "kaldi-french"
    NEMO_FRENCH = "nemo-french"
    NEMO_ENGLISH = "nemo-english"
    KYUTAI = "kyutai"


class GPUArchitecture(str, Enum):
    """GPU architecture for Kyutai."""

    HOPPER = "hopper"  # H100
    ADA = "ada"  # RTX 40xx
    AMPERE = "ampere"  # RTX 30xx, A100


class GPUMode(str, Enum):
    """GPU sharing mode for Kubernetes deployments."""

    NONE = "none"  # No GPU
    EXCLUSIVE = "exclusive"  # 1 GPU per pod
    TIME_SLICING = "time-slicing"  # Share GPU via time-slicing
    TIMESLICING = "timeslicing"  # Alias for time-slicing (backwards compat)


class ProfileConfig(BaseModel):
    """Configuration for a deployment profile."""

    name: str = Field(default="dev", min_length=1, max_length=32)
    domain: str = Field(default="localhost")

    # Embedded kubeconfig for cluster access
    kubeconfig: dict | None = Field(default=None)
    image_tag: str = Field(default="latest-unstable")
    # Individual service tags (overrides image_tag for specific services)
    service_tags: dict[str, str] = Field(default_factory=dict)
    tls_mode: TLSMode = Field(default=TLSMode.MKCERT)

    # Deployment backend
    backend: DeploymentBackend = Field(default=DeploymentBackend.COMPOSE)

    # GPU mode (for Kubernetes)
    gpu_mode: GPUMode = Field(default=GPUMode.NONE)

    # Service toggles
    studio_enabled: bool = Field(default=True)
    stt_enabled: bool = Field(default=True)

    # STT settings
    security_level: str = Field(default="0")

    # Live Session
    live_session_enabled: bool = Field(default=False)
    streaming_stt_variants: list[StreamingSTTVariant] = Field(default_factory=list)
    kyutai_gpu_architecture: GPUArchitecture | None = Field(default=None)
    session_transcriber_replicas: int = Field(default=2, ge=1)

    # LLM
    llm_enabled: bool = Field(default=False)
    openai_api_base: str | None = Field(default=None)
    openai_api_token: str | None = Field(default=None)
    vllm_enabled: bool = Field(default=False)

    # ACME TLS
    acme_email: str | None = Field(default=None)

    # Custom TLS certs
    custom_cert_path: str | None = Field(default=None)
    custom_key_path: str | None = Field(default=None)

    # Secrets (auto-generated if not provided)
    redis_password: str | None = Field(default=None)
    jwt_secret: str | None = Field(default=None)
    jwt_refresh_secret: str | None = Field(default=None)
    super_admin_email: str = Field(default="admin@linto.local")
    super_admin_password: str | None = Field(default=None)

    # Session secrets
    session_postgres_password: str | None = Field(default=None)
    session_crypt_key: str | None = Field(default=None)

    # LLM secrets
    llm_postgres_password: str | None = Field(default=None)
    llm_redis_password: str | None = Field(default=None)

    # K3S-specific settings
    k3s_namespace: str = Field(default="linto")
    k3s_storage_class: str | None = Field(default=None)
    k3s_install_cert_manager: bool = Field(default=False)
    k3s_tls_secret_name: str = Field(default="linto-tls")
    k3s_database_host_path: str | None = Field(default=None)
    k3s_files_host_path: str | None = Field(default=None)
    k3s_database_node_selector: dict[str, str] | None = Field(default=None)

    # GPU settings (for multi-GPU setups)
    gpu_count: int = Field(default=1, ge=1)
    gpu_slices_per_gpu: int = Field(default=4, ge=1)  # For time-slicing mode

    # K3S additional settings
    k3s_database_node_role: str | None = Field(default=None)  # Node label for database placement

    # Monitoring
    monitoring_enabled: bool = Field(default=False)  # Prometheus + Grafana stack

    # LLM additional secrets
    llm_encryption_key: str | None = Field(default=None)
    llm_admin_username: str = Field(default="admin")
    llm_admin_password: str | None = Field(default=None)

    # SMTP Configuration
    smtp_enabled: bool = Field(default=False)
    smtp_host: str | None = Field(default=None)
    smtp_port: int = Field(default=465)
    smtp_secure: bool = Field(default=True)
    smtp_require_tls: bool = Field(default=True)
    smtp_auth: str | None = Field(default=None)
    smtp_password: str | None = Field(default=None)
    smtp_no_reply_email: str | None = Field(default=None)

    # Google OIDC
    oidc_google_enabled: bool = Field(default=False)
    oidc_google_client_id: str | None = Field(default=None)
    oidc_google_client_secret: str | None = Field(default=None)

    # GitHub OIDC
    oidc_github_enabled: bool = Field(default=False)
    oidc_github_client_id: str | None = Field(default=None)
    oidc_github_client_secret: str | None = Field(default=None)

    # Native OIDC (Linagora)
    oidc_native_type: str | None = Field(default=None)  # "linagora" or "eu"
    oidc_native_client_id: str | None = Field(default=None)
    oidc_native_client_secret: str | None = Field(default=None)
    oidc_native_url: str | None = Field(default=None)
    oidc_native_scope: str = Field(default="openid,email,profile")

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Validate profile name: alphanumeric and hyphens only."""
        import re

        if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9-]*$", v):
            msg = "Profile name must be alphanumeric with optional hyphens"
            raise ValueError(msg)
        return v

    @field_validator("domain")
    @classmethod
    def validate_domain(cls, v: str) -> str:
        """Validate domain is a valid hostname or localhost."""
        import re

        if v == "localhost":
            return v
        # Simple hostname validation (RFC 952/1123 compliant)
        hostname_pattern = (
            r"^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?"
            r"(\.[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?)*$"
        )
        if not re.match(hostname_pattern, v):
            msg = "Invalid hostname format"
            raise ValueError(msg)
        return v

    @field_validator("super_admin_email")
    @classmethod
    def validate_email(cls, v: str) -> str:
        """Validate email format."""
        import re

        email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
        if not re.match(email_pattern, v):
            msg = "Invalid email format"
            raise ValueError(msg)
        return v

    @field_validator("super_admin_password")
    @classmethod
    def validate_password(cls, v: str | None) -> str | None:
        """Validate password minimum length when provided."""
        if v is not None and len(v) < 8:
            msg = "Password must be at least 8 characters"
            raise ValueError(msg)
        return v

    @model_validator(mode="after")
    def validate_profile(self) -> "ProfileConfig":
        """Validate profile configuration constraints."""
        # At least one service must be enabled
        if not self.studio_enabled and not self.stt_enabled and not self.live_session_enabled and not self.llm_enabled:
            msg = "At least one service must be enabled (Studio, STT, Live Session, or LLM)"
            raise ValueError(msg)

        # Kyutai requires GPU architecture
        if self.live_session_enabled and StreamingSTTVariant.KYUTAI in self.streaming_stt_variants:
            if self.kyutai_gpu_architecture is None:
                msg = "Kyutai streaming STT requires kyutai_gpu_architecture to be set"
                raise ValueError(msg)

        # Note: openai_api_base and openai_api_token are optional for LLM Gateway v2
        # (they're configured directly in Helm values if needed for external APIs)

        # ACME requires email
        if self.tls_mode == TLSMode.ACME and not self.acme_email:
            msg = "ACME TLS mode requires acme_email"
            raise ValueError(msg)

        # Custom TLS requires cert and key paths
        if self.tls_mode == TLSMode.CUSTOM:
            if not self.custom_cert_path or not self.custom_key_path:
                msg = "Custom TLS mode requires custom_cert_path and custom_key_path"
                raise ValueError(msg)

        # SMTP validation
        if self.smtp_enabled:
            if not self.smtp_host:
                msg = "SMTP host is required when SMTP is enabled"
                raise ValueError(msg)
            if not self.smtp_auth:
                msg = "SMTP auth user is required when SMTP is enabled"
                raise ValueError(msg)
            if not self.smtp_no_reply_email:
                msg = "No-reply email is required when SMTP is enabled"
                raise ValueError(msg)

        # Google OIDC validation
        if self.oidc_google_enabled:
            if not self.oidc_google_client_id:
                msg = "Google client ID is required when Google OIDC is enabled"
                raise ValueError(msg)
            if not self.oidc_google_client_secret:
                msg = "Google client secret is required when Google OIDC is enabled"
                raise ValueError(msg)

        # GitHub OIDC validation
        if self.oidc_github_enabled:
            if not self.oidc_github_client_id:
                msg = "GitHub client ID is required when GitHub OIDC is enabled"
                raise ValueError(msg)
            if not self.oidc_github_client_secret:
                msg = "GitHub client secret is required when GitHub OIDC is enabled"
                raise ValueError(msg)

        # Native OIDC validation
        if self.oidc_native_type:
            if self.oidc_native_type not in ["linagora", "eu"]:
                msg = "Native OIDC type must be 'linagora' or 'eu'"
                raise ValueError(msg)
            if not self.oidc_native_client_id:
                msg = "Native OIDC client ID is required when type is set"
                raise ValueError(msg)
            if not self.oidc_native_client_secret:
                msg = "Native OIDC client secret is required when type is set"
                raise ValueError(msg)
            if not self.oidc_native_url:
                msg = "Native OIDC URL is required when type is set"
                raise ValueError(msg)

        return self
