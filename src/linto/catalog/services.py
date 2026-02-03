"""Service definitions catalog."""

from linto.model.profile import GPUArchitecture, StreamingSTTVariant
from linto.model.service import (
    DeployConfig,
    HealthcheckConfig,
    RestartPolicy,
    ServiceDefinition,
    VolumeMount,
)

# Network definitions for Compose
NETWORKS = {
    "linto": {"driver": "bridge"},
    "net_studio": {"driver": "bridge"},
    "net_stt_services": {"driver": "bridge"},
    "task_broker_services": {"driver": "bridge"},
}

STUDIO_NETWORKS = {
    "net_studio": {"driver": "bridge"},
}

STT_NETWORKS = {
    "net_stt_services": {"driver": "bridge"},
    "task_broker_services": {"driver": "bridge"},
}

SESSION_NETWORKS = {
    "session_network": {"driver": "bridge"},
}

LLM_NETWORKS = {
    "net_llm_services": {"driver": "bridge"},
}


def get_networks_for_swarm() -> dict:
    """Return networks with overlay driver for Swarm mode."""
    return {
        "linto": {"driver": "overlay", "external": True},
        "net_studio": {"driver": "overlay"},
        "session_network": {"driver": "overlay"},
        "net_stt_services": {"driver": "overlay"},
        "net_llm_services": {"driver": "overlay"},
        "task_broker_services": {"driver": "overlay"},
    }


# ============================================================================
# Infrastructure Services
# ============================================================================


def _api_gateway_service(image_tag: str) -> ServiceDefinition:
    """Create API Gateway service definition for STT routing.

    Note: This service requires access to Docker socket for service discovery.
    In Swarm mode, it should run on manager nodes only.
    """
    return ServiceDefinition(
        name="api-gateway",
        category="stt",
        image=f"lintoai/linto-api-gateway:{image_tag}",
        networks=["linto", "net_stt_services"],
        traefik_endpoint="/gateway",
        traefik_strip_prefix=True,
        volumes=[
            VolumeMount(
                source="/var/run/docker.sock",
                target="/var/run/docker.sock",
                read_only=True,
            ),
        ],
        environment={
            "COMPONENT": "ServiceWatcher,WebServer",
            "DEBUG": "saas-api-gateway*",
        },
        # No placement constraints - they're only used in Swarm mode
        # and will be added by the Swarm backend when needed
    )


def _traefik_service(domain: str, tls_mode: str) -> ServiceDefinition:
    """Create Traefik service definition."""
    volumes = [
        VolumeMount(
            source="/var/run/docker.sock",
            target="/var/run/docker.sock",
            read_only=True,
        ),
    ]

    command = [
        "--api.insecure=true",
        "--providers.docker=true",
        "--providers.docker.exposedbydefault=false",
        "--entrypoints.web.address=:80",
        "--entrypoints.websecure.address=:443",
        "--entrypoints.rtmp.address=:1935/tcp",
        "--entrypoints.srt.address=:8889/udp",
    ]

    if tls_mode == "mkcert":
        command.extend(
            [
                "--providers.file.directory=/etc/traefik/dynamic",
                "--providers.file.watch=true",
            ]
        )
        volumes.append(
            VolumeMount(
                source="./.linto/tls/certs",
                target="/certs",
                read_only=True,
            )
        )
        volumes.append(
            VolumeMount(
                source="./.linto/traefik/dynamic",
                target="/etc/traefik/dynamic",
                read_only=True,
            )
        )
    elif tls_mode == "acme":
        command.extend(
            [
                "--certificatesresolvers.leresolver.acme.httpchallenge=true",
                "--certificatesresolvers.leresolver.acme.httpchallenge.entrypoint=web",
                "--certificatesresolvers.leresolver.acme.storage=/acme.json",
            ]
        )
        volumes.append(
            VolumeMount(
                source="./.linto/tls/acme.json",
                target="/acme.json",
                read_only=False,
            )
        )
    elif tls_mode == "custom":
        command.extend(
            [
                "--providers.file.directory=/etc/traefik/dynamic",
                "--providers.file.watch=true",
            ]
        )
        volumes.append(
            VolumeMount(
                source="./.linto/tls/certs",
                target="/certs",
                read_only=True,
            )
        )
        volumes.append(
            VolumeMount(
                source="./.linto/traefik/dynamic",
                target="/etc/traefik/dynamic",
                read_only=True,
            )
        )

    return ServiceDefinition(
        name="traefik",
        category="infra",
        image="traefik:2.9.1",
        ports=["80:80", "443:443", "8080:8080", "1935:1935", "8889:8889/udp"],
        networks=["linto"],
        volumes=volumes,
        command=command,
        healthcheck=HealthcheckConfig(
            test=["CMD", "traefik", "healthcheck", "--ping"],
            interval="10s",
            timeout="5s",
            retries=3,
            start_period="10s",
        ),
    )


