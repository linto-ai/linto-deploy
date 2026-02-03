"""Kubernetes (k3s) backend using Helm charts."""

import importlib.resources
import subprocess
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
    with KubeconfigContext(kubeconfig):
        try:
            result = subprocess.run(
                ["kubectl", "cluster-info"],
                capture_output=True,
                check=False,
                timeout=15,
            )
            if result.returncode != 0:
                missing.append("Kubernetes cluster not accessible")
        except (subprocess.TimeoutExpired, FileNotFoundError):
            missing.append("Cannot connect to Kubernetes cluster")

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
        db_name: Database name (e.g., 'studio-mongo', 'stt-redis', 'llm-postgres')

    Returns:
        Version tag for the database
    """
    # Check for db-prefixed key first, then direct name
    tag = profile.service_tags.get(f"db-{db_name}")
    if tag:
        return tag
    # Default database versions (service-specific)
    defaults = {
        "studio-mongo": "6.0.2",
        "stt-mongo": "6.0.2",
        "stt-redis": "7.4.0-v8",
        "live-postgres": "15-alpine",
        "live-mosquitto": "2",
        "llm-postgres": "15-alpine",
        "llm-redis": "7.4.0-v8",
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
            "replicas": 1,
            "image": {
                "tag": get_service_tag(profile, "studio-api"),
            },
            "env": {
                "SUPER_ADMIN_EMAIL": profile.super_admin_email,
                "SUPER_ADMIN_PWD": profile.super_admin_password or "",
                "CM_JWT_SECRET": profile.jwt_secret or "",
                "CM_REFRESH_SECRET": profile.jwt_refresh_secret or "",
            },
            "resources": {
                "limits": {
                    "cpu": "2",
                    "memory": "8Gi",
                },
            },
        },
        "studioFrontend": {
            "enabled": True,
            "replicas": 1,
            "image": {
                "tag": get_service_tag(profile, "studio-frontend"),
            },
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

    # Add service gateway URLs if STT/LLM enabled
    if profile.stt_enabled:
        values["studioApi"]["env"]["GATEWAY_SERVICES"] = "http://linto-stt-api-gateway:80"
    if profile.llm_enabled:
        values["studioApi"]["env"]["LLM_GATEWAY_SERVICES"] = "http://linto-llm-llm-api:80"

    if profile.k3s_storage_class:
        values["mongodb"]["persistence"]["storageClass"] = profile.k3s_storage_class

    # Determine URL scheme based on TLS mode
    tls_mode = profile.tls_mode.value if isinstance(profile.tls_mode, TLSMode) else profile.tls_mode
    scheme = "https" if tls_mode != "off" else "http"

    # Initialize secrets dict
    if "secrets" not in values["studioApi"]:
        values["studioApi"]["secrets"] = {}

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
                "BROKER_PASS": profile.redis_password or "",
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
                "BROKER_PASS": profile.redis_password or "",
                "DEVICE": "cuda" if gpu_enabled else "cpu",
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
        values["diarization"]["replicasPerGpu"] = replicas_per_gpu
    else:
        # Single GPU or CPU: use simple replicas
        values["whisperWorkers"]["replicas"] = 1
        values["whisperWorkers"]["resources"] = {}
        values["diarization"]["replicas"] = 1
        values["diarization"]["resources"] = {}

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
            "resources": {
                "limits": {
                    "cpu": "2",
                    "memory": "8Gi",
                },
            },
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
            "resources": {
                "limits": {
                    "cpu": "8",
                    "memory": "8Gi",
                },
            },
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
        "streamingStt": {},
    }

    # Add streaming STT variants with version tags
    variant_image_map = {
        StreamingSTTVariant.WHISPER: "linto-stt-whisper",
        StreamingSTTVariant.KALDI_FRENCH: "linto-stt-kaldi",
        StreamingSTTVariant.NEMO_FRENCH: "linto-stt-nemo",
        StreamingSTTVariant.NEMO_ENGLISH: "linto-stt-nemo",
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

        # Install cert-manager if requested and using ACME
        tls_mode = profile.tls_mode.value if isinstance(profile.tls_mode, TLSMode) else profile.tls_mode
        if tls_mode == "acme" and profile.k3s_install_cert_manager:
            if not install_cert_manager(kubeconfig):
                console.print("[yellow]Warning: cert-manager installation failed[/yellow]")

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
        service: Pod or deployment name
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

    if not service:
        console.print("[red]Error: Service/pod name is required for k3s logs[/red]")
        console.print("[dim]Use 'linto status --profile {profile}' to see available pods[/dim]")
        raise ValidationError(
            "SERVICE_REQUIRED",
            "Service/pod name is required for k3s logs",
        )

    cmd = [
        "kubectl",
        "logs",
        "--namespace",
        namespace,
        "--tail",
        str(tail),
    ]

    if follow:
        cmd.append("-f")

    # Determine if it's a pod or deployment
    if "/" in service:
        cmd.append(service)
    else:
        # Try to find matching pod
        cmd.extend(["-l", f"app.kubernetes.io/name={service}"])

    # All kubectl operations use the profile's kubeconfig
    with KubeconfigContext(kubeconfig):
        try:
            if follow:
                # For follow mode, print command then use Popen
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
