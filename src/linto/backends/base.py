"""Shared utilities for backend renderers."""

from typing import Any

from linto.model.service import ServiceDefinition


def generate_traefik_labels(
    service_name: str,
    endpoint: str,
    domain: str,
    strip_prefix: bool,
    tls_enabled: bool,
    tls_mode: str,
    server_port: int = 80,
) -> list[str]:
    """Generate Traefik labels for both Compose and Swarm.

    Args:
        service_name: Name of the service for router naming
        endpoint: URL path prefix for the service
        domain: Domain name for routing
        strip_prefix: Whether to strip the prefix from forwarded requests
        tls_enabled: Whether TLS is enabled
        tls_mode: TLS mode (off, mkcert, acme, custom)
        server_port: Backend server port

    Returns:
        List of Traefik label strings
    """
    router_name = service_name.replace("-", "_")
    entrypoint = "websecure" if tls_enabled else "web"

    labels = [
        "traefik.enable=true",
        f"traefik.http.routers.{router_name}.entrypoints={entrypoint}",
        f"traefik.http.services.{router_name}.loadbalancer.server.port={server_port}",
    ]

    # Route rule
    if endpoint == "/":
        labels.append(f"traefik.http.routers.{router_name}.rule=Host(`{domain}`)")
        # Lower priority for catch-all route
        labels.append(f"traefik.http.routers.{router_name}.priority=1")
    else:
        labels.append(f"traefik.http.routers.{router_name}.rule=Host(`{domain}`) && PathPrefix(`{endpoint}`)")

    if tls_enabled:
        labels.append(f"traefik.http.routers.{router_name}.tls=true")
        # ACME uses cert resolver
        if tls_mode == "acme":
            labels.append(f"traefik.http.routers.{router_name}.tls.certresolver=leresolver")

    if strip_prefix and endpoint != "/":
        middleware_name = f"{router_name}_strip"
        labels.extend(
            [
                f"traefik.http.middlewares.{middleware_name}.stripPrefix.prefixes={endpoint}",
                f"traefik.http.routers.{router_name}.middlewares={middleware_name}",
            ]
        )

    return labels


def service_to_compose_dict(
    service: ServiceDefinition,
    domain: str,
    tls_mode: str,
) -> dict[str, Any]:
    """Convert ServiceDefinition to docker-compose service dict.

    Args:
        service: Service definition
        domain: Domain for Traefik routing
        tls_mode: TLS mode string

    Returns:
        Dictionary suitable for docker-compose services section
    """
    svc: dict[str, Any] = {
        "image": service.image,
        "restart": service.restart,
    }

    if service.depends_on:
        svc["depends_on"] = service.depends_on

    if service.networks:
        svc["networks"] = service.networks

    if service.volumes:
        svc["volumes"] = [f"{v.source}:{v.target}{':ro' if v.read_only else ''}" for v in service.volumes]

    if service.environment:
        svc["environment"] = service.environment

    if service.ports:
        svc["ports"] = service.ports

    if service.expose:
        svc["expose"] = service.expose

    if service.command:
        svc["command"] = service.command

    if service.healthcheck:
        svc["healthcheck"] = {
            "test": service.healthcheck.test,
            "interval": service.healthcheck.interval,
            "timeout": service.healthcheck.timeout,
            "retries": service.healthcheck.retries,
            "start_period": service.healthcheck.start_period,
        }

    # Add Traefik labels if endpoint is specified
    labels: list[str] = []
    if service.traefik_endpoint:
        labels = generate_traefik_labels(
            service_name=service.name,
            endpoint=service.traefik_endpoint,
            domain=domain,
            strip_prefix=service.traefik_strip_prefix,
            tls_enabled=(tls_mode != "off"),
            tls_mode=tls_mode,
            server_port=service.traefik_server_port,
        )

    # Add extra labels
    if service.extra_labels:
        labels.extend(service.extra_labels)

    if labels:
        svc["labels"] = labels

    return svc