# ============================================================================
# Studio Services
# ============================================================================


def _studio_mongodb_service() -> ServiceDefinition:
    """Create Studio MongoDB service definition."""
    return ServiceDefinition(
        name="studio-mongodb",
        category="studio",
        image="mongo:6.0.2",
        networks=["net_studio"],
        volumes=[
            VolumeMount(source="studio_mongodb_data", target="/data/db"),
        ],
        healthcheck=HealthcheckConfig(
            test=["CMD", "mongosh", "--eval", "db.adminCommand('ping')"],
            interval="30s",
            timeout="10s",
            retries=3,
            start_period="30s",
        ),
    )


def _studio_api_service(
    domain: str,
    image_tag: str,
    jwt_secret: str,
    jwt_refresh_secret: str,
    super_admin_email: str,
    super_admin_password: str,
    live_session_enabled: bool = False,
    llm_enabled: bool = False,
    stt_enabled: bool = False,
) -> ServiceDefinition:
    """Create Studio API service definition."""
    # Build COMPONENTS based on enabled features
    components = ["WebServer", "MongoMigration"]
    if live_session_enabled:
        components.extend(["BrokerClient", "IoHandler"])

    networks = ["linto", "net_studio"]
    if live_session_enabled:
        networks.append("session_network")

    environment = {
        "DB_HOST": "studio-mongodb",
        "DB_PORT": "27017",
        "DB_NAME": "conversations",
        "DB_REQUIRE_LOGIN": "false",
        "CM_JWT_SECRET": jwt_secret,
        "CM_REFRESH_SECRET": jwt_refresh_secret,
        "JWT_ALGORITHM": "HS256",
        "SUPER_ADMIN_EMAIL": super_admin_email,
        "SUPER_ADMIN_PWD": super_admin_password,
        "CORS_API_WHITELIST": f"https://{domain}",
        "CORS_ENABLED": "true",
        "WEBSERVER_HTTP_PORT": "80",
        "NODE_ENV": "production",
        "COMPONENTS": ",".join(components),
        "AXIOS_SIZE_FILE_MAX": "1000000000",
        "EXPRESS_SIZE_FILE_MAX": "1gb",
        "MAX_SUBTITLE_VERSION": "5",
        "DISABLE_DEFAULT_ORGANIZATION_CREATION": "false",
        "ORGANIZATION_DEFAULT_PERMISSIONS": "upload,summary,session",
        "LOCAL_AUTH_ENABLED": "true",
    }

    # Add STT gateway connection
    if stt_enabled:
        environment["GATEWAY_SERVICES"] = "http://api-gateway"

    # Add LLM gateway connection
    if llm_enabled:
        environment["LLM_GATEWAY_SERVICES"] = "http://llm-gateway-api"
        environment["LLM_GATEWAY_SERVICES_WS"] = "ws://llm-gateway-api/ws/results"

    # Add live session connection
    if live_session_enabled:
        environment.update(
            {
                "BROKER_HOST": "session-broker",
                "BROKER_PORT": "1883",
                "BROKER_PROTOCOL": "mqtt",
                "BROKER_KEEPALIVE": "60",
                "SESSION_API_ENDPOINT": "http://session-api/v1",
            }
        )

    return ServiceDefinition(
        name="studio-api",
        category="studio",
        image=f"lintoai/studio-api:{image_tag}",
        depends_on=["studio-mongodb"],
        networks=networks,
        traefik_endpoint="/cm-api",
        traefik_strip_prefix=True,
        environment=environment,
        healthcheck=HealthcheckConfig(
            test=[
                "CMD",
                "wget",
                "--quiet",
                "--tries=1",
                "--spider",
                "http://localhost:80/healthcheck",
            ],
            interval="30s",
            timeout="10s",
            retries=3,
            start_period="60s",
        ),
    )


