"""Docker Compose renderer and operations."""

from pathlib import Path
from typing import Any

import yaml
from rich.console import Console
from rich.table import Table

from linto.backends.base import (
    generate_traefik_dynamic_config,
    service_to_compose_dict,
)
from linto.catalog.services import (
    LLM_NETWORKS,
    SESSION_NETWORKS,
    STT_NETWORKS,
    STUDIO_NETWORKS,
    _api_gateway_service,
    _diarization_pyannote_service,
    _llm_celery_worker_service,
    _llm_gateway_api_service,
    _llm_gateway_frontend_service,
    _llm_postgres_service,
    _llm_redis_service,
    _session_api_service,
    _session_broker_service,
    _session_postgres_migration_service,
    _session_postgres_service,
    _session_scheduler_service,
    _session_transcriber_service,
    _stt_mongo_service,
    _stt_whisper_service,
    _stt_whisper_workers_service,
    _studio_api_service,
    _studio_frontend_service,
    _studio_mongodb_service,
    _studio_websocket_service,
    _task_broker_redis_service,
    _traefik_service,
    _vllm_service,
    get_streaming_stt_service,
)
from linto.model.profile import ProfileConfig, TLSMode
from linto.model.validation import ValidationError, load_profile, save_profile
from linto.tls.mkcert import generate_certs
from linto.utils.docker import run_docker_compose
from linto.utils.secrets import generate_secrets

console = Console()