def service_to_swarm_dict(
    service: ServiceDefinition,
    domain: str,
    tls_mode: str,
) -> dict[str, Any]:
    """Convert ServiceDefinition to Docker Swarm stack service dict.

    Args:
        service: Service definition
        domain: Domain for Traefik routing
        tls_mode: TLS mode string

    Returns:
        Dictionary suitable for docker stack services section
    """
    svc: dict[str, Any] = {
        "image": service.image,
    }

    # Swarm does not use depends_on the same way as Compose
    # Instead, we rely on healthchecks and restart policies

    if service.networks:
        svc["networks"] = service.networks

    if service.volumes:
        svc["volumes"] = [f"{v.source}:{v.target}{':ro' if v.read_only else ''}" for v in service.volumes]

    if service.environment:
        svc["environment"] = service.environment

    # In Swarm, ports are typically exposed via Traefik
    # Only infrastructure services like traefik expose ports directly
    if service.ports:
        svc["ports"] = service.ports

    if service.expose:
        svc["expose"] = service.expose

    if service.command:
        svc["command"] = service.command

    if service.healthcheck:
        svc["healthcheck"] = {
            "test": service.healthcheck.test,
            "interval": service.healthcheck.interval,
            "timeout": service.healthcheck.timeout,
            "retries": service.healthcheck.retries,
            "start_period": service.healthcheck.start_period,
        }

    # Build deploy section
    deploy: dict[str, Any] = {}

    if service.deploy:
        deploy["mode"] = service.deploy.mode
        deploy["replicas"] = service.deploy.replicas

        if service.deploy.placement_constraints:
            deploy["placement"] = {
                "constraints": service.deploy.placement_constraints,
            }

        if service.deploy.resources:
            resources: dict[str, Any] = {}
            if service.deploy.resources.limits:
                limits = {}
                if service.deploy.resources.limits.cpus:
                    limits["cpus"] = service.deploy.resources.limits.cpus
                if service.deploy.resources.limits.memory:
                    limits["memory"] = service.deploy.resources.limits.memory
                if limits:
                    resources["limits"] = limits
            if service.deploy.resources.reservations:
                reservations = {}
                if service.deploy.resources.reservations.cpus:
                    reservations["cpus"] = service.deploy.resources.reservations.cpus
                if service.deploy.resources.reservations.memory:
                    reservations["memory"] = service.deploy.resources.reservations.memory
                if reservations:
                    resources["reservations"] = reservations
            if resources:
                deploy["resources"] = resources

        if service.deploy.restart_policy:
            restart_policy: dict[str, Any] = {
                "condition": service.deploy.restart_policy.condition,
            }
            if service.deploy.restart_policy.delay:
                restart_policy["delay"] = service.deploy.restart_policy.delay
            if service.deploy.restart_policy.max_attempts:
                restart_policy["max_attempts"] = service.deploy.restart_policy.max_attempts
            if service.deploy.restart_policy.window:
                restart_policy["window"] = service.deploy.restart_policy.window
            deploy["restart_policy"] = restart_policy
    else:
        # Default deploy config
        deploy["mode"] = "replicated"
        deploy["replicas"] = 1

    # Build labels for deploy section
    labels: list[str] = []
    if service.traefik_endpoint:
        labels = generate_traefik_labels(
            service_name=service.name,
            endpoint=service.traefik_endpoint,
            domain=domain,
            strip_prefix=service.traefik_strip_prefix,
            tls_enabled=(tls_mode != "off"),
            tls_mode=tls_mode,
            server_port=service.traefik_server_port,
        )

    # Add extra labels
    if service.extra_labels:
        labels.extend(service.extra_labels)

    # Add deploy labels from service definition
    if service.deploy and service.deploy.labels:
        labels.extend(service.deploy.labels)

    if labels:
        deploy["labels"] = labels

    svc["deploy"] = deploy

    return svc


def generate_traefik_dynamic_config(domain: str) -> dict[str, Any]:
    """Generate Traefik dynamic configuration for TLS.

    Args:
        domain: Domain name for certificates

    Returns:
        Traefik dynamic configuration dictionary
    """
    return {
        "tls": {
            "certificates": [
                {
                    "certFile": f"/certs/{domain}.pem",
                    "keyFile": f"/certs/{domain}-key.pem",
                }
            ],
            "stores": {
                "default": {
                    "defaultCertificate": {
                        "certFile": f"/certs/{domain}.pem",
                        "keyFile": f"/certs/{domain}-key.pem",
                    }
                }
            },
        }
    }