def _studio_frontend_service(
    domain: str,
    image_tag: str,
) -> ServiceDefinition:
    """Create Studio Frontend service definition."""
    return ServiceDefinition(
        name="studio-frontend",
        category="studio",
        image=f"lintoai/studio-frontend:{image_tag}",
        depends_on=["studio-api"],
        networks=["linto", "net_studio"],
        traefik_endpoint="/",
        traefik_strip_prefix=False,
        environment={
            "VUE_APP_CM_API": f"https://{domain}/cm-api",
            "VUE_APP_WS_URL": f"wss://{domain}/ws",
        },
    )


def _studio_websocket_service(
    domain: str,
    image_tag: str,
    jwt_secret: str,
) -> ServiceDefinition:
    """Create Studio WebSocket service definition."""
    return ServiceDefinition(
        name="studio-websocket",
        category="studio",
        image=f"lintoai/studio-websocket:{image_tag}",
        depends_on=["studio-api"],
        networks=["linto", "net_studio"],
        traefik_endpoint="/ws",
        traefik_strip_prefix=True,
        environment={
            "CM_API_URL": "http://studio-api:80",
            "CM_JWT_SECRET": jwt_secret,
            "NODE_ENV": "production",
        },
    )


# ============================================================================
# STT Services (File-based transcription)
# ============================================================================


def _stt_mongo_service() -> ServiceDefinition:
    """Create STT MongoDB service definition."""
    return ServiceDefinition(
        name="stt-mongo",
        category="stt",
        image="mongo:6.0.2",
        networks=["net_stt_services"],
        volumes=[
            VolumeMount(source="stt_mongodb_data", target="/data/db"),
        ],
        healthcheck=HealthcheckConfig(
            test=["CMD", "mongosh", "--eval", "db.adminCommand('ping')"],
            interval="30s",
            timeout="10s",
            retries=3,
            start_period="30s",
        ),
    )


def _task_broker_redis_service(redis_password: str) -> ServiceDefinition:
    """Create Redis task broker service definition."""
    return ServiceDefinition(
        name="task-broker-redis",
        category="stt",
        image="redis:7",
        networks=["task_broker_services"],
        command=["redis-server", "--requirepass", redis_password],
        volumes=[
            VolumeMount(source="task_broker_redis_data", target="/data"),
        ],
        healthcheck=HealthcheckConfig(
            test=["CMD", "redis-cli", "ping"],
            interval="30s",
            timeout="10s",
            retries=3,
            start_period="10s",
        ),
    )


def _stt_whisper_service(
    image_tag: str,
    redis_password: str,
) -> ServiceDefinition:
    """Create STT Whisper API service definition."""
    service_name = "stt-all-whisper-v3-turbo"
    return ServiceDefinition(
        name=service_name,
        category="stt",
        image=f"lintoai/linto-transcription-service:{image_tag}",
        depends_on=["task-broker-redis", "stt-mongo", "api-gateway"],
        networks=["linto", "net_stt_services", "task_broker_services"],
        traefik_endpoint=f"/{service_name}",
        traefik_strip_prefix=True,
        environment={
            "SERVICES_BROKER": "redis://task-broker-redis:6379",
            "BROKER_PASS": redis_password,
            "MONGO_HOST": "stt-mongo",
            "MONGO_PORT": "27017",
            "SERVICE_NAME": service_name,
            "LANGUAGE": "*",
            "CONCURRENCY": "2",
            # Gateway registration
            "GATEWAY_SERVICE_BASE_URL": "http://api-gateway",
            "GATEWAY_PROXY_PATH": f"/{service_name}",
            "GATEWAY_DESCRIPTION": f'{{"en": "{service_name}", "fr": "{service_name}"}}',
            "PROXIED_SERVICE_BASE_URL": f"http://{service_name}",
            "REGISTRATION_MODE": "DOCKER",
            "RESOLVE_POLICY": "ANY",
            # Model settings
            "ACCOUSTIC": "1",
            "MODEL_QUALITY": "1",
            "SECURITY_LEVEL": "0",
            "MODEL_TYPE": "whisper",
            "DIARIZATION_DEFAULT": "false",
            "WEBSERVER_HTTP_PORT": "80",
            "SWAGGER_PREFIX": f"/{service_name}",
            "SWAGGER_URLS": f"/{service_name}",
        },
        healthcheck=HealthcheckConfig(
            test=[
                "CMD",
                "wget",
                "--quiet",
                "--tries=1",
                "--spider",
                "http://localhost:80/healthcheck",
            ],
            interval="15s",
            timeout="10s",
            retries=4,
            start_period="180s",
        ),
    )