def render_compose(profile: ProfileConfig) -> dict[str, Any]:
    """Render docker-compose.yml as a dictionary."""
    # Ensure secrets are populated
    profile = generate_secrets(profile)

    services: dict[str, Any] = {}
    networks: dict[str, Any] = {"linto": {"driver": "bridge"}}
    volumes: dict[str, Any] = {}

    tls_mode = profile.tls_mode.value if isinstance(profile.tls_mode, TLSMode) else profile.tls_mode

    # Always add traefik
    traefik = _traefik_service(profile.domain, tls_mode)
    services[traefik.name] = service_to_compose_dict(traefik, profile.domain, tls_mode)

    # Add Studio services
    if profile.studio_enabled:
        networks.update(STUDIO_NETWORKS)

        mongodb = _studio_mongodb_service()
        services[mongodb.name] = service_to_compose_dict(mongodb, profile.domain, tls_mode)
        volumes["studio_mongodb_data"] = {}

        api = _studio_api_service(
            domain=profile.domain,
            image_tag=profile.image_tag,
            jwt_secret=profile.jwt_secret or "",
            jwt_refresh_secret=profile.jwt_refresh_secret or "",
            super_admin_email=profile.super_admin_email,
            super_admin_password=profile.super_admin_password or "",
            live_session_enabled=profile.live_session_enabled,
            llm_enabled=profile.llm_enabled,
            stt_enabled=profile.stt_enabled,
        )
        services[api.name] = service_to_compose_dict(api, profile.domain, tls_mode)

        frontend = _studio_frontend_service(
            domain=profile.domain,
            image_tag=profile.image_tag,
        )
        services[frontend.name] = service_to_compose_dict(frontend, profile.domain, tls_mode)

        websocket = _studio_websocket_service(
            domain=profile.domain,
            image_tag=profile.image_tag,
            jwt_secret=profile.jwt_secret or "",
        )
        services[websocket.name] = service_to_compose_dict(websocket, profile.domain, tls_mode)

    # Add STT services
    if profile.stt_enabled:
        networks.update(STT_NETWORKS)

        # API Gateway for service discovery
        api_gateway = _api_gateway_service(image_tag=profile.image_tag)
        services[api_gateway.name] = service_to_compose_dict(api_gateway, profile.domain, tls_mode)

        stt_mongo = _stt_mongo_service()
        services[stt_mongo.name] = service_to_compose_dict(stt_mongo, profile.domain, tls_mode)
        volumes["stt_mongodb_data"] = {}

        redis = _task_broker_redis_service(profile.redis_password or "")
        services[redis.name] = service_to_compose_dict(redis, profile.domain, tls_mode)
        volumes["task_broker_redis_data"] = {}

        whisper_api = _stt_whisper_service(
            image_tag=profile.image_tag,
            redis_password=profile.redis_password or "",
        )
        services[whisper_api.name] = service_to_compose_dict(whisper_api, profile.domain, tls_mode)

        whisper_workers = _stt_whisper_workers_service(
            image_tag=profile.image_tag,
            redis_password=profile.redis_password or "",
        )
        services[whisper_workers.name] = service_to_compose_dict(whisper_workers, profile.domain, tls_mode)

        diarization = _diarization_pyannote_service(
            image_tag=profile.image_tag,
            redis_password=profile.redis_password or "",
        )
        services[diarization.name] = service_to_compose_dict(diarization, profile.domain, tls_mode)

    # Add Live Session services
    if profile.live_session_enabled:
        networks.update(SESSION_NETWORKS)

        session_postgres = _session_postgres_service(profile.session_postgres_password or "")
        services[session_postgres.name] = service_to_compose_dict(session_postgres, profile.domain, tls_mode)
        volumes["session_postgres_data"] = {}

        session_migration = _session_postgres_migration_service(
            image_tag=profile.image_tag,
            password=profile.session_postgres_password or "",
        )
        services[session_migration.name] = service_to_compose_dict(session_migration, profile.domain, tls_mode)

        session_broker = _session_broker_service()
        services[session_broker.name] = service_to_compose_dict(session_broker, profile.domain, tls_mode)

        session_api = _session_api_service(
            domain=profile.domain,
            image_tag=profile.image_tag,
            session_postgres_password=profile.session_postgres_password or "",
            session_crypt_key=profile.session_crypt_key or "",
        )
        services[session_api.name] = service_to_compose_dict(session_api, profile.domain, tls_mode)

        session_scheduler = _session_scheduler_service(
            image_tag=profile.image_tag,
            session_postgres_password=profile.session_postgres_password or "",
        )
        services[session_scheduler.name] = service_to_compose_dict(session_scheduler, profile.domain, tls_mode)

        session_transcriber = _session_transcriber_service(
            domain=profile.domain,
            image_tag=profile.image_tag,
            replicas=profile.session_transcriber_replicas,
            session_crypt_key=profile.session_crypt_key or "",
        )
        services[session_transcriber.name] = service_to_compose_dict(session_transcriber, profile.domain, tls_mode)
        volumes["session_audio_data"] = {}

        # Add streaming STT services
        for variant in profile.streaming_stt_variants:
            stt_service = get_streaming_stt_service(
                variant=variant,
                image_tag=profile.image_tag,
                gpu_architecture=profile.kyutai_gpu_architecture,
            )
            services[stt_service.name] = service_to_compose_dict(stt_service, profile.domain, tls_mode)

    # Add LLM services
    if profile.llm_enabled:
        networks.update(LLM_NETWORKS)

        llm_postgres = _llm_postgres_service(profile.llm_postgres_password or "")
        services[llm_postgres.name] = service_to_compose_dict(llm_postgres, profile.domain, tls_mode)
        volumes["llm_postgres_data"] = {}

        llm_redis = _llm_redis_service(profile.llm_redis_password or "")
        services[llm_redis.name] = service_to_compose_dict(llm_redis, profile.domain, tls_mode)
        volumes["llm_redis_data"] = {}

        # Determine OpenAI API base
        openai_api_base = profile.openai_api_base
        if profile.vllm_enabled and not openai_api_base:
            openai_api_base = "http://vllm-service:8000/v1"

        llm_gateway = _llm_gateway_api_service(
            image_tag=profile.image_tag,
            openai_api_base=openai_api_base or "",
            openai_api_token=profile.openai_api_token or "",
            redis_password=profile.llm_redis_password or "",
        )
        services[llm_gateway.name] = service_to_compose_dict(llm_gateway, profile.domain, tls_mode)
        volumes["llm_models_cache"] = {}

        # Celery worker for async tasks
        llm_celery = _llm_celery_worker_service(
            image_tag=profile.image_tag,
            redis_password=profile.llm_redis_password or "",
            openai_api_base=openai_api_base or "",
            openai_api_token=profile.openai_api_token or "",
        )
        services[llm_celery.name] = service_to_compose_dict(llm_celery, profile.domain, tls_mode)

        llm_frontend = _llm_gateway_frontend_service(
            domain=profile.domain,
            image_tag=profile.image_tag,
        )
        services[llm_frontend.name] = service_to_compose_dict(llm_frontend, profile.domain, tls_mode)

        if profile.vllm_enabled:
            vllm = _vllm_service()
            services[vllm.name] = service_to_compose_dict(vllm, profile.domain, tls_mode)
            volumes["vllm_models_cache"] = {}

    return {
        "version": "3.8",
        "services": services,
        "networks": networks,
        "volumes": volumes,
    }


