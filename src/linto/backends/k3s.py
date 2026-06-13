"""Kubernetes (k3s) backend using Helm charts."""

import importlib.resources
import json
import subprocess
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml
from rich.console import Console
from rich.table import Table

from linto.model.profile import GPUMode, ProfileConfig, StreamingSTTVariant, TLSMode
from linto.model.validation import ValidationError, load_profile, save_profile
from linto.utils.cmd import run_cmd
from linto.utils.kubeconfig import KubeconfigContext
from linto.utils.secrets import generate_secrets

console = Console()
stderr_console = Console(stderr=True)


def _get_charts_dir() -> Path:
    """Get the path to Helm charts directory."""
    # First try: installed package with importlib.resources
    try:
        # For Python 3.11+
        if hasattr(importlib.resources, "files"):
            # Try to get from package data
            import linto

            pkg_path = Path(importlib.resources.files(linto))
            charts_path = pkg_path.parent.parent / "charts"
            if charts_path.exists():
                return charts_path
    except Exception:
        pass

    # Fallback: development mode (relative to source)
    dev_charts = Path(__file__).parent.parent.parent.parent / "charts"
    if dev_charts.exists():
        return dev_charts

    # Last resort: current working directory
    cwd_charts = Path.cwd() / "charts"
    if cwd_charts.exists():
        return cwd_charts

    raise FileNotFoundError("Helm charts directory not found")


# Lazy initialization
_charts_dir: Path | None = None


def get_charts_dir() -> Path:
    """Get charts directory with lazy initialization."""
    global _charts_dir
    if _charts_dir is None:
        _charts_dir = _get_charts_dir()
    return _charts_dir


def _kubeconfig_requires_tunnel(kubeconfig: dict | None) -> bool:
    """Check if kubeconfig points to localhost (requires SSH tunnel)."""
    if not kubeconfig:
        return False
    try:
        server = kubeconfig["clusters"][0]["cluster"]["server"]
        return "127.0.0.1" in server or "localhost" in server
    except (KeyError, IndexError):
        return False


def check_k3s_prerequisites(profile: ProfileConfig | None = None) -> list[str]:
    """Check for required tools and return list of missing prerequisites.

    Args:
        profile: Optional profile to use its embedded kubeconfig

    Returns:
        List of missing prerequisites (empty if all present)
    """
    kubeconfig = profile.kubeconfig if profile else None

    missing = []

    # Check kubectl
    try:
        result = subprocess.run(
            ["kubectl", "version", "--client", "--output=json"],
            capture_output=True,
            check=False,
            timeout=10,
        )
        if result.returncode != 0:
            missing.append("kubectl not properly configured")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        missing.append("kubectl not found")

    # Check helm
    try:
        result = subprocess.run(
            ["helm", "version", "--short"],
            capture_output=True,
            check=False,
            timeout=10,
        )
        if result.returncode != 0:
            missing.append("helm not properly configured")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        missing.append("helm not found")

    # Check cluster access (using profile's kubeconfig if available)
    requires_tunnel = _kubeconfig_requires_tunnel(kubeconfig)
    with KubeconfigContext(kubeconfig):
        try:
            result = subprocess.run(
                ["kubectl", "cluster-info"],
                capture_output=True,
                check=False,
                timeout=15,
            )
            if result.returncode != 0:
                msg = "Kubernetes cluster not accessible"
                if requires_tunnel:
                    msg += " (SSH tunnel required: ssh -L 6443:127.0.0.1:6443 <host> -N -f)"
                missing.append(msg)
        except (subprocess.TimeoutExpired, FileNotFoundError):
            msg = "Cannot connect to Kubernetes cluster"
            if requires_tunnel:
                msg += " (SSH tunnel required: ssh -L 6443:127.0.0.1:6443 <host> -N -f)"
            missing.append(msg)

    return missing


def ensure_namespace(namespace: str, kubeconfig: dict | None = None) -> bool:
    """Ensure the namespace exists, creating it if necessary.

    Args:
        namespace: Kubernetes namespace name
        kubeconfig: Optional kubeconfig dict to use

    Returns:
        True if namespace exists or was created
    """
    with KubeconfigContext(kubeconfig):
        try:
            # Check if namespace exists
            result = subprocess.run(
                ["kubectl", "get", "namespace", namespace],
                capture_output=True,
                check=False,
                timeout=10,
            )
            if result.returncode == 0:
                return True

            # Create namespace
            result = subprocess.run(
                ["kubectl", "create", "namespace", namespace],
                capture_output=True,
                check=False,
                timeout=10,
            )
            return result.returncode == 0
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False