def _stt_whisper_workers_service(
    image_tag: str,
    redis_password: str,
) -> ServiceDefinition:
    """Create STT Whisper Worker service definition."""
    return ServiceDefinition(
        name="stt-whisper-workers",
        category="stt",
        image=f"lintoai/linto-stt-whisper:{image_tag}",
        depends_on=["task-broker-redis"],
        networks=["net_stt_services", "task_broker_services"],
        environment={
            "SERVICES_BROKER": "redis://task-broker-redis:6379",
            "BROKER_PASS": redis_password,
            "SERVICE_NAME": "stt-all-whisper-v3-turbo",
            "MODEL": "large-v3-turbo",
            "LANGUAGE": "*",
            "DEVICE": "cpu",
            "CONCURRENCY": "1",
            "SECURITY_LEVEL": "0",
        },
    )


def _diarization_pyannote_service(
    image_tag: str,
    redis_password: str,
) -> ServiceDefinition:
    """Create Diarization Pyannote service definition."""
    return ServiceDefinition(
        name="diarization-pyannote",
        category="stt",
        image=f"lintoai/linto-diarization-pyannote:{image_tag}",
        depends_on=["task-broker-redis"],
        networks=["net_stt_services", "task_broker_services"],
        environment={
            "SERVICES_BROKER": "redis://task-broker-redis:6379",
            "BROKER_PASS": redis_password,
            "SERVICE_NAME": "diarization",
            "DEVICE": "cpu",
            "CONCURRENCY": "1",
        },
    )


# ============================================================================
# Live Session Services
# ============================================================================


def _session_postgres_service(password: str) -> ServiceDefinition:
    """Create Session PostgreSQL service definition."""
    return ServiceDefinition(
        name="session-postgres",
        category="live",
        image="postgres:15-alpine",
        networks=["session_network", "net_studio"],
        volumes=[
            VolumeMount(source="session_postgres_data", target="/var/lib/postgresql/data"),
        ],
        environment={
            "POSTGRES_DB": "session_DB",
            "POSTGRES_USER": "session_user",
            "POSTGRES_PASSWORD": password,
        },
        deploy=DeployConfig(
            mode="replicated",
            replicas=1,
            placement_constraints=["node.role==manager"],
        ),
        healthcheck=HealthcheckConfig(
            test=["CMD-SHELL", "pg_isready -U session_user -d session_DB"],
            interval="30s",
            timeout="10s",
            retries=3,
            start_period="30s",
        ),
    )


def _session_postgres_migration_service(
    image_tag: str,
    password: str,
) -> ServiceDefinition:
    """Create Session PostgreSQL migration service definition."""
    return ServiceDefinition(
        name="session-postgres-migration",
        category="live",
        image=f"lintoai/studio-plugins-migration:{image_tag}",
        depends_on=["session-postgres"],
        networks=["session_network"],
        environment={
            "DB_HOST": "session-postgres",
            "DB_PORT": "5432",
            "DB_NAME": "session_DB",
            "DB_USER": "session_user",
            "DB_PASSWORD": password,
            "NODE_ENV": "production",
        },
        restart="no",
        deploy=DeployConfig(
            mode="replicated",
            replicas=1,
            restart_policy=RestartPolicy(condition="on-failure"),
        ),
    )


def _session_broker_service() -> ServiceDefinition:
    """Create Session MQTT broker service definition."""
    return ServiceDefinition(
        name="session-broker",
        category="live",
        image="eclipse-mosquitto:2",
        networks=["session_network", "net_studio"],
        command="mosquitto -c /mosquitto-no-auth.conf",
        expose=["1883"],
        healthcheck=HealthcheckConfig(
            test=["CMD-SHELL", "mosquitto_sub -t '$SYS/#' -C 1 -W 3 || exit 1"],
            interval="30s",
            timeout="10s",
            retries=3,
            start_period="10s",
        ),
    )