def generate_compose(
    profile_name: str,
    output_dir: str | None = None,
    base_dir: Path | None = None,
) -> Path:
    """Generate docker-compose.yml for a profile.

    Args:
        profile_name: Name of the profile to generate
        output_dir: Optional output directory path
        base_dir: Base directory for .linto folder

    Returns:
        Path to the generated docker-compose.yml
    """
    if base_dir is None:
        base_dir = Path.cwd()

    # Load profile
    profile = load_profile(profile_name, base_dir)

    # Ensure secrets are populated and save back
    profile = generate_secrets(profile)
    save_profile(profile, base_dir)

    tls_mode = profile.tls_mode.value if isinstance(profile.tls_mode, TLSMode) else profile.tls_mode

    # Determine output directory
    if output_dir:
        compose_dir = Path(output_dir)
    else:
        compose_dir = base_dir / ".linto" / "render" / "compose" / profile_name

    compose_dir.mkdir(parents=True, exist_ok=True)

    # Generate TLS certificates if needed
    if tls_mode == "mkcert":
        certs_dir = base_dir / ".linto" / "tls" / "certs"
        cert_path, key_path = generate_certs(profile.domain, certs_dir)
        console.print(f"[green]Generated TLS certificates in {certs_dir}[/green]")

        # Create Traefik dynamic config
        traefik_dynamic_dir = base_dir / ".linto" / "traefik" / "dynamic"
        traefik_dynamic_dir.mkdir(parents=True, exist_ok=True)
        dynamic_config = generate_traefik_dynamic_config(profile.domain)
        dynamic_config_path = traefik_dynamic_dir / "tls.yml"
        with dynamic_config_path.open("w") as f:
            yaml.dump(dynamic_config, f, default_flow_style=False)

    elif tls_mode == "acme":
        # Setup ACME storage
        from linto.tls.acme import setup_acme_storage

        setup_acme_storage(base_dir)
        console.print("[green]Prepared ACME storage for Let's Encrypt[/green]")

    elif tls_mode == "custom":
        # Import custom certificates
        from linto.tls.custom import import_custom_certs

        if profile.custom_cert_path and profile.custom_key_path:
            import_custom_certs(
                cert_path=Path(profile.custom_cert_path),
                key_path=Path(profile.custom_key_path),
                domain=profile.domain,
                base_dir=base_dir,
            )
            console.print("[green]Imported custom TLS certificates[/green]")

            # Create Traefik dynamic config
            traefik_dynamic_dir = base_dir / ".linto" / "traefik" / "dynamic"
            traefik_dynamic_dir.mkdir(parents=True, exist_ok=True)
            dynamic_config = generate_traefik_dynamic_config(profile.domain)
            dynamic_config_path = traefik_dynamic_dir / "tls.yml"
            with dynamic_config_path.open("w") as f:
                yaml.dump(dynamic_config, f, default_flow_style=False)

    # Create LLM config directories if LLM enabled
    if profile.llm_enabled:
        llm_hydra_dir = base_dir / ".linto" / "llm" / "hydra-conf"
        llm_prompts_dir = base_dir / ".linto" / "llm" / "prompts"
        llm_hydra_dir.mkdir(parents=True, exist_ok=True)
        llm_prompts_dir.mkdir(parents=True, exist_ok=True)

    # Render compose
    compose_dict = render_compose(profile)

    # Write docker-compose.yml
    compose_path = compose_dir / "docker-compose.yml"
    with compose_path.open("w") as f:
        yaml.dump(compose_dict, f, default_flow_style=False, sort_keys=False)

    # Write .env file with non-sensitive vars
    env_path = compose_dir / ".env"
    with env_path.open("w") as f:
        f.write(f"COMPOSE_PROJECT_NAME=linto-{profile_name}\n")
        f.write(f"DOMAIN={profile.domain}\n")
        f.write(f"IMAGE_TAG={profile.image_tag}\n")

    # Print summary
    _print_summary(profile, compose_path)

    return compose_path