def install_cert_manager(kubeconfig: dict | None = None) -> bool:
    """Install cert-manager for ACME TLS support.

    Args:
        kubeconfig: Optional kubeconfig dict to use

    Returns:
        True if cert-manager is installed or already present
    """
    with KubeconfigContext(kubeconfig):
        try:
            # Check if cert-manager is already installed
            result = subprocess.run(
                ["kubectl", "get", "namespace", "cert-manager"],
                capture_output=True,
                check=False,
                timeout=10,
            )
            if result.returncode == 0:
                console.print("[dim]cert-manager already installed[/dim]")
                return True

            console.print("[cyan]Installing cert-manager...[/cyan]")

            # Add jetstack repo
            subprocess.run(
                ["helm", "repo", "add", "jetstack", "https://charts.jetstack.io"],
                capture_output=True,
                check=False,
                timeout=30,
            )

            subprocess.run(
                ["helm", "repo", "update"],
                capture_output=True,
                check=False,
                timeout=60,
            )

            # Install cert-manager
            result = subprocess.run(
                [
                    "helm",
                    "install",
                    "cert-manager",
                    "jetstack/cert-manager",
                    "--namespace",
                    "cert-manager",
                    "--create-namespace",
                    "--set",
                    "installCRDs=true",
                    "--wait",
                    "--timeout",
                    "5m",
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=300,
            )
            if result.returncode == 0:
                console.print("[green]cert-manager installed successfully[/green]")
                return True
            else:
                console.print(f"[red]Failed to install cert-manager: {result.stderr}[/red]")
                return False
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            console.print(f"[red]Error installing cert-manager: {e}[/red]")
            return False


def ensure_cluster_issuer(acme_email: str, kubeconfig: dict | None = None) -> bool:
    """Ensure the letsencrypt-prod ClusterIssuer exists for ACME TLS.

    Args:
        acme_email: Email for Let's Encrypt registration
        kubeconfig: Optional kubeconfig dict to use

    Returns:
        True if the ClusterIssuer is ready
    """
    with KubeconfigContext(kubeconfig):
        try:
            # Check if ClusterIssuer already exists
            result = subprocess.run(
                ["kubectl", "get", "clusterissuer", "letsencrypt-prod"],
                capture_output=True,
                check=False,
                timeout=10,
            )
            if result.returncode == 0:
                return True

            console.print("[cyan]Creating letsencrypt-prod ClusterIssuer...[/cyan]")

            issuer_manifest = json.dumps({
                "apiVersion": "cert-manager.io/v1",
                "kind": "ClusterIssuer",
                "metadata": {"name": "letsencrypt-prod"},
                "spec": {
                    "acme": {
                        "email": acme_email,
                        "server": "https://acme-v02.api.letsencrypt.org/directory",
                        "privateKeySecretRef": {"name": "letsencrypt-prod-account-key"},
                        "solvers": [{"http01": {"ingress": {"ingressClassName": "traefik"}}}],
                    }
                },
            })

            result = subprocess.run(
                ["kubectl", "apply", "-f", "-"],
                input=issuer_manifest,
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )
            if result.returncode == 0:
                console.print("[green]ClusterIssuer created successfully[/green]")
                return True
            else:
                console.print(f"[red]Failed to create ClusterIssuer: {result.stderr}[/red]")
                return False
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            console.print(f"[red]Error creating ClusterIssuer: {e}[/red]")
            return False


MONITORING_NAMESPACE = "monitoring"


def _install_dcgm_exporter(kubeconfig: dict | None = None) -> bool:
    """Install NVIDIA DCGM Exporter for GPU metrics.

    Args:
        kubeconfig: Optional kubeconfig dict to use

    Returns:
        True if installed successfully or no GPU nodes exist
    """
    with KubeconfigContext(kubeconfig):
        try:
            # Check if any nodes have NVIDIA GPUs
            result = subprocess.run(
                ["kubectl", "get", "nodes", "-l", "nvidia.com/gpu=true", "-o", "name"],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            if result.returncode != 0 or not result.stdout.strip():
                console.print("[dim]No GPU nodes found, skipping DCGM exporter[/dim]")
                return True

            console.print("[cyan]Installing NVIDIA DCGM Exporter for GPU metrics...[/cyan]")

            # Add NVIDIA helm repo
            subprocess.run(
                ["helm", "repo", "add", "gpu-helm-charts", "https://nvidia.github.io/dcgm-exporter/helm-charts"],
                capture_output=True,
                check=False,
                timeout=30,
            )

            # Install DCGM exporter with ServiceMonitor for Prometheus
            values = """
serviceMonitor:
  enabled: true
  interval: 15s
  additionalLabels:
    release: prometheus
nodeSelector:
  nvidia.com/gpu: "true"
resources:
  requests:
    cpu: 100m
    memory: 256Mi
  limits:
    cpu: 500m
    memory: 512Mi
"""
            result = subprocess.run(
                [
                    "helm",
                    "upgrade",
                    "--install",
                    "dcgm-exporter",
                    "gpu-helm-charts/dcgm-exporter",
                    "--namespace",
                    MONITORING_NAMESPACE,
                    "-f",
                    "-",
                ],
                input=values,
                capture_output=True,
                text=True,
                check=False,
                timeout=300,
            )
            if result.returncode == 0:
                console.print("[green]DCGM Exporter installed[/green]")
                return True
            else:
                console.print(f"[yellow]DCGM Exporter installation failed: {result.stderr}[/yellow]")
                return False
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            console.print(f"[yellow]DCGM Exporter installation skipped: {e}[/yellow]")
            return False


def _import_gpu_dashboard(kubeconfig: dict | None = None) -> bool:
    """Import NVIDIA GPU dashboard into Grafana.

    Args:
        kubeconfig: Optional kubeconfig dict to use

    Returns:
        True if imported successfully
    """
    import urllib.request

    with KubeconfigContext(kubeconfig):
        try:
            # Download dashboard JSON from grafana.com
            dashboard_url = "https://grafana.com/api/dashboards/12239/revisions/2/download"
            with urllib.request.urlopen(dashboard_url, timeout=30) as response:
                dashboard_json = response.read().decode("utf-8")

            # Import via Grafana API (using kubectl port-forward)
            import_payload = f'''{{
                "dashboard": {dashboard_json},
                "overwrite": true,
                "inputs": [{{
                    "name": "DS_PROMETHEUS",
                    "type": "datasource",
                    "pluginId": "prometheus",
                    "value": "prometheus"
                }}],
                "folderId": 0
            }}'''

            # Use kubectl exec to call Grafana API from inside the cluster
            result = subprocess.run(
                [
                    "kubectl",
                    "run",
                    "grafana-import",
                    "--rm",
                    "-i",
                    "--restart=Never",
                    "--namespace",
                    MONITORING_NAMESPACE,
                    "--image=curlimages/curl:latest",
                    "--",
                    "curl",
                    "-s",
                    "-X",
                    "POST",
                    "http://prometheus-grafana:80/api/dashboards/import",
                    "-H",
                    "Content-Type: application/json",
                    "-d",
                    import_payload,
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
            )
            if "imported" in result.stdout.lower() or result.returncode == 0:
                console.print("[green]GPU dashboard imported[/green]")
                return True
            else:
                console.print("[dim]GPU dashboard import skipped[/dim]")
                return False
        except Exception as e:
            console.print(f"[dim]GPU dashboard import skipped: {e}[/dim]")
            return False


def install_monitoring(kubeconfig: dict | None = None) -> bool:
    """Install kube-prometheus-stack for monitoring.

    Installs in dedicated 'monitoring' namespace.
    Also installs DCGM exporter for GPU metrics if GPU nodes are present.

    Args:
        kubeconfig: Optional kubeconfig dict to use

    Returns:
        True if monitoring was installed successfully
    """
    with KubeconfigContext(kubeconfig):
        try:
            # Check if prometheus-grafana is already installed
            result = subprocess.run(
                ["kubectl", "get", "svc", "prometheus-grafana", "-n", MONITORING_NAMESPACE],
                capture_output=True,
                check=False,
                timeout=10,
            )
            if result.returncode == 0:
                console.print("[dim]Monitoring stack already installed[/dim]")
                # Still try to install DCGM exporter (idempotent)
                _install_dcgm_exporter(kubeconfig)
                return True

            console.print(f"[cyan]Installing monitoring stack in namespace '{MONITORING_NAMESPACE}'...[/cyan]")

            # Add prometheus-community repo
            subprocess.run(
                ["helm", "repo", "add", "prometheus-community", "https://prometheus-community.github.io/helm-charts"],
                capture_output=True,
                check=False,
                timeout=30,
            )

            subprocess.run(
                ["helm", "repo", "update"],
                capture_output=True,
                check=False,
                timeout=60,
            )

            # Install kube-prometheus-stack with anonymous access enabled
            result = subprocess.run(
                [
                    "helm",
                    "upgrade",
                    "--install",
                    "prometheus",
                    "prometheus-community/kube-prometheus-stack",
                    "--namespace",
                    MONITORING_NAMESPACE,
                    "--create-namespace",
                    "--set",
                    "grafana.adminPassword=admin",
                    "--set",
                    "grafana.grafana\\.ini.auth\\.anonymous.enabled=true",
                    "--set",
                    "grafana.grafana\\.ini.auth\\.anonymous.org_role=Admin",
                    "--set",
                    "grafana.grafana\\.ini.auth.disable_login_form=true",
                    "--wait",
                    "--timeout",
                    "10m",
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=600,
            )
            if result.returncode == 0:
                console.print("[green]Monitoring stack installed successfully[/green]")

                # Install DCGM exporter for GPU metrics
                _install_dcgm_exporter(kubeconfig)

                # Import GPU dashboard
                _import_gpu_dashboard(kubeconfig)

                console.print("[dim]Access Grafana with: linto grafana <profile>[/dim]")
                return True
            else:
                console.print(f"[red]Failed to install monitoring stack: {result.stderr}[/red]")
                return False
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            console.print(f"[red]Error installing monitoring stack: {e}[/red]")
            return False


def uninstall_monitoring(kubeconfig: dict | None = None) -> bool:
    """Uninstall kube-prometheus-stack and DCGM exporter.

    Args:
        kubeconfig: Optional kubeconfig dict to use

    Returns:
        True if monitoring was uninstalled successfully
    """
    with KubeconfigContext(kubeconfig):
        try:
            # Uninstall DCGM exporter first
            subprocess.run(
                [
                    "helm",
                    "uninstall",
                    "dcgm-exporter",
                    "--namespace",
                    MONITORING_NAMESPACE,
                ],
                capture_output=True,
                check=False,
                timeout=60,
            )

            # Uninstall prometheus stack
            result = subprocess.run(
                [
                    "helm",
                    "uninstall",
                    "prometheus",
                    "--namespace",
                    MONITORING_NAMESPACE,
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
            )
            if result.returncode == 0:
                console.print("[green]Monitoring stack uninstalled[/green]")
                return True
            return False
        except (subprocess.TimeoutExpired, FileNotFoundError):
            return False


def backup_tls_certificates(
    namespace: str,
    profile_name: str,
    base_dir: Path | None = None,
    kubeconfig: dict | None = None,
) -> bool:
    """Backup TLS certificates from cluster to local storage.

    Saves cert-manager Certificate and Secret resources to avoid
    hitting Let's Encrypt rate limits on redeployment.

    Args:
        namespace: Kubernetes namespace
        profile_name: Profile name for backup directory
        base_dir: Base directory for .linto folder
        kubeconfig: Optional kubeconfig dict to use

    Returns:
        True if backup succeeded or no certificates to backup
    """
    import json

    if base_dir is None:
        base_dir = Path.cwd()

    backup_dir = base_dir / ".linto" / "certs" / profile_name
    backup_dir.mkdir(parents=True, exist_ok=True)

    with KubeconfigContext(kubeconfig):
        try:
            # Get TLS secrets (created by cert-manager)
            result = subprocess.run(
                [
                    "kubectl",
                    "get",
                    "secrets",
                    "-n",
                    namespace,
                    "-l",
                    "controller.cert-manager.io/fao=true",
                    "-o",
                    "json",
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=30,
            )

            if result.returncode != 0:
                # Try alternative: get secrets of type kubernetes.io/tls
                result = subprocess.run(
                    [
                        "kubectl",
                        "get",
                        "secrets",
                        "-n",
                        namespace,
                        "--field-selector",
                        "type=kubernetes.io/tls",
                        "-o",
                        "json",
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=30,
                )

            if result.returncode == 0:
                secrets_data = json.loads(result.stdout)
                items = secrets_data.get("items", [])

                if items:
                    # Save secrets
                    secrets_file = backup_dir / "tls-secrets.json"
                    with open(secrets_file, "w") as f:
                        json.dump(secrets_data, f, indent=2)
                    console.print(f"[green]Backed up {len(items)} TLS certificate(s) to {backup_dir}[/green]")
                    return True
                else:
                    console.print("[dim]No TLS certificates found to backup[/dim]")
                    return True

            console.print("[dim]Could not retrieve TLS certificates for backup[/dim]")
            return True  # Not a failure - just no certs

        except Exception as e:
            console.print(f"[yellow]Warning: Certificate backup failed: {e}[/yellow]")
            return False


def restore_tls_certificates(
    namespace: str,
    profile_name: str,
    base_dir: Path | None = None,
    kubeconfig: dict | None = None,
) -> bool:
    """Restore TLS certificates from local backup to cluster.

    Args:
        namespace: Kubernetes namespace
        profile_name: Profile name for backup directory
        base_dir: Base directory for .linto folder
        kubeconfig: Optional kubeconfig dict to use

    Returns:
        True if restore succeeded or no backup exists
    """
    import json

    if base_dir is None:
        base_dir = Path.cwd()

    backup_dir = base_dir / ".linto" / "certs" / profile_name
    secrets_file = backup_dir / "tls-secrets.json"

    if not secrets_file.exists():
        console.print("[dim]No certificate backup found - will request new certificates[/dim]")
        return True

    with KubeconfigContext(kubeconfig):
        try:
            with open(secrets_file) as f:
                secrets_data = json.load(f)

            items = secrets_data.get("items", [])
            if not items:
                return True

            console.print(f"[cyan]Restoring {len(items)} TLS certificate(s) from backup...[/cyan]")

            for secret in items:
                # Update namespace in metadata
                secret["metadata"]["namespace"] = namespace
                # Remove resourceVersion and uid for re-creation
                secret["metadata"].pop("resourceVersion", None)
                secret["metadata"].pop("uid", None)
                secret["metadata"].pop("creationTimestamp", None)

                # Apply the secret
                secret_json = json.dumps(secret)
                result = subprocess.run(
                    ["kubectl", "apply", "-f", "-"],
                    input=secret_json,
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=30,
                )

                secret_name = secret.get("metadata", {}).get("name", "unknown")
                if result.returncode == 0:
                    console.print(f"[green]Restored certificate: {secret_name}[/green]")
                else:
                    console.print(f"[yellow]Could not restore {secret_name}: {result.stderr}[/yellow]")

            return True

        except Exception as e:
            console.print(f"[yellow]Warning: Certificate restore failed: {e}[/yellow]")
            return False


def get_service_tag(profile: ProfileConfig, service_name: str) -> str:
    """Get the tag for a specific service from profile.

    Checks service_tags first, falls back to image_tag.

    Args:
        profile: Profile configuration
        service_name: Service name (e.g., 'studio-api', 'linto-stt-whisper')

    Returns:
        Version tag for the service
    """
    return profile.service_tags.get(service_name, profile.image_tag)


def get_database_tag(profile: ProfileConfig, db_name: str) -> str:
    """Get the tag for a database from profile.

    Args:
        profile: Profile configuration
        db_name: Database name (e.g., 'studio-mongo', 'stt-redis', 'live-postgres')

    Returns:
        Version tag for the database
    """
    # Check for db-prefixed key first, then direct name
    tag = profile.service_tags.get(f"db-{db_name}")
    if tag:
        return tag
    # Default database versions (service-specific names)
    defaults = {
        # Studio
        "studio-mongo": "6.0.2",
        # STT
        "stt-mongo": "6.0.2",
        "stt-redis": "latest",
        # Live
        "live-postgres": "15-alpine",
        "live-mosquitto": "2",
        # LLM
        "llm-postgres": "15-alpine",
        "llm-redis": "latest",
    }
    return defaults.get(db_name, "latest")


def get_llm_service_tag(profile: ProfileConfig, service_name: str) -> str:
    """Get the tag for an LLM service from profile.

    Args:
        profile: Profile configuration
        service_name: LLM service name (e.g., 'vllm-openai')

    Returns:
        Version tag for the service
    """
    return profile.service_tags.get(f"llm-{service_name}", "latest")


def generate_global_values(profile: ProfileConfig, create_certificate: bool = True) -> dict[str, Any]:
    """Generate global values shared across all charts.

    Args:
        profile: Profile configuration
        create_certificate: Whether to create TLS certificate (only first chart should)

    Returns:
        Global values dictionary
    """
    tls_mode = profile.tls_mode.value if isinstance(profile.tls_mode, TLSMode) else profile.tls_mode
    tls_enabled = tls_mode != "off"

    global_values: dict[str, Any] = {
        "domain": profile.domain,
        "imageTag": profile.image_tag,
        "tls": {
            "enabled": tls_enabled,
            "mode": tls_mode,
        },
    }

    if tls_enabled:
        global_values["tls"]["secretName"] = profile.k3s_tls_secret_name
        global_values["tls"]["createCertificate"] = create_certificate

    if tls_mode == "acme" and profile.acme_email:
        global_values["tls"]["acmeEmail"] = profile.acme_email

    if profile.k3s_storage_class:
        global_values["storageClass"] = profile.k3s_storage_class

    # Storage configuration
    if profile.k3s_database_host_path or profile.k3s_files_host_path:
        global_values["storage"] = {}
        if profile.k3s_database_host_path:
            global_values["storage"]["database"] = {
                "hostPath": profile.k3s_database_host_path,
            }
            # Use node_selector if provided, otherwise convert node_role to selector
            if profile.k3s_database_node_selector:
                global_values["storage"]["database"]["nodeSelector"] = profile.k3s_database_node_selector
            elif profile.k3s_database_node_role:
                global_values["storage"]["database"]["nodeSelector"] = {"linto.ai/role": profile.k3s_database_node_role}
        if profile.k3s_files_host_path:
            global_values["storage"]["files"] = {
                "hostPath": profile.k3s_files_host_path,
            }

    return global_values


def generate_studio_values(profile: ProfileConfig) -> dict[str, Any]:
    """Generate values for linto-studio chart.

    Args:
        profile: Profile configuration

    Returns:
        Values dictionary for studio chart
    """
    # Studio creates the certificate (first chart)
    values: dict[str, Any] = {
        "global": generate_global_values(profile, create_certificate=True),
        "studioApi": {
            "enabled": True,
            "replicas": profile.studio_api_replicas,
            "image": {
                "tag": get_service_tag(profile, "studio-api"),
            },
            "env": {
                "SUPER_ADMIN_EMAIL": profile.super_admin_email,
                "SUPER_ADMIN_PWD": profile.super_admin_password or "",
                "CM_JWT_SECRET": profile.jwt_secret or "",
                "CM_REFRESH_SECRET": profile.jwt_refresh_secret or "",
            },
            "resources": {"limits": {}},
        },
        "studioFrontend": {
            "enabled": True,
            "replicas": 1,
            "image": {
                "tag": get_service_tag(profile, "studio-frontend"),
            },
            **({"env": profile.studio_frontend_env} if profile.studio_frontend_env else {}),
        },
        "studioWebsocket": {
            "enabled": True,
            "replicas": 1,
            "image": {
                "tag": get_service_tag(profile, "studio-websocket"),
            },
            "env": {
                "CM_JWT_SECRET": profile.jwt_secret or "",
            },
        },
        "mongodb": {
            "enabled": True,
            "image": {
                "tag": get_database_tag(profile, "studio-mongo"),
            },
            "persistence": {
                "enabled": True,
                "size": "10Gi",
            },
            "resources": {
                "limits": {},
            },
        },
    }

    # Initialize secrets dict before conditional blocks that may add secrets
    if "secrets" not in values["studioApi"]:
        values["studioApi"]["secrets"] = {}

    # Add service gateway URLs if STT/LLM enabled
    if profile.stt_enabled:
        values["studioApi"]["env"]["GATEWAY_SERVICES"] = "http://linto-stt-api-gateway:80"
    if profile.llm_enabled:
        values["studioApi"]["env"]["LLM_GATEWAY_SERVICES"] = "http://linto-llm-llm-api:80"
        if profile.llm_chat_service_id:
            values["studioApi"]["env"]["LLM_CHAT_SERVICE_ID"] = profile.llm_chat_service_id
        # Socket.IO Redis adapter (reuse LLM Redis for multi-instance scaling)
        values["studioApi"]["env"]["SOCKETIO_REDIS_HOST"] = "linto-llm-redis"
        values["studioApi"]["env"]["SOCKETIO_REDIS_PORT"] = "6379"
        if profile.llm_redis_password:
            values["studioApi"]["secrets"]["SOCKETIO_REDIS_PASSWORD"] = profile.llm_redis_password

    # Speaker identification: turn on the studio-api routes + frontend UI. The
    # endpoint is auto-discovered via the gateway (the diarization service whose
    # info reports speaker_identification=true), so SPEAKER_ID_SERVICE_ENDPOINT is
    # left unset. Qdrant itself is enabled in the linto-stt chart (generate_stt_values).
    if profile.speaker_identification_enabled and profile.stt_enabled:
        values["studioApi"]["env"]["ENABLE_SPEAKER_IDENTIFICATION"] = "true"
        if profile.speaker_id_api_token:
            values["studioApi"]["env"]["SPEAKER_ID_API_TOKEN"] = profile.speaker_id_api_token
        if profile.speaker_id_consent_version:
            values["studioApi"]["env"]["SPEAKER_ID_CONSENT_VERSION"] = profile.speaker_id_consent_version
        values["studioFrontend"].setdefault("env", {})[
            "VUE_APP_ENABLE_SPEAKER_IDENTIFICATION"
        ] = "true"

    if profile.k3s_storage_class:
        values["mongodb"]["persistence"]["storageClass"] = profile.k3s_storage_class

    # Determine URL scheme based on TLS mode
    tls_mode = profile.tls_mode.value if isinstance(profile.tls_mode, TLSMode) else profile.tls_mode
    scheme = "https" if tls_mode != "off" else "http"

    # Default organization permissions override (image defaults to upload,summary,session)
    if profile.organization_default_permissions is not None:
        values["studioApi"]["env"]["ORGANIZATION_DEFAULT_PERMISSIONS"] = (
            profile.organization_default_permissions
        )

    # SMTP configuration
    if profile.smtp_enabled:
        values["studioApi"]["env"]["SMTP_HOST"] = profile.smtp_host or ""
        values["studioApi"]["env"]["SMTP_PORT"] = str(profile.smtp_port)
        values["studioApi"]["env"]["SMTP_SECURE"] = str(profile.smtp_secure).lower()
        values["studioApi"]["env"]["SMTP_REQUIRE_TLS"] = str(profile.smtp_require_tls).lower()
        values["studioApi"]["env"]["SMTP_AUTH"] = profile.smtp_auth or ""
        values["studioApi"]["env"]["NO_REPLY_EMAIL"] = profile.smtp_no_reply_email or ""
        values["studioApi"]["secrets"]["SMTP_PSWD"] = profile.smtp_password or ""

    # Google OIDC
    if profile.oidc_google_enabled:
        values["studioApi"]["env"]["OIDC_GOOGLE_ENABLED"] = "true"
        values["studioApi"]["env"]["GOOGLE_CLIENT_ID"] = profile.oidc_google_client_id or ""
        values["studioApi"]["env"]["GOOGLE_OIDC_CALLBACK_URI"] = (
            f"{scheme}://{profile.domain}/cm-api/auth/oidc/google/cb"
        )
        values["studioApi"]["secrets"]["GOOGLE_CLIENT_SECRET"] = profile.oidc_google_client_secret or ""

    # GitHub OIDC
    if profile.oidc_github_enabled:
        values["studioApi"]["env"]["OIDC_GITHUB_ENABLED"] = "true"
        values["studioApi"]["env"]["GITHUB_CLIENT_ID"] = profile.oidc_github_client_id or ""
        values["studioApi"]["env"]["GITHUB_OIDC_CALLBACK_URI"] = (
            f"{scheme}://{profile.domain}/cm-api/auth/oidc/github/cb"
        )
        values["studioApi"]["secrets"]["GITHUB_CLIENT_SECRET"] = profile.oidc_github_client_secret or ""

    # Native OIDC (Linagora)
    if profile.oidc_native_type:
        values["studioApi"]["env"]["OIDC_TYPE"] = profile.oidc_native_type
        values["studioApi"]["env"]["OIDC_CLIENT_ID"] = profile.oidc_native_client_id or ""
        values["studioApi"]["env"]["OIDC_CALLBACK_URI"] = f"{scheme}://{profile.domain}/cm-api/auth/oidc/cb"
        values["studioApi"]["env"]["OIDC_URL"] = profile.oidc_native_url or ""
        values["studioApi"]["env"]["OIDC_SCOPE"] = profile.oidc_native_scope
        values["studioApi"]["secrets"]["OIDC_CLIENT_SECRET"] = profile.oidc_native_client_secret or ""
        # Native OIDC also uses NO_REPLY_EMAIL
        if profile.smtp_no_reply_email and "NO_REPLY_EMAIL" not in values["studioApi"]["env"]:
            values["studioApi"]["env"]["NO_REPLY_EMAIL"] = profile.smtp_no_reply_email

    return values


def generate_stt_values(profile: ProfileConfig) -> dict[str, Any]:
    """Generate values for linto-stt chart.

    Args:
        profile: Profile configuration

    Returns:
        Values dictionary for stt chart
    """
    gpu_enabled = profile.gpu_mode != GPUMode.NONE
    gpu_count = profile.gpu_count if gpu_enabled else 0

    values: dict[str, Any] = {
        "global": generate_global_values(profile, create_certificate=False),
        "apiGateway": {
            "enabled": True,
            "replicas": 1,
            "image": {
                "tag": get_service_tag(profile, "linto-api-gateway"),
            },
            "env": {
                "COMPONENTS": "ApiWatcher,WebServer",
            },
            "ingress": {
                "enabled": False,  # Internal only
            },
        },
        "whisper": {
            "enabled": True,
            "replicas": 1,
            "image": {
                "tag": get_service_tag(profile, "linto-transcription-service"),
            },
            "env": {
                "SERVICE_NAME": "whisper-large-v3-turbo",
                "GATEWAY_DESCRIPTION": '{"en": "Recommended (Whisper Large V3)", "fr": "Recommandé (Whisper Large V3)"}',
                "BROKER_PASS": profile.redis_password or "",
                "SECURITY_LEVEL": profile.security_level,
            },
            "ingress": {
                "enabled": False,  # Internal only
            },
        },
        "whisperWorkers": {
            "enabled": True,
            "image": {
                "tag": get_service_tag(profile, "linto-stt-whisper"),
            },
            "env": {
                "SERVICE_NAME": "whisper-large-v3-turbo",
                "BROKER_PASS": profile.redis_password or "",
                "DEVICE": "cuda" if gpu_enabled else "cpu",
                "SECURITY_LEVEL": profile.security_level,
            },
        },
        "nemo": {
            "enabled": profile.stt_enabled and any(v.value.startswith("nemo") for v in profile.streaming_stt_variants),
            "replicas": 1,
            "image": {
                "tag": get_service_tag(profile, "linto-transcription-service"),
            },
            "env": {
                "SERVICE_NAME": "nemo-parakeet-tdt-v3",
                "GATEWAY_DESCRIPTION": '{"en": "Fast (Parakeet)", "fr": "Rapide (Parakeet)"}',
                "BROKER_PASS": profile.redis_password or "",
                "SECURITY_LEVEL": profile.security_level,
            },
            "ingress": {
                "enabled": False,
            },
        },
        "nemoWorkers": {
            "enabled": profile.stt_enabled and any(v.value.startswith("nemo") for v in profile.streaming_stt_variants),
            "image": {
                "tag": get_service_tag(profile, "linto-stt-nemo"),
            },
            "env": {
                "SERVICE_NAME": "nemo-parakeet-tdt-v3",
                "BROKER_PASS": profile.redis_password or "",
                "DEVICE": "cuda" if gpu_enabled else "cpu",
                "SECURITY_LEVEL": profile.security_level,
            },
        },
        "diarization": {
            "enabled": True,
            "image": {
                "tag": get_service_tag(profile, "linto-diarization-pyannote"),
            },
            "env": {
                "SERVICE_NAME": "stt-diarization-pyannote",
                "QUEUE_NAME": "diarization-pyannote",
                "BROKER_PASS": profile.redis_password or "",
                "DEVICE": "cuda" if gpu_enabled else "cpu",
            },
        },
        "redis": {
            "enabled": True,
            "image": {
                "tag": get_database_tag(profile, "stt-redis"),
            },
            "password": profile.redis_password or "",
            "persistence": {
                "enabled": True,
                "size": "5Gi",
            },
            "resources": {
                "limits": {},
            },
        },
        "mongodb": {
            "enabled": True,
            "image": {
                "tag": get_database_tag(profile, "stt-mongo"),
            },
            "persistence": {
                "enabled": True,
                "size": "10Gi",
            },
            "resources": {
                "limits": {},
            },
        },
    }

    # GPU configuration: use replicasPerGpu for multi-GPU setups
    if gpu_enabled and gpu_count > 1:
        # Create array [1, 1, ...] with one replica per GPU
        replicas_per_gpu = [1] * gpu_count
        values["whisperWorkers"]["replicasPerGpu"] = replicas_per_gpu
        values["nemoWorkers"]["replicasPerGpu"] = replicas_per_gpu
        values["diarization"]["replicasPerGpu"] = replicas_per_gpu
    else:
        # Single GPU or CPU: use simple replicas
        values["whisperWorkers"]["replicas"] = 1
        values["whisperWorkers"]["resources"] = {}
        values["nemoWorkers"]["replicas"] = 1
        values["nemoWorkers"]["resources"] = {}
        values["diarization"]["replicas"] = 1
        values["diarization"]["resources"] = {}

    # Speaker identification: enable the Qdrant voiceprint store. The chart wires
    # QDRANT_HOST/PORT into the diarization workers and stores on hostPath when
    # global.storage.database.hostPath is set (else a PVC), so nothing else to do.
    if profile.speaker_identification_enabled and profile.stt_enabled:
        values["qdrant"] = {"enabled": True}
        if profile.speaker_id_api_token:
            # Token guarding the speaker-id HTTP endpoint on the transcription service
            values["whisper"]["env"]["SPEAKER_ID_API_TOKEN"] = profile.speaker_id_api_token

    if profile.k3s_storage_class:
        values["redis"]["persistence"]["storageClass"] = profile.k3s_storage_class
        values["mongodb"]["persistence"]["storageClass"] = profile.k3s_storage_class

    return values


def generate_live_values(profile: ProfileConfig) -> dict[str, Any]:
    """Generate values for linto-live chart.

    Args:
        profile: Profile configuration

    Returns:
        Values dictionary for live chart
    """
    gpu_enabled = profile.gpu_mode != GPUMode.NONE

    values: dict[str, Any] = {
        "global": generate_global_values(profile, create_certificate=False),
        "migration": {
            "enabled": True,
            "image": {
                "tag": get_service_tag(profile, "studio-plugins-migration"),
            },
        },
        "sessionApi": {
            "enabled": True,
            "replicas": 1,
            "image": {
                "tag": get_service_tag(profile, "studio-plugins-sessionapi"),
            },
            "env": {
                "DB_PASSWORD": profile.session_postgres_password or "",
                "SECURITY_CRYPT_KEY": profile.session_crypt_key or "",
            },
            "resources": {"limits": {}},
        },
        "sessionScheduler": {
            "enabled": True,
            "replicas": 1,
            "image": {
                "tag": get_service_tag(profile, "studio-plugins-scheduler"),
            },
            "env": {
                "DB_PASSWORD": profile.session_postgres_password or "",
            },
        },
        "sessionTranscriber": {
            "enabled": True,
            "replicas": profile.session_transcriber_replicas,
            "image": {
                "tag": get_service_tag(profile, "studio-plugins-transcriber"),
            },
            "env": {
                "SECURITY_CRYPT_KEY": profile.session_crypt_key or "",
            },
            "resources": {"limits": {}},
        },
        "postgres": {
            "enabled": True,
            "image": {
                "tag": get_database_tag(profile, "live-postgres"),
            },
            "password": profile.session_postgres_password or "",
            "persistence": {
                "enabled": True,
                "size": "10Gi",
            },
            "resources": {
                "limits": {},
            },
        },
        "broker": {
            "enabled": True,
            "image": {
                "tag": get_database_tag(profile, "live-mosquitto"),
            },
            "resources": {
                "limits": {},
            },
        },
        "translator": {
            "enabled": profile.translator_enabled,
            "replicas": 1,
            "image": {
                "tag": get_service_tag(profile, "studio-plugins-translator"),
            },
            "env": {
                "TRANSLATOR_NAME": profile.translator_name or "gemma",
                "TRANSLATION_PROVIDER": profile.translator_provider or "translategemma",
                "TRANSLATEGEMMA_ENDPOINT": profile.translator_endpoint or "",
                "TRANSLATEGEMMA_MODEL": profile.translator_model or "Infomaniak-AI/vllm-translategemma-4b-it",
                "PARTIAL_DEBOUNCE_MS": "300",
            },
        },
        "streamingStt": {},
    }

    # Add streaming STT variants with version tags
    variant_image_map = {
        StreamingSTTVariant.WHISPER: "linto-stt-whisper",
        StreamingSTTVariant.KALDI_FRENCH: "linto-stt-kaldi",
        StreamingSTTVariant.NEMO_FRENCH: "linto-stt-nemo",
        StreamingSTTVariant.NEMO_ENGLISH: "linto-stt-nemo",
        StreamingSTTVariant.NEMO_TDT_V3: "linto-stt-nemo",
        StreamingSTTVariant.KYUTAI: "kyutai-moshi-stt-server-cuda",
    }

    for variant in profile.streaming_stt_variants:
        variant_key = variant.value.replace("-", "_")
        variant_config: dict[str, Any] = {
            "enabled": True,
            "replicas": 1,
            "image": {
                "tag": get_service_tag(profile, variant_image_map.get(variant, "linto-stt-whisper")),
            },
        }

        # GPU services need resource limits
        gpu_services = [
            StreamingSTTVariant.WHISPER,
            StreamingSTTVariant.NEMO_FRENCH,
            StreamingSTTVariant.NEMO_ENGLISH,
            StreamingSTTVariant.NEMO_TDT_V3,
            StreamingSTTVariant.KYUTAI,
        ]
        if variant in gpu_services and gpu_enabled:
            variant_config["resources"] = {
                "limits": {"nvidia.com/gpu": "1"},
                "requests": {"nvidia.com/gpu": "1"},
            }

        # Kyutai needs GPU architecture
        if variant == StreamingSTTVariant.KYUTAI and profile.kyutai_gpu_architecture:
            variant_config["gpuArchitecture"] = profile.kyutai_gpu_architecture.value

        values["streamingStt"][variant_key] = variant_config

    if profile.k3s_storage_class:
        values["postgres"]["persistence"]["storageClass"] = profile.k3s_storage_class

    return values


def generate_llm_values(profile: ProfileConfig) -> dict[str, Any]:
    """Generate values for linto-llm chart.

    Args:
        profile: Profile configuration

    Returns:
        Values dictionary for llm chart
    """
    gpu_enabled = profile.gpu_mode != GPUMode.NONE
    tls_mode = profile.tls_mode.value if isinstance(profile.tls_mode, TLSMode) else profile.tls_mode
    protocol = "https" if tls_mode != "off" else "http"

    # Determine OpenAI API base
    openai_api_base = profile.openai_api_base
    if profile.vllm_enabled and not openai_api_base:
        openai_api_base = "http://vllm-service:8000/v1"

    values: dict[str, Any] = {
        "global": generate_global_values(profile, create_certificate=False),
        "llmGatewayApi": {
            "enabled": True,
            "replicas": 1,
            "image": {
                "tag": get_service_tag(profile, "llm-gateway"),
            },
            "env": {
                "REDIS_PASSWORD": profile.llm_redis_password or "",
                "ENCRYPTION_KEY": profile.llm_encryption_key or "",
                "DEBUG": "false",
                "CORS_ORIGINS": f"{protocol}://{profile.domain}",
            },
        },
        "celeryWorker": {
            "enabled": True,
            "replicas": 1,
            "image": {
                "tag": get_service_tag(profile, "llm-gateway"),
            },
        },
        "llmGatewayFrontend": {
            "enabled": True,
            "replicas": 1,
            "image": {
                "tag": get_service_tag(profile, "llm-gateway-frontend"),
            },
            "basicAuth": {
                "enabled": True,
                "username": profile.llm_admin_username,
                "password": profile.llm_admin_password or "",
            },
        },
        "postgres": {
            "enabled": True,
            "image": {
                "tag": get_database_tag(profile, "llm-postgres"),
            },
            "password": profile.llm_postgres_password or "",
            "persistence": {
                "enabled": True,
                "size": "10Gi",
            },
            "resources": {
                "limits": {},
            },
        },
        "redis": {
            "enabled": True,
            "image": {
                "tag": get_database_tag(profile, "llm-redis"),
            },
            "password": profile.llm_redis_password or "",
            "persistence": {
                "enabled": True,
                "size": "5Gi",
            },
            "resources": {
                "limits": {},
            },
        },
        "vllm": {
            "enabled": profile.vllm_enabled,
            "replicas": 1,
            "image": {
                "tag": get_llm_service_tag(profile, "vllm-openai"),
            },
            "resources": {},
        },
    }

    # Add GPU resources for vLLM
    if profile.vllm_enabled and gpu_enabled:
        values["vllm"]["resources"] = {
            "limits": {"nvidia.com/gpu": "1"},
            "requests": {"nvidia.com/gpu": "1"},
        }

    if profile.k3s_storage_class:
        values["postgres"]["persistence"]["storageClass"] = profile.k3s_storage_class
        values["redis"]["persistence"]["storageClass"] = profile.k3s_storage_class

    return values


def generate_vllm_values(profile: ProfileConfig) -> dict:
    """Generate Helm values for the linto-vllm chart."""
    global_values = generate_global_values(profile, create_certificate=False)

    instances = {}
    for inst in profile.vllm_instances:
        instance_values = {
            "enabled": inst.enabled,
            "image": {
                "repository": inst.image.rsplit(":", 1)[0] if ":" in inst.image else inst.image,
                "tag": inst.image.rsplit(":", 1)[1] if ":" in inst.image else "",
            },
            "model": inst.model,
            "gpuMemoryUtilization": str(inst.gpu_memory_utilization),
            "replicas": 1,
            "service": {"port": 8000},
            "resources": {
                "limits": {"nvidia.com/gpu": "1", "memory": "16Gi"},
                "requests": {"nvidia.com/gpu": "1", "memory": "4Gi"},
            },
        }
        if inst.model_cache_path:
            instance_values["modelCachePath"] = inst.model_cache_path
        if inst.extra_args:
            instance_values["extraArgs"] = inst.extra_args
        if inst.extra_pip_packages:
            instance_values["extraPipPackages"] = inst.extra_pip_packages
        if inst.node_selector:
            instance_values["nodeSelector"] = inst.node_selector
        if inst.tolerations:
            instance_values["tolerations"] = inst.tolerations

        instances[inst.name] = instance_values

    return {
        "global": global_values,
        "instances": instances,
    }


def generate_values(profile: ProfileConfig, chart: str) -> dict[str, Any]:
    """Generate values.yaml content for a specific chart.

    Args:
        profile: Profile configuration
        chart: Chart name (studio, stt, live, llm)

    Returns:
        Values dictionary
    """
    if chart == "studio":
        return generate_studio_values(profile)
    elif chart == "stt":
        return generate_stt_values(profile)
    elif chart == "live":
        return generate_live_values(profile)
    elif chart == "llm":
        return generate_llm_values(profile)
    elif chart == "linto-vllm":
        return generate_vllm_values(profile)
    else:
        raise ValueError(f"Unknown chart: {chart}")


def render_k3s(profile: ProfileConfig, output_dir: Path) -> dict[str, Path]:
    """Generate all values files for enabled services.

    Args:
        profile: Profile configuration
        output_dir: Output directory for values files

    Returns:
        Dictionary mapping chart names to values file paths
    """
    values_dir = output_dir / "values"
    values_dir.mkdir(parents=True, exist_ok=True)

    generated_files: dict[str, Path] = {}

    # Generate studio values
    if profile.studio_enabled:
        values = generate_studio_values(profile)
        values_path = values_dir / "studio-values.yaml"
        with values_path.open("w") as f:
            yaml.dump(values, f, default_flow_style=False, sort_keys=False)
        generated_files["studio"] = values_path

    # Generate STT values
    if profile.stt_enabled:
        values = generate_stt_values(profile)
        values_path = values_dir / "stt-values.yaml"
        with values_path.open("w") as f:
            yaml.dump(values, f, default_flow_style=False, sort_keys=False)
        generated_files["stt"] = values_path

    # Generate Live values
    if profile.live_session_enabled:
        values = generate_live_values(profile)
        values_path = values_dir / "live-values.yaml"
        with values_path.open("w") as f:
            yaml.dump(values, f, default_flow_style=False, sort_keys=False)
        generated_files["live"] = values_path

    # Generate LLM values
    if profile.llm_enabled:
        values = generate_llm_values(profile)
        values_path = values_dir / "llm-values.yaml"
        with values_path.open("w") as f:
            yaml.dump(values, f, default_flow_style=False, sort_keys=False)
        generated_files["llm"] = values_path

    # Generate vLLM values
    if profile.vllm_instances:
        values = generate_vllm_values(profile)
        values_path = values_dir / "vllm-values.yaml"
        with values_path.open("w") as f:
            yaml.dump(values, f, default_flow_style=False, sort_keys=False)
        generated_files["vllm"] = values_path

    return generated_files


def generate_k3s(
    profile_name: str,
    output_dir: str | None = None,
    base_dir: Path | None = None,
) -> Path:
    """Generate Helm values files for a profile.

    Args:
        profile_name: Name of the profile to generate
        output_dir: Optional output directory path
        base_dir: Base directory for .linto folder

    Returns:
        Path to the output directory
    """
    if base_dir is None:
        base_dir = Path.cwd()

    # Load profile
    profile = load_profile(profile_name, base_dir)

    # Ensure secrets are populated and save back
    profile = generate_secrets(profile)
    save_profile(profile, base_dir)

    # Determine output directory
    if output_dir:
        k3s_dir = Path(output_dir)
    else:
        k3s_dir = base_dir / ".linto" / "render" / "k3s" / profile_name

    k3s_dir.mkdir(parents=True, exist_ok=True)

    # Generate values files
    generated_files = render_k3s(profile, k3s_dir)

    # Print summary
    _print_summary(profile, k3s_dir, generated_files)

    return k3s_dir


def _print_summary(
    profile: ProfileConfig,
    output_dir: Path,
    generated_files: dict[str, Path],
) -> None:
    """Print a summary table of the generated configuration."""
    table = Table(title="K3s Deployment Summary")
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="green")

    tls_mode = profile.tls_mode.value if isinstance(profile.tls_mode, TLSMode) else profile.tls_mode

    table.add_row("Profile", profile.name)
    table.add_row("Backend", "Kubernetes (k3s/Helm)")
    table.add_row("Namespace", profile.k3s_namespace)
    table.add_row("Domain", profile.domain)
    table.add_row("Image Tag", profile.image_tag)
    table.add_row("TLS Mode", tls_mode)
    table.add_row("Storage Class", profile.k3s_storage_class or "(default)")
    table.add_row("Studio Enabled", "Yes" if profile.studio_enabled else "No")
    table.add_row("STT Enabled", "Yes" if profile.stt_enabled else "No")
    table.add_row("Live Session Enabled", "Yes" if profile.live_session_enabled else "No")
    table.add_row("LLM Enabled", "Yes" if profile.llm_enabled else "No")
    table.add_row("Admin Email", profile.super_admin_email)
    table.add_row("Output", str(output_dir))

    console.print(table)

    # Print generated files
    console.print("\n[bold]Generated values files:[/bold]")
    for chart, path in generated_files.items():
        console.print(f"  - {chart}: {path}")


def apply_k3s(profile_name: str, base_dir: Path | None = None) -> None:
    """Apply a deployment profile using Helm.

    Args:
        profile_name: Name of the profile to apply
        base_dir: Base directory for .linto folder

    Raises:
        ValidationError: If deployment fails
    """
    if base_dir is None:
        base_dir = Path.cwd()

    # Load profile
    profile = load_profile(profile_name, base_dir)
    namespace = profile.k3s_namespace
    kubeconfig = profile.kubeconfig

    # Check prerequisites (using profile's kubeconfig)
    missing = check_k3s_prerequisites(profile)
    if missing:
        raise ValidationError(
            "K3S_PREREQUISITES_MISSING",
            f"Missing prerequisites: {', '.join(missing)}",
        )

    # All kubectl/helm operations use the profile's kubeconfig
    with KubeconfigContext(kubeconfig):
        # Ensure namespace exists
        if not ensure_namespace(namespace, kubeconfig):
            raise ValidationError(
                "NAMESPACE_CREATION_FAILED",
                f"Failed to create namespace '{namespace}'",
            )

        # Install cert-manager and ClusterIssuer if using ACME
        tls_mode = profile.tls_mode.value if isinstance(profile.tls_mode, TLSMode) else profile.tls_mode
        if tls_mode == "acme" and profile.k3s_install_cert_manager:
            if not install_cert_manager(kubeconfig):
                console.print("[yellow]Warning: cert-manager installation failed[/yellow]")
            else:
                ensure_cluster_issuer(profile.acme_email, kubeconfig)

        # Restore TLS certificates from backup (if available)
        if tls_mode == "acme":
            restore_tls_certificates(namespace, profile_name, base_dir, kubeconfig)

        # Always regenerate values to ensure profile changes are applied
        k3s_dir = base_dir / ".linto" / "render" / "k3s" / profile_name
        values_dir = k3s_dir / "values"
        generate_k3s(profile_name, base_dir=base_dir)

        console.print(f"[cyan]Deploying to namespace '{namespace}'...[/cyan]")

        # Deploy each enabled chart
        charts_to_deploy = []
        if profile.studio_enabled:
            charts_to_deploy.append(("linto-studio", "studio-values.yaml"))
        if profile.stt_enabled:
            charts_to_deploy.append(("linto-stt", "stt-values.yaml"))
        if profile.live_session_enabled:
            charts_to_deploy.append(("linto-live", "live-values.yaml"))
        if profile.llm_enabled:
            charts_to_deploy.append(("linto-llm", "llm-values.yaml"))
        if profile.vllm_instances:
            charts_to_deploy.append(("linto-vllm", "vllm-values.yaml"))

        for chart_name, values_file in charts_to_deploy:
            chart_path = get_charts_dir() / chart_name
            values_path = values_dir / values_file

            if not chart_path.exists():
                console.print(f"[red]Chart not found: {chart_path}[/red]")
                continue

            if not values_path.exists():
                console.print(f"[yellow]Values file not found: {values_path}[/yellow]")
                continue

            release_name = f"linto-{chart_name.replace('linto-', '')}"

            console.print(f"[cyan]Installing/upgrading {chart_name}...[/cyan]")

            try:
                result = run_cmd(
                    [
                        "helm",
                        "upgrade",
                        "--install",
                        release_name,
                        str(chart_path),
                        "--namespace",
                        namespace,
                        "--values",
                        str(values_path),
                        "--wait",
                        "--timeout",
                        "10m",
                    ],
                    check=False,
                    timeout=600,
                )

                if result.returncode != 0:
                    console.print(f"[red]Failed to deploy {chart_name}: {result.stderr}[/red]")
                else:
                    console.print(f"[green]{chart_name} deployed successfully[/green]")
            except subprocess.TimeoutExpired:
                console.print(f"[red]{chart_name} deployment timed out[/red]")

        # Deploy monitoring if enabled
        if profile.monitoring_enabled:
            if not install_monitoring(kubeconfig):
                console.print("[yellow]Warning: Monitoring installation failed[/yellow]")

    console.print("[green]Deployment complete![/green]")
    console.print(f"[cyan]Access at: https://{profile.domain}[/cyan]")
    if profile.monitoring_enabled:
        console.print(f"[cyan]Access Grafana with: linto grafana {profile_name}[/cyan]")


def destroy_k3s(
    profile_name: str,
    remove_files: bool = False,
    remove_volumes: bool = False,
    base_dir: Path | None = None,
) -> None:
    """Stop and remove a k3s deployment.

    Args:
        profile_name: Name of the profile to destroy
        remove_files: Whether to remove generated files
        remove_volumes: Whether to remove PVCs
        base_dir: Base directory for .linto folder
    """
    if base_dir is None:
        base_dir = Path.cwd()

    # Load profile
    profile = load_profile(profile_name, base_dir)
    namespace = profile.k3s_namespace
    kubeconfig = profile.kubeconfig

    # Check prerequisites (using profile's kubeconfig)
    missing = check_k3s_prerequisites(profile)
    if missing:
        raise ValidationError(
            "K3S_PREREQUISITES_MISSING",
            f"Missing prerequisites: {', '.join(missing)}",
        )

    # All kubectl/helm operations use the profile's kubeconfig
    with KubeconfigContext(kubeconfig):
        # Backup TLS certificates before destroying (to avoid Let's Encrypt rate limits)
        tls_mode = profile.tls_mode.value if isinstance(profile.tls_mode, TLSMode) else profile.tls_mode
        if tls_mode == "acme":
            console.print("[cyan]Backing up TLS certificates...[/cyan]")
            backup_tls_certificates(namespace, profile_name, base_dir, kubeconfig)

        console.print(f"[yellow]Removing deployment from namespace '{namespace}'...[/yellow]")

        # Uninstall monitoring if it was deployed
        if profile.monitoring_enabled:
            uninstall_monitoring(kubeconfig)

        # Uninstall each chart
        charts = ["linto-studio", "linto-stt", "linto-live", "linto-llm"]
        for chart_name in charts:
            release_name = f"linto-{chart_name.replace('linto-', '')}"

            try:
                result = run_cmd(
                    [
                        "helm",
                        "uninstall",
                        release_name,
                        "--namespace",
                        namespace,
                    ],
                    check=False,
                    timeout=120,
                )
                if result.returncode == 0:
                    console.print(f"[green]Uninstalled {release_name}[/green]")
            except subprocess.TimeoutExpired:
                console.print(f"[red]{release_name} uninstall timed out[/red]")

        # Remove PVCs if requested
        if remove_volumes:
            console.print("[yellow]Removing PVCs...[/yellow]")
            try:
                subprocess.run(
                    [
                        "kubectl",
                        "delete",
                        "pvc",
                        "--all",
                        "--namespace",
                        namespace,
                    ],
                    capture_output=True,
                    check=False,
                    timeout=120,
                )
                console.print("[green]PVCs removed[/green]")
            except subprocess.TimeoutExpired:
                console.print("[red]PVC removal timed out[/red]")

    # Remove generated files if requested
    if remove_files:
        import shutil

        k3s_dir = base_dir / ".linto" / "render" / "k3s" / profile_name
        if k3s_dir.exists():
            shutil.rmtree(k3s_dir)
            console.print(f"[yellow]Removed generated files in {k3s_dir}[/yellow]")

    console.print("[green]Deployment removed.[/green]")


def status_k3s(
    profile_name: str,
    base_dir: Path | None = None,
) -> list[dict]:
    """Get status of deployed services.

    Args:
        profile_name: Name of the profile
        base_dir: Base directory for .linto folder

    Returns:
        List of service status dicts
    """
    if base_dir is None:
        base_dir = Path.cwd()

    # Load profile
    profile = load_profile(profile_name, base_dir)
    namespace = profile.k3s_namespace
    kubeconfig = profile.kubeconfig

    # Check prerequisites (using profile's kubeconfig)
    missing = check_k3s_prerequisites(profile)
    if missing:
        raise ValidationError(
            "K3S_PREREQUISITES_MISSING",
            f"Missing prerequisites: {', '.join(missing)}",
        )

    services = []

    # All kubectl/helm operations use the profile's kubeconfig
    with KubeconfigContext(kubeconfig):
        try:
            # Get helm releases
            result = run_cmd(
                [
                    "helm",
                    "list",
                    "--namespace",
                    namespace,
                    "--output",
                    "json",
                ],
                check=False,
                timeout=30,
            )

            if result.returncode == 0 and result.stdout.strip():
                import json

                releases = json.loads(result.stdout)
                for release in releases:
                    services.append(
                        {
                            "name": release.get("name", "unknown"),
                            "status": release.get("status", "unknown"),
                            "revision": release.get("revision", "0"),
                            "chart": release.get("chart", "unknown"),
                        }
                    )

            # Get pods
            result = run_cmd(
                [
                    "kubectl",
                    "get",
                    "pods",
                    "--namespace",
                    namespace,
                    "-o",
                    "json",
                ],
                check=False,
                timeout=30,
            )

            if result.returncode == 0 and result.stdout.strip():
                import json

                pods_data = json.loads(result.stdout)
                # NOTE: do not seed the log-targets cache here — status only
                # fetches the linto namespace, which would shrink a richer
                # multi-namespace cache populated by `linto logs <profile>`.
                for pod in pods_data.get("items", []):
                    pod_name = pod.get("metadata", {}).get("name", "unknown")
                    creation_timestamp = pod.get("metadata", {}).get("creationTimestamp")
                    phase = pod.get("status", {}).get("phase", "unknown")

                    # Get detailed status from containerStatuses
                    detailed_status = None
                    container_statuses = pod.get("status", {}).get("containerStatuses", [])
                    for cs in container_statuses:
                        state = cs.get("state", {})
                        if "waiting" in state:
                            reason = state["waiting"].get("reason", "Waiting")
                            detailed_status = reason
                            break
                        elif "terminated" in state:
                            reason = state["terminated"].get("reason", "Terminated")
                            detailed_status = reason
                            break

                    # Check init containers too (image pull often happens there)
                    if not detailed_status:
                        init_statuses = pod.get("status", {}).get("initContainerStatuses", [])
                        for cs in init_statuses:
                            state = cs.get("state", {})
                            if "waiting" in state:
                                reason = state["waiting"].get("reason", "Waiting")
                                detailed_status = f"Init:{reason}"
                                break

                    # Check if pod is terminating (deletionTimestamp set)
                    if pod.get("metadata", {}).get("deletionTimestamp"):
                        detailed_status = "Terminating"

                    services.append(
                        {
                            "name": f"pod/{pod_name}",
                            "status": phase,
                            "detailed_status": detailed_status,
                            "creation_timestamp": creation_timestamp,
                            "type": "pod",
                        }
                    )

        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass

    return services


@dataclass
class LogTarget:
    """A logical log target across any namespace, with its kubectl selector pre-built."""

    namespace: str
    instance: str
    instance_short: str
    component: str
    label_selector: str
    pod_count: int
    pods: list[str] = field(default_factory=list)


def _targets_cache_path(profile_name: str, base_dir: Path) -> Path:
    return base_dir / ".linto" / "cache" / f"{profile_name}-k8s.json"


def _resolve_pod_identity(
    labels: dict[str, str],
) -> tuple[str | None, str, str] | None:
    """Pull a (instance, component, label_selector) out of a pod's labels.

    Tries Helm-style conventions first, then falls back to `app`/`k8s-app`/
    `name` for system pods (coredns, nvidia-device-plugin, …).
    Returns None when no usable identity exists.
    """
    inst = labels.get("app.kubernetes.io/instance")

    comp = labels.get("app.kubernetes.io/component")
    if comp:
        sel = f"app.kubernetes.io/component={comp}"
        if inst:
            sel += f",app.kubernetes.io/instance={inst}"
        return inst, comp, sel

    name = labels.get("app.kubernetes.io/name")
    if name:
        sel = f"app.kubernetes.io/name={name}"
        if inst:
            sel += f",app.kubernetes.io/instance={inst}"
        return inst, name, sel

    # Non-Helm fallbacks
    for key in ("k8s-app", "app", "name"):
        val = labels.get(key)
        if val:
            return inst, val, f"{key}={val}"

    return None


def _build_log_targets(pods_data: dict) -> list[LogTarget]:
    """Group pods across all namespaces into LogTarget records.

    Pods with Helm-style labels are keyed by `(namespace, instance, component)`.
    Pods without an `instance` label use the namespace as the pseudo-instance.
    """
    grouped: dict[tuple[str, str, str], LogTarget] = {}
    for pod in pods_data.get("items", []):
        md = pod.get("metadata", {})
        namespace = md.get("namespace", "")
        labels = md.get("labels") or {}
        identity = _resolve_pod_identity(labels)
        if not identity:
            continue
        inst, comp, selector = identity
        effective_instance = inst or namespace
        key = (namespace, effective_instance, comp)
        if key not in grouped:
            grouped[key] = LogTarget(
                namespace=namespace,
                instance=effective_instance,
                instance_short=effective_instance.removeprefix("linto-"),
                component=comp,
                label_selector=selector,
                pod_count=0,
                pods=[],
            )
        grouped[key].pod_count += 1
        pod_name = md.get("name")
        if pod_name:
            grouped[key].pods.append(pod_name)
    return sorted(
        grouped.values(), key=lambda t: (t.namespace, t.instance, t.component)
    )


def write_targets_cache(
    profile_name: str, targets: list[LogTarget], base_dir: Path
) -> None:
    """Persist log targets for fast completion lookups. Best-effort."""
    try:
        path = _targets_cache_path(profile_name, base_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {
                    "refreshed_at": datetime.utcnow().isoformat() + "Z",
                    "targets": [asdict(t) for t in targets],
                },
                indent=2,
            )
        )
    except OSError:
        pass


def read_targets_cache(
    profile_name: str, base_dir: Path | None = None
) -> list[LogTarget] | None:
    """Load cached log targets. Returns None if missing or unreadable."""
    if base_dir is None:
        base_dir = Path.cwd()
    path = _targets_cache_path(profile_name, base_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text())
        return [LogTarget(**t) for t in data.get("targets", [])]
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def fetch_log_targets(
    profile: ProfileConfig,
    profile_name: str,
    base_dir: Path | None = None,
    timeout: int = 10,
) -> list[LogTarget]:
    """Live-fetch log targets across every namespace and update the cache."""
    if base_dir is None:
        base_dir = Path.cwd()
    with KubeconfigContext(profile.kubeconfig):
        try:
            result = subprocess.run(
                ["kubectl", "get", "pods", "--all-namespaces", "-o", "json"],
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return []
    if result.returncode != 0 or not result.stdout.strip():
        return []
    try:
        pods_data = json.loads(result.stdout)
    except json.JSONDecodeError:
        return []
    targets = _build_log_targets(pods_data)
    write_targets_cache(profile_name, targets, base_dir)
    return targets


def _print_log_targets(targets: list[LogTarget], profile_name: str) -> None:
    """Render the list of targets grouped by namespace."""
    if not targets:
        console.print(
            "[yellow]No pods found. Is the SSH tunnel up and the cluster reachable?[/yellow]"
        )
        return

    # Component → set of (namespace, instance) to detect ambiguity
    locations_of_component: dict[str, set[tuple[str, str]]] = defaultdict(set)
    for t in targets:
        locations_of_component[t.component].add((t.namespace, t.instance))

    table = Table(title=f"Log targets — {profile_name}")
    table.add_column("Namespace", style="magenta")
    table.add_column("Chart / release", style="cyan")
    table.add_column("Component", style="green")
    table.add_column("Pods", style="dim", justify="right")
    table.add_column("Invocation", style="white")

    current_namespace = None
    current_instance = None
    for t in targets:
        locations = locations_of_component[t.component]
        namespaces = {ns for ns, _ in locations}
        instances = {inst for _, inst in locations}
        if len(namespaces) > 1:
            invocation = f"{t.namespace}/{t.component}"
        elif len(instances) > 1:
            invocation = f"{t.instance_short}/{t.component}"
        else:
            invocation = t.component

        ns_display = t.namespace if t.namespace != current_namespace else ""
        inst_display = (
            t.instance
            if (t.namespace, t.instance) != (current_namespace, current_instance)
            else ""
        )
        current_namespace = t.namespace
        current_instance = t.instance
        table.add_row(
            ns_display, inst_display, t.component, str(t.pod_count), invocation
        )

    console.print(table)
    console.print(
        f"[dim]Usage: linto logs {profile_name} <invocation>"
        f"   |   <ns>/<component>   |   <chart>/<component>"
        f"   |   pod/<full-pod-name>[/dim]"
    )


def _resolve_log_target(
    service: str,
    targets: list[LogTarget],
    default_namespace: str,
) -> tuple[str, list[str], str | None]:
    """Translate a user token into a (namespace, kubectl_args, warning) tuple."""
    # Explicit pod/ or deployment/ — look up namespace from cache, else default
    if service.startswith("pod/"):
        pod_name = service[4:]
        for t in targets:
            if pod_name in t.pods:
                return t.namespace, [service], None
        return default_namespace, [service], None

    if service.startswith("deployment/"):
        dep_name = service[len("deployment/") :]
        for t in targets:
            if any(p.startswith(dep_name + "-") for p in t.pods):
                return t.namespace, [service], None
        return default_namespace, [service], None

    # X/Y form — X can be namespace, instance (full or short)
    if "/" in service:
        left, right = service.split("/", 1)
        matches = [
            t
            for t in targets
            if t.component == right
            and (
                t.namespace == left
                or t.instance == left
                or t.instance_short == left
                or t.instance == f"linto-{left}"
            )
        ]
        if matches:
            t = matches[0]
            return t.namespace, ["-l", t.label_selector], None
        # Unknown left side — best-effort guess
        return (
            default_namespace,
            [
                "-l",
                f"app.kubernetes.io/instance=linto-{left},app.kubernetes.io/component={right}",
            ],
            f"No target matched '{service}'. Guessing namespace={default_namespace}.",
        )

    # Bare token: try component first, then instance-level shortcut
    comp_matches = [t for t in targets if t.component == service]
    if comp_matches:
        namespaces = {t.namespace for t in comp_matches}
        instances = {t.instance for t in comp_matches}
        if len(namespaces) == 1 and len(instances) == 1:
            t = comp_matches[0]
            return t.namespace, ["-l", t.label_selector], None
        if len(namespaces) == 1:
            # Same namespace, multiple instances → stream all via bare component label
            warning = (
                f"'{service}' matches {len(comp_matches)} releases in "
                f"{namespaces.pop()}; streaming all. Disambiguate with "
                f"<chart>/{service}."
            )
            return (
                comp_matches[0].namespace,
                ["-l", f"app.kubernetes.io/component={service}"],
                warning,
            )
        # Across namespaces — must pick one
        t = comp_matches[0]
        warning = (
            f"'{service}' exists in namespaces {sorted(namespaces)}; "
            f"streaming {t.namespace}. Use <ns>/{service} to pick another."
        )
        return t.namespace, ["-l", t.label_selector], warning

    # Instance-level shortcut (chart-level within linto, namespace-level elsewhere)
    inst_matches = [
        t
        for t in targets
        if t.instance == service
        or t.instance_short == service
        or t.instance == f"linto-{service}"
    ]
    if inst_matches:
        namespaces = {t.namespace for t in inst_matches}
        t = inst_matches[0]
        if len(namespaces) > 1:
            warning = (
                f"Chart '{service}' spans {sorted(namespaces)}; streaming "
                f"{t.namespace}."
            )
        else:
            warning = None
        return (
            t.namespace,
            ["-l", f"app.kubernetes.io/instance={t.instance}"],
            warning,
        )

    # Namespace-level "shortcut" isn't meaningful for `kubectl logs` (no selector
    # ⇒ error), so nudge the user toward a specific component instead.
    ns_matches = [t for t in targets if t.namespace == service]
    if ns_matches:
        options = sorted({t.component for t in ns_matches})
        raise ValidationError(
            "SERVICE_NAMESPACE_ONLY",
            f"'{service}' is a namespace. Pick a component: {', '.join(options)}",
        )


def resolve_pod_for_service(
    service: str,
    targets: list[LogTarget],
    default_namespace: str,
) -> tuple[str, str] | None:
    """Resolve a service token into the (namespace, pod_name) of a single pod.

    Used by `port-forward`, `exec`, etc. where we need exactly one pod rather
    than a label stream. Accepts the same forms as `_resolve_log_target`:
    pod/X, deployment/X, <ns>/<component>, <instance>/<component>, bare name.
    """
    if service.startswith("pod/"):
        pod_name = service[4:]
        for t in targets:
            if pod_name in t.pods:
                return t.namespace, pod_name
        return default_namespace, pod_name

    if service.startswith("deployment/"):
        dep_name = service[len("deployment/") :]
        for t in targets:
            for p in t.pods:
                if p.startswith(dep_name + "-"):
                    return t.namespace, p
        return None

    if "/" in service:
        left, right = service.split("/", 1)
        matches = [
            t
            for t in targets
            if t.component == right
            and (
                t.namespace == left
                or t.instance == left
                or t.instance_short == left
                or t.instance == f"linto-{left}"
            )
        ]
        if matches and matches[0].pods:
            return matches[0].namespace, matches[0].pods[0]
        return None

    comp_matches = [t for t in targets if t.component == service]
    if comp_matches and comp_matches[0].pods:
        return comp_matches[0].namespace, comp_matches[0].pods[0]

    inst_matches = [
        t
        for t in targets
        if t.instance == service
        or t.instance_short == service
        or t.instance == f"linto-{service}"
    ]
    if inst_matches and inst_matches[0].pods:
        return inst_matches[0].namespace, inst_matches[0].pods[0]

    return None

    # Unknown — try the label anyway in the default namespace
    return (
        default_namespace,
        ["-l", f"app.kubernetes.io/component={service}"],
        f"'{service}' not found in cache. Run 'linto logs <profile>' to refresh.",
    )


def logs_k3s(
    profile_name: str,
    service: str | None = None,
    follow: bool = False,
    tail: int = 100,
    base_dir: Path | None = None,
) -> None:
    """Show logs from k3s services.

    Args:
        profile_name: Name of the profile
        service: Component name, instance/component, pod/<name>, or deployment/<name>
        follow: Whether to follow log output
        tail: Number of lines to show
        base_dir: Base directory for .linto folder
    """
    if base_dir is None:
        base_dir = Path.cwd()

    # Load profile
    profile = load_profile(profile_name, base_dir)
    namespace = profile.k3s_namespace
    kubeconfig = profile.kubeconfig

    # Check prerequisites (using profile's kubeconfig)
    missing = check_k3s_prerequisites(profile)
    if missing:
        raise ValidationError(
            "K3S_PREREQUISITES_MISSING",
            f"Missing prerequisites: {', '.join(missing)}",
        )

    # No service: list the available targets (also refreshes the cache)
    if not service:
        targets = fetch_log_targets(profile, profile_name, base_dir=base_dir)
        _print_log_targets(targets, profile_name)
        return

    # Resolve the service token — cache-first, fall back to live fetch.
    # We always need the cache so we can map components / pods to namespaces.
    targets = read_targets_cache(profile_name, base_dir) or fetch_log_targets(
        profile, profile_name, base_dir=base_dir
    )

    resolved_namespace, resolved_args, warning = _resolve_log_target(
        service, targets, default_namespace=namespace
    )
    if warning:
        console.print(f"[yellow]⚠ {warning}[/yellow]")

    cmd = [
        "kubectl",
        "logs",
        "--namespace",
        resolved_namespace,
        "--tail",
        str(tail),
    ]
    if follow:
        cmd.append("-f")
    cmd.extend(resolved_args)

    # All kubectl operations use the profile's kubeconfig
    with KubeconfigContext(kubeconfig):
        try:
            if follow:
                from linto.utils.cmd import get_show_commands, quote_arg

                if get_show_commands():
                    cmd_str = " ".join(quote_arg(arg) for arg in cmd)
                    stderr_console.print(f"[dim]$ {cmd_str}[/dim]")
                process = subprocess.Popen(cmd)
                try:
                    process.wait()
                except KeyboardInterrupt:
                    process.terminate()
                    console.print("\n[yellow]Stopped following logs.[/yellow]")
            else:
                run_cmd(cmd, check=False, capture_output=False)
        except subprocess.SubprocessError as e:
            raise ValidationError(
                "LOGS_FAILED",
                f"kubectl logs failed: {e}",
            ) from e


# Module-level exports matching Backend protocol
render = render_k3s
generate = generate_k3s
apply = apply_k3s
destroy = destroy_k3s
status = status_k3s
logs = logs_k3s