def _session_api_service(
    domain: str,
    image_tag: str,
    session_postgres_password: str,
    session_crypt_key: str,
) -> ServiceDefinition:
    """Create Session API service definition."""
    return ServiceDefinition(
        name="session-api",
        category="live",
        image=f"lintoai/studio-plugins-sessionapi:{image_tag}",
        depends_on=["session-postgres", "session-broker"],
        networks=["session_network", "linto"],
        traefik_endpoint="/session-api",
        traefik_strip_prefix=True,
        expose=["80"],
        environment={
            "BROKER_HOST": "session-broker",
            "BROKER_PORT": "1883",
            "BROKER_PROTOCOL": "mqtt",
            "BROKER_KEEPALIVE": "60",
            "DB_HOST": "session-postgres",
            "DB_PORT": "5432",
            "DB_NAME": "session_DB",
            "DB_USER": "session_user",
            "DB_PASSWORD": session_postgres_password,
            "SESSION_API_BASE_PATH": "/",
            "SESSION_API_WEBSERVER_HTTP_PORT": "80",
            "STREAMING_HOST": "session-transcriber",
            "STREAMING_PASSPHRASE": "false",
            "STREAMING_PROXY_RTMP_HOST": domain,
            "STREAMING_PROXY_RTMP_TCP_PORT": "1935",
            "STREAMING_PROXY_SRT_HOST": domain,
            "STREAMING_PROXY_SRT_UDP_PORT": "8889",
            "STREAMING_PROXY_WS_HOST": domain,
            "STREAMING_PROXY_WS_TCP_PORT": "443",
            "STREAMING_WS_SECURE": "true",
            "SECURITY_CRYPT_KEY": session_crypt_key,
            "LOG_FORMAT": "text",
            "LOG_LEVEL": "debug",
        },
    )


def _session_scheduler_service(
    image_tag: str,
    session_postgres_password: str,
) -> ServiceDefinition:
    """Create Session scheduler service definition."""
    return ServiceDefinition(
        name="session-scheduler",
        category="live",
        image=f"lintoai/studio-plugins-scheduler:{image_tag}",
        depends_on=["session-postgres", "session-broker"],
        networks=["session_network", "net_studio"],
        environment={
            "BROKER_HOST": "session-broker",
            "BROKER_PORT": "1883",
            "BROKER_PROTOCOL": "mqtt",
            "BROKER_KEEPALIVE": "60",
            "DB_HOST": "session-postgres",
            "DB_PORT": "5432",
            "DB_NAME": "session_DB",
            "DB_USER": "session_user",
            "DB_PASSWORD": session_postgres_password,
            "LOG_FORMAT": "text",
            "LOG_LEVEL": "debug",
            "SCHEDULER_WEBSERVER_HTTP_PORT": "80",
        },
    )


def _session_transcriber_service(
    domain: str,
    image_tag: str,
    replicas: int,
    session_crypt_key: str,
) -> ServiceDefinition:
    """Create Session transcriber service definition."""
    return ServiceDefinition(
        name="session-transcriber",
        category="live",
        image=f"lintoai/studio-plugins-transcriber:{image_tag}",
        depends_on=["session-broker"],
        networks=["linto", "session_network"],
        traefik_endpoint="/transcriber-ws",
        traefik_strip_prefix=True,
        traefik_server_port=8080,
        expose=["8889/udp", "1935", "8080"],
        volumes=[
            VolumeMount(source="session_audio_data", target="/session_audio"),
        ],
        environment={
            "BROKER_HOST": "session-broker",
            "BROKER_PORT": "1883",
            "BROKER_PROTOCOL": "mqtt",
            "BROKER_KEEPALIVE": "60",
            "AUDIO_STORAGE_PATH": "/session_audio",
            "STREAMING_PROTOCOLS": "SRT,RTMP,WS",
            "STREAMING_SRT_MODE": "listener",
            "STREAMING_SRT_UDP_PORT": "8889",
            "STREAMING_RTMP_TCP_PORT": "1935",
            "STREAMING_RTMP_SECURE": "false",
            "STREAMING_WS_TCP_PORT": "8080",
            "STREAMING_WS_ENDPOINT": "transcriber-ws",
            "STREAMING_WS_SECURE": "true",
            "STREAMING_PASSPHRASE": "false",
            "STREAMING_HEALTHCHECK_TCP": "9999",
            "STREAMING_PROXY_RTMP_HOST": domain,
            "STREAMING_PROXY_RTMP_TCP_PORT": "1935",
            "STREAMING_PROXY_SRT_HOST": domain,
            "STREAMING_PROXY_SRT_UDP_PORT": "8889",
            "STREAMING_PROXY_WS_HOST": domain,
            "STREAMING_PROXY_WS_TCP_PORT": "443",
            "SECURITY_CRYPT_KEY": session_crypt_key,
            "LOG_FORMAT": "text",
            "LOG_LEVEL": "debug",
        },
        deploy=DeployConfig(
            mode="replicated",
            replicas=replicas,
        ),
        extra_labels=[
            "traefik.udp.routers.session-transcriber-srt.entrypoints=srt",
            "traefik.udp.routers.session-transcriber-srt.service=session-transcriber-srt",
            "traefik.udp.services.session-transcriber-srt.loadbalancer.server.port=8889",
            "traefik.tcp.routers.session-transcriber-rtmp.entrypoints=rtmp",
            "traefik.tcp.routers.session-transcriber-rtmp.rule=HostSNI(`*`)",
            "traefik.tcp.routers.session-transcriber-rtmp.service=session-transcriber-rtmp",
            "traefik.tcp.services.session-transcriber-rtmp.loadbalancer.server.port=1935",
        ],
    )