def _print_summary(profile: ProfileConfig, compose_path: Path) -> None:
    """Print a summary table of the generated configuration."""
    table = Table(title="Deployment Summary")
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="green")

    tls_mode = profile.tls_mode.value if isinstance(profile.tls_mode, TLSMode) else profile.tls_mode

    table.add_row("Profile", profile.name)
    table.add_row("Backend", "Docker Compose")
    table.add_row("Domain", profile.domain)
    table.add_row("Image Tag", profile.image_tag)
    table.add_row("TLS Mode", tls_mode)
    table.add_row("Studio Enabled", "Yes" if profile.studio_enabled else "No")
    table.add_row("STT Enabled", "Yes" if profile.stt_enabled else "No")
    table.add_row("Live Session Enabled", "Yes" if profile.live_session_enabled else "No")
    table.add_row("LLM Enabled", "Yes" if profile.llm_enabled else "No")
    table.add_row("Admin Email", profile.super_admin_email)
    table.add_row("Output", str(compose_path))

    console.print(table)


def apply_compose(profile_name: str, base_dir: Path | None = None) -> None:
    """Apply a deployment profile (docker compose up).

    Args:
        profile_name: Name of the profile to apply
        base_dir: Base directory for .linto folder
    """
    if base_dir is None:
        base_dir = Path.cwd()

    compose_dir = base_dir / ".linto" / "render" / "compose" / profile_name

    # Generate if not present
    if not (compose_dir / "docker-compose.yml").exists():
        console.print("[yellow]Generating deployment artifacts...[/yellow]")
        generate_compose(profile_name, base_dir=base_dir)

    console.print(f"[cyan]Starting deployment for profile '{profile_name}'...[/cyan]")

    result = run_docker_compose(compose_dir, ["up", "-d"])

    if result.returncode == 0:
        console.print("[green]Deployment started successfully![/green]")
        profile = load_profile(profile_name, base_dir)
        console.print(f"[cyan]Access at: https://{profile.domain}[/cyan]")
    else:
        raise ValidationError(
            "APPLY_FAILED",
            f"docker compose up failed with code {result.returncode}",
        )


def destroy_compose(
    profile_name: str,
    remove_files: bool = False,
    base_dir: Path | None = None,
) -> None:
    """Stop and remove a deployment.

    Args:
        profile_name: Name of the profile to destroy
        remove_files: Whether to remove generated files
        base_dir: Base directory for .linto folder
    """
    if base_dir is None:
        base_dir = Path.cwd()

    compose_dir = base_dir / ".linto" / "render" / "compose" / profile_name

    if not (compose_dir / "docker-compose.yml").exists():
        raise ValidationError(
            "PROFILE_NOT_FOUND",
            f"No deployment found for profile '{profile_name}'",
        )

    console.print(f"[yellow]Stopping deployment for profile '{profile_name}'...[/yellow]")

    result = run_docker_compose(compose_dir, ["down", "-v"])

    if result.returncode == 0:
        console.print("[green]Deployment stopped and removed.[/green]")
    else:
        console.print(f"[red]Warning: docker compose down returned {result.returncode}[/red]")

    if remove_files:
        import shutil

        shutil.rmtree(compose_dir)
        console.print(f"[yellow]Removed generated files in {compose_dir}[/yellow]")


# Module-level exports matching Backend protocol
render = render_compose
generate = generate_compose
apply = apply_compose
destroy = destroy_compose