# ============================================================================
# Streaming STT Services
# ============================================================================


def _stt_whisper_streaming_service(
    image_tag: str,
    use_gpu: bool = False,
) -> ServiceDefinition:
    """Create Whisper streaming STT service definition."""
    return ServiceDefinition(
        name="stt-whisper-streaming",
        category="live",
        image=f"lintoai/linto-stt-whisper:{image_tag}",
        networks=["session_network"],
        environment={
            "SERVICE_MODE": "websocket",
            "MODEL": "large-v3-turbo",
            "LANGUAGE": "*",
            "DEVICE": "cuda" if use_gpu else "cpu",
            "VAD": "true",
            "STREAMING_MIN_CHUNK_SIZE": "0.5",
            "STREAMING_BUFFER_TRIMMING_SEC": "8",
            "STREAMING_PAUSE_FOR_FINAL": "1.0",
        },
        gpu_required=use_gpu,
    )


def _stt_kaldi_french_streaming_service(image_tag: str) -> ServiceDefinition:
    """Create Kaldi French streaming STT service definition."""
    return ServiceDefinition(
        name="stt-kaldi-french-streaming",
        category="live",
        image=f"lintoai/linto-stt-kaldi:{image_tag}",
        networks=["session_network"],
        environment={
            "SERVICE_MODE": "websocket",
            "LANGUAGE": "fr-FR",
        },
        gpu_required=False,
    )


def _stt_nemo_french_streaming_service(image_tag: str) -> ServiceDefinition:
    """Create NeMo French streaming STT service definition."""
    return ServiceDefinition(
        name="stt-nemo-french-streaming",
        category="live",
        image=f"lintoai/linto-stt-nemo:{image_tag}",
        networks=["session_network"],
        environment={
            "SERVICE_MODE": "websocket",
            "LANGUAGE": "fr-FR",
            "DEVICE": "cuda",
        },
        gpu_required=True,
    )


def _stt_nemo_english_streaming_service(image_tag: str) -> ServiceDefinition:
    """Create NeMo English streaming STT service definition."""
    return ServiceDefinition(
        name="stt-nemo-english-streaming",
        category="live",
        image=f"lintoai/linto-stt-nemo:{image_tag}",
        networks=["session_network"],
        environment={
            "SERVICE_MODE": "websocket",
            "LANGUAGE": "en-US",
            "DEVICE": "cuda",
        },
        gpu_required=True,
    )


def _stt_kyutai_streaming_service(
    image_tag: str,
    gpu_architecture: GPUArchitecture,
) -> ServiceDefinition:
    """Create Kyutai streaming STT service definition."""
    # Image tag includes architecture suffix
    full_tag = f"{image_tag}-{gpu_architecture.value}"
    return ServiceDefinition(
        name="stt-kyutai-streaming",
        category="live",
        image=f"lintoai/kyutai-moshi-stt-server-cuda:{full_tag}",
        networks=["session_network"],
        environment={
            "DEVICE": "cuda",
        },
        gpu_required=True,
    )


def get_streaming_stt_service(
    variant: StreamingSTTVariant,
    image_tag: str,
    gpu_architecture: GPUArchitecture | None = None,
) -> ServiceDefinition:
    """Get streaming STT service definition for a variant."""
    if variant == StreamingSTTVariant.WHISPER:
        return _stt_whisper_streaming_service(image_tag, use_gpu=True)
    elif variant == StreamingSTTVariant.KALDI_FRENCH:
        return _stt_kaldi_french_streaming_service(image_tag)
    elif variant == StreamingSTTVariant.NEMO_FRENCH:
        return _stt_nemo_french_streaming_service(image_tag)
    elif variant == StreamingSTTVariant.NEMO_ENGLISH:
        return _stt_nemo_english_streaming_service(image_tag)
    elif variant == StreamingSTTVariant.KYUTAI:
        if gpu_architecture is None:
            msg = "Kyutai requires gpu_architecture"
            raise ValueError(msg)
        return _stt_kyutai_streaming_service(image_tag, gpu_architecture)
    else:
        msg = f"Unknown streaming STT variant: {variant}"
        raise ValueError(msg)


# ============================================================================
# LLM Services
# ============================================================================


def _llm_postgres_service(password: str) -> ServiceDefinition:
    """Create LLM PostgreSQL service definition."""
    return ServiceDefinition(
        name="llm-postgres",
        category="llm",
        image="postgres:15-alpine",
        networks=["net_llm_services"],
        volumes=[
            VolumeMount(source="llm_postgres_data", target="/var/lib/postgresql/data"),
        ],
        environment={
            "POSTGRES_DB": "llm_DB",
            "POSTGRES_USER": "llm_user",
            "POSTGRES_PASSWORD": password,
        },
        deploy=DeployConfig(
            mode="replicated",
            replicas=1,
            placement_constraints=["node.role==manager"],
        ),
        healthcheck=HealthcheckConfig(
            test=["CMD-SHELL", "pg_isready -U llm_user -d llm_DB"],
            interval="30s",
            timeout="10s",
            retries=3,
            start_period="30s",
        ),
    )


def _llm_redis_service(password: str) -> ServiceDefinition:
    """Create LLM Redis service definition."""
    return ServiceDefinition(
        name="llm-redis",
        category="llm",
        image="redis/redis-stack-server:latest",
        networks=["net_llm_services"],
        command=f"/bin/sh -c 'redis-stack-server --requirepass {password}'",
        volumes=[
            VolumeMount(source="llm_redis_data", target="/data"),
        ],
        healthcheck=HealthcheckConfig(
            test=["CMD", "redis-cli", "ping"],
            interval="30s",
            timeout="10s",
            retries=3,
            start_period="10s",
        ),
    )


def _llm_gateway_api_service(
    image_tag: str,
    openai_api_base: str,
    openai_api_token: str,
    redis_password: str,
) -> ServiceDefinition:
    """Create LLM Gateway API service definition."""
    return ServiceDefinition(
        name="llm-gateway-api",
        category="llm",
        image=f"lintoai/llm-gateway:{image_tag}",
        depends_on=["llm-redis"],
        networks=["net_llm_services", "linto"],
        traefik_endpoint="/llm-gateway",
        traefik_strip_prefix=True,
        command="-m app --debug",
        volumes=[
            VolumeMount(source="llm_models_cache", target="/root/.cache"),
            VolumeMount(source="./.linto/llm/hydra-conf", target="/usr/src/.hydra-conf"),
            VolumeMount(source="./.linto/llm/prompts", target="/usr/src/prompts"),
        ],
        environment={
            "SERVICES_BROKER": "redis://llm-redis:6379",
            "BROKER_PASS": redis_password,
            "OPENAI_API_BASE": openai_api_base,
            "OPENAI_API_TOKEN": openai_api_token,
            "HTTP_PORT": "80",
            "CONCURRENCY": "1",
            "SERVICE_NAME": "LLM_Gateway",
            "SWAGGER_PATH": "../document/swagger_llm_gateway.yml",
            "SWAGGER_PREFIX": "/llm-gateway",
            "SWAGGER_URL": "/llm-gateway",
            "PYTHONUNBUFFERED": "1",
            "TIMEOUT": "60",
            "RESULT_DB_PATH": "./results.sqlite",
        },
    )


def _llm_celery_worker_service(
    image_tag: str,
    redis_password: str,
    openai_api_base: str,
    openai_api_token: str,
) -> ServiceDefinition:
    """Create LLM Celery Worker service definition for async tasks."""
    return ServiceDefinition(
        name="llm-celery-worker",
        category="llm",
        image=f"lintoai/llm-gateway:{image_tag}",
        depends_on=["llm-redis", "llm-postgres"],
        networks=["net_llm_services"],
        command="celery -A app.celery.celery_app worker --loglevel=info",
        environment={
            "SERVICES_BROKER": "redis://llm-redis:6379",
            "BROKER_PASS": redis_password,
            "OPENAI_API_BASE": openai_api_base,
            "OPENAI_API_TOKEN": openai_api_token,
            "PYTHONUNBUFFERED": "1",
            "CONCURRENCY": "1",
        },
    )


def _llm_gateway_frontend_service(
    domain: str,
    image_tag: str,
) -> ServiceDefinition:
    """Create LLM Gateway Frontend service definition."""
    return ServiceDefinition(
        name="llm-gateway-frontend",
        category="llm",
        image=f"lintoai/llm-gateway-frontend:{image_tag}",
        depends_on=["llm-gateway-api"],
        networks=["net_llm_services", "linto"],
        traefik_endpoint="/llm-admin",
        traefik_strip_prefix=False,
        environment={
            "NEXT_PUBLIC_API_URL": f"https://{domain}/llm-gateway",
        },
    )


def _vllm_service() -> ServiceDefinition:
    """Create vLLM service definition."""
    return ServiceDefinition(
        name="vllm-service",
        category="llm",
        image="vllm/vllm-openai:latest",
        networks=["net_llm_services", "linto"],
        command="--model casperhansen/llama-3-8b-instruct-awq --quantization awq --gpu-memory-utilization 0.65",
        volumes=[
            VolumeMount(source="vllm_models_cache", target="/root/.cache/huggingface"),
        ],
        environment={
            "NVIDIA_DRIVER_CAPABILITIES": "all",
            "NVIDIA_VISIBLE_DEVICES": "0",
        },
        gpu_required=True,
        deploy=DeployConfig(
            mode="replicated",
            replicas=1,
            placement_constraints=["node.labels.ip==ingress"],
        ),
    )


# ============================================================================
# Service catalog
# ============================================================================

# Service catalog as a dictionary of service factories
SERVICES = {
    "traefik": _traefik_service,
    "api-gateway": _api_gateway_service,
    "studio-mongodb": _studio_mongodb_service,
    "studio-api": _studio_api_service,
    "studio-frontend": _studio_frontend_service,
    "studio-websocket": _studio_websocket_service,
    "stt-mongo": _stt_mongo_service,
    "task-broker-redis": _task_broker_redis_service,
    "stt-all-whisper-v3-turbo": _stt_whisper_service,
    "stt-whisper-workers": _stt_whisper_workers_service,
    "diarization-pyannote": _diarization_pyannote_service,
    # Live Session
    "session-postgres": _session_postgres_service,
    "session-postgres-migration": _session_postgres_migration_service,
    "session-broker": _session_broker_service,
    "session-api": _session_api_service,
    "session-scheduler": _session_scheduler_service,
    "session-transcriber": _session_transcriber_service,
    # Streaming STT
    "stt-whisper-streaming": _stt_whisper_streaming_service,
    "stt-kaldi-french-streaming": _stt_kaldi_french_streaming_service,
    "stt-nemo-french-streaming": _stt_nemo_french_streaming_service,
    "stt-nemo-english-streaming": _stt_nemo_english_streaming_service,
    "stt-kyutai-streaming": _stt_kyutai_streaming_service,
    # LLM
    "llm-postgres": _llm_postgres_service,
    "llm-redis": _llm_redis_service,
    "llm-gateway-api": _llm_gateway_api_service,
    "llm-celery-worker": _llm_celery_worker_service,
    "llm-gateway-frontend": _llm_gateway_frontend_service,
    "vllm-service": _vllm_service,
}


def get_studio_services() -> list[str]:
    """Get list of Studio service names."""
    return [
        "studio-mongodb",
        "studio-api",
        "studio-frontend",
        "studio-websocket",
    ]


def get_stt_services() -> list[str]:
    """Get list of STT service names."""
    return [
        "api-gateway",
        "stt-mongo",
        "task-broker-redis",
        "stt-all-whisper-v3-turbo",
        "stt-whisper-workers",
        "diarization-pyannote",
    ]


def get_infra_services() -> list[str]:
    """Get list of infrastructure service names."""
    return ["traefik"]


def get_live_session_services() -> list[str]:
    """Get list of Live Session service names."""
    return [
        "session-postgres",
        "session-postgres-migration",
        "session-broker",
        "session-api",
        "session-scheduler",
        "session-transcriber",
    ]


def get_llm_services() -> list[str]:
    """Get list of LLM service names."""
    return [
        "llm-postgres",
        "llm-redis",
        "llm-gateway-api",
        "llm-celery-worker",
        "llm-gateway-frontend",
    ]
