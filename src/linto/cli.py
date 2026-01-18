"""CLI entry point for LinTO deployment tool."""

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Annotated, Optional

import typer
import yaml
from rich.console import Console
from rich.live import Live
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.prompt import Confirm
from rich.table import Table

from linto.model.validation import ValidationError
from linto.utils.cmd import run_cmd

app = typer.Typer(
    name="linto",
    help="LinTO deployment tool - manage LinTO deployments on Kubernetes",
    no_args_is_help=True,
    rich_markup_mode="rich",
)


@app.callback()
def main_callback(
    quiet: Annotated[
        bool,
        typer.Option("--quiet", "-q", help="Hide kubectl/helm commands being executed"),
    ] = False,
) -> None:
    """LinTO deployment tool."""
    from linto.utils.cmd import set_show_commands

    set_show_commands(not quiet)

# Subcommand groups
kubeconfig_app = typer.Typer(name="kubeconfig", help="Manage kubeconfig")
profile_app = typer.Typer(name="profile", help="Manage profiles")

app.add_typer(kubeconfig_app)
app.add_typer(profile_app)

console = Console()


def _handle_error(error: ValidationError) -> None:
    """Handle validation errors with rich formatting."""
    console.print(f"[red]Error ({error.code}):[/red] {error.message}")
    raise typer.Exit(1)


def _check_backend_supported(profile_data) -> None:
    """Check if backend is supported and raise error if not."""
    from linto.model.profile import DeploymentBackend

    if profile_data.backend != DeploymentBackend.K3S:
        console.print(f"[red]Error:[/red] Backend '{profile_data.backend.value}' is not yet supported.")
        console.print("[dim]Currently only 'k3s' backend is available.[/dim]")
        console.print("[dim]Docker Compose and Swarm support is planned for a future release.[/dim]")
        raise typer.Exit(1)


def _get_available_profiles() -> list[str]:
    """Get list of available profile names for autocomplete."""
    profiles_dir = Path.cwd() / ".linto" / "profiles"
    if not profiles_dir.exists():
        return []
    return [f.stem for f in profiles_dir.glob("*.json")]


def _complete_profile(incomplete: str) -> list[str]:
    """Shell completion for profile names."""
    profiles = _get_available_profiles()
    return [p for p in profiles if p.startswith(incomplete)]


def _get_k3s_services(profile_name: str) -> list[str]:
    """Get list of available services/pods for a k3s profile."""
    try:
        from linto.model.validation import load_profile
        from linto.utils.kubeconfig import KubeconfigContext

        profile = load_profile(profile_name)
        namespace = profile.k3s_namespace

        with KubeconfigContext(profile.kubeconfig):
            chart_names = set()
            deployments = []
            pods = []

            # Get deployments
            result = subprocess.run(
                ["kubectl", "get", "deployments", "-n", namespace, "-o", "json"],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                for item in data.get("items", []):
                    name = item["metadata"]["name"]
                    deployments.append(f"deployment/{name}")
                    labels = item.get("metadata", {}).get("labels", {})
                    chart_name = labels.get("app.kubernetes.io/name")
                    if chart_name:
                        chart_names.add(chart_name)

            # Get pods
            result = subprocess.run(
                ["kubectl", "get", "pods", "-n", namespace, "-o", "json"],
                capture_output=True,
                text=True,
                check=False,
                timeout=10,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                for item in data.get("items", []):
                    name = item["metadata"]["name"]
                    pods.append(f"pod/{name}")

            # Order: chart names, deployments, pods
            return sorted(chart_names) + sorted(deployments) + sorted(pods)
    except FileNotFoundError:
        # kubectl not installed - silent fail for completion
        pass
    except subprocess.TimeoutExpired:
        # Cluster not responding - silent fail for completion
        pass
    except Exception as e:
        # Log other errors for debugging
        print(f"Service completion error: {e}", file=sys.stderr)
    return []


def _complete_service(ctx: typer.Context, incomplete: str) -> list[str]:
    """Shell completion for service names."""
    try:
        # For positional arguments, we need to look at the raw args
        # The profile should be the first argument after the command name
        args = ctx.args if ctx.args else []

        # Also check parent context for args
        if not args and ctx.parent and hasattr(ctx.parent, "args"):
            args = ctx.parent.args or []

        # Try to get profile from params first (works for some shells)
        profile = ctx.params.get("profile", "")

        # If not in params, try to extract from command line args
        if not profile and args:
            profile = args[0]

        if not profile:
            return []

        services = _get_k3s_services(profile)
        return [s for s in services if s.startswith(incomplete)]
    except Exception as e:
        # Log error for debugging instead of silently ignoring
        print(f"Completion error: {e}", file=sys.stderr)
        return []


@app.command()
def wizard() -> None:
    """Interactive wizard to create a deployment profile."""
    try:
        from linto.wizard.flow import run_wizard

        run_wizard()
    except ValidationError as e:
        _handle_error(e)
    except KeyboardInterrupt:
        console.print("\n[yellow]Wizard cancelled.[/yellow]")
        raise typer.Exit(0)


@app.command(name="list")
def list_profiles_cmd() -> None:
    """List all deployment profiles."""
    from linto.profile_ops import get_profile_summary, list_profiles

    profiles = list_profiles()

    if not profiles:
        console.print("[yellow]No profiles found.[/yellow]")
        console.print("[dim]Use 'linto wizard' to create one.[/dim]")
        raise typer.Exit(0)

    table = Table(title="Profiles")
    table.add_column("Name", style="cyan")
    table.add_column("Backend", style="green")
    table.add_column("Domain", style="white")
    table.add_column("Services", style="dim")

    for profile in profiles:
        summary = get_profile_summary(profile)
        table.add_row(
            summary["name"],
            summary["backend"],
            summary["domain"],
            summary["services"],
        )

    console.print(table)


@app.command()
def show(
    profile: Annotated[
        str,
        typer.Argument(
            help="Profile name",
            metavar="PROFILE_NAME",
            autocompletion=_complete_profile,
        ),
    ],
) -> None:
    """Show details of a deployment profile.

    [bold]Example:[/bold]
        linto show my-profile
    """
    from linto.model.validation import load_profile

    try:
        profile_data = load_profile(profile)

        table = Table(title=f"Profile: {profile}")
        table.add_column("Setting", style="cyan")
        table.add_column("Value", style="green")

        table.add_row("Name", profile_data.name)
        table.add_row("Backend", profile_data.backend.value)
        table.add_row("Domain", profile_data.domain)
        table.add_row("Image Tag", profile_data.image_tag)
        table.add_row("TLS Mode", profile_data.tls_mode.value)
        table.add_row("GPU Mode", profile_data.gpu_mode.value)
        table.add_row("GPU Count", str(profile_data.gpu_count))
        table.add_row("Studio", "enabled" if profile_data.studio_enabled else "disabled")
        table.add_row("STT", "enabled" if profile_data.stt_enabled else "disabled")
        table.add_row(
            "Live Session",
            "enabled" if profile_data.live_session_enabled else "disabled",
        )
        table.add_row("LLM", "enabled" if profile_data.llm_enabled else "disabled")
        table.add_row("Admin Email", profile_data.super_admin_email)

        if profile_data.backend.value == "k3s":
            table.add_row("Namespace", profile_data.k3s_namespace)
            table.add_row("Storage Class", profile_data.k3s_storage_class or "(default)")

        console.print(table)
    except ValidationError as e:
        _handle_error(e)


@app.command()
def render(
    profile: Annotated[
        str,
        typer.Argument(
            help="Profile name",
            metavar="PROFILE_NAME",
            autocompletion=_complete_profile,
        ),
    ],
    output: Annotated[
        Optional[str],
        typer.Option("--output", "-o", help="Output directory"),
    ] = None,
) -> None:
    """Generate deployment artifacts without applying.

    [bold]Example:[/bold]
        linto render my-profile
        linto render my-profile -o ./output
    """
    try:
        from linto.backends import get_backend
        from linto.model.validation import load_profile

        profile_data = load_profile(profile)
        _check_backend_supported(profile_data)
        backend = get_backend(profile_data.backend)
        backend.generate(profile, output)
    except ValidationError as e:
        _handle_error(e)


@app.command()
def deploy(
    profile: Annotated[
        str,
        typer.Argument(
            help="Profile name",
            metavar="PROFILE_NAME",
            autocompletion=_complete_profile,
        ),
    ],
    force: Annotated[
        bool,
        typer.Option("--force", help="Skip GPU capacity warnings"),
    ] = False,
) -> None:
    """Generate Helm values and deploy services to cluster.

    [bold]Example:[/bold]
        linto deploy my-profile
    """
    try:
        from linto.backends import get_backend
        from linto.gpu import validate_gpu_capacity
        from linto.model.validation import load_profile

        profile_data = load_profile(profile)
        _check_backend_supported(profile_data)

        # GPU capacity validation
        warnings = validate_gpu_capacity(profile_data)
        if warnings and not force:
            for warning in warnings:
                console.print(f"[yellow]{warning}[/yellow]")
            if not Confirm.ask("\n[cyan]Continue anyway?[/cyan]", default=False):
                console.print("[yellow]Deployment cancelled.[/yellow]")
                raise typer.Exit(0)

        backend = get_backend(profile_data.backend)
        backend.apply(profile)
    except ValidationError as e:
        _handle_error(e)


@app.command()
def destroy(
    profile: Annotated[
        str,
        typer.Argument(
            help="Profile name",
            metavar="PROFILE_NAME",
            autocompletion=_complete_profile,
        ),
    ],
    force: Annotated[
        bool,
        typer.Option("--force", help="Skip confirmation prompt"),
    ] = False,
    volumes: Annotated[
        bool,
        typer.Option("--volumes", "-v", help="Remove persistent volumes (PVCs)"),
    ] = False,
    remove_files: Annotated[
        bool,
        typer.Option("--remove-files", "-r", help="Remove generated files"),
    ] = False,
) -> None:
    """Stop and remove a deployment.

    [bold]Example:[/bold]
        linto destroy my-profile
        linto destroy my-profile --volumes  # also delete data
    """
    try:
        from linto.backends import get_backend
        from linto.model.validation import load_profile

        profile_data = load_profile(profile)
        _check_backend_supported(profile_data)

        # Confirmation prompt
        if not force:
            console.print(f"[yellow]Warning: This will stop and remove all services for profile '{profile}'.[/yellow]")
            if not Confirm.ask("[cyan]Are you sure?[/cyan]", default=False):
                console.print("[yellow]Cancelled.[/yellow]")
                raise typer.Exit(0)

        # Volume warning
        if volumes and not force:
            console.print("[red]Warning: This will delete all persistent data including:[/red]")
            console.print("  - Database contents")
            console.print("  - Model caches")
            console.print("  - Audio files")
            if not Confirm.ask("[cyan]Are you sure?[/cyan]", default=False):
                console.print("[yellow]Cancelled.[/yellow]")
                raise typer.Exit(0)

        backend = get_backend(profile_data.backend)
        backend.destroy(profile, remove_files=remove_files, remove_volumes=volumes)
    except ValidationError as e:
        _handle_error(e)


def _format_age(timestamp_str: str | None) -> str:
    """Format a Kubernetes timestamp as a human-readable age (e.g., '2d3h', '5m', '30s')."""
    if not timestamp_str:
        return "-"

    from datetime import datetime, timezone

    try:
        # Parse ISO 8601 timestamp from Kubernetes
        created = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        delta = now - created

        total_seconds = int(delta.total_seconds())
        if total_seconds < 0:
            return "-"

        days = total_seconds // 86400
        hours = (total_seconds % 86400) // 3600
        minutes = (total_seconds % 3600) // 60
        seconds = total_seconds % 60

        if days > 0:
            return f"{days}d{hours}h" if hours > 0 else f"{days}d"
        elif hours > 0:
            return f"{hours}h{minutes}m" if minutes > 0 else f"{hours}h"
        elif minutes > 0:
            return f"{minutes}m{seconds}s" if seconds > 0 else f"{minutes}m"
        else:
            return f"{seconds}s"
    except (ValueError, TypeError):
        return "-"


def _get_pod_metrics(namespace: str, kubeconfig: dict | None = None) -> dict[str, dict]:
    """Get pod resource metrics from kubectl top."""
    from linto.utils.kubeconfig import KubeconfigContext

    metrics = {}
    try:
        with KubeconfigContext(kubeconfig):
            result = subprocess.run(
                ["kubectl", "top", "pods", "-n", namespace, "--no-headers"],
                capture_output=True,
                text=True,
                check=False,
                timeout=15,
            )
            if result.returncode == 0:
                for line in result.stdout.strip().split("\n"):
                    if not line.strip():
                        continue
                    parts = line.split()
                    if len(parts) >= 3:
                        pod_name = parts[0]
                        cpu = parts[1]
                        memory = parts[2]
                        metrics[pod_name] = {"cpu": cpu, "memory": memory}
    except Exception as e:
        console.print(f"[dim]Debug: {type(e).__name__}: {e}[/dim]", style="dim")
    return metrics


def _get_pod_resource_limits(namespace: str, kubeconfig: dict | None = None) -> dict[str, dict]:
    """Get pod resource limits from specs."""
    from linto.utils.kubeconfig import KubeconfigContext

    limits = {}
    try:
        with KubeconfigContext(kubeconfig):
            result = subprocess.run(
                ["kubectl", "get", "pods", "-n", namespace, "-o", "json"],
                capture_output=True,
                text=True,
                check=False,
                timeout=15,
            )
            if result.returncode == 0:
                data = json.loads(result.stdout)
                for pod in data.get("items", []):
                    pod_name = pod["metadata"]["name"]
                    containers = pod.get("spec", {}).get("containers", [])
                    if containers:
                        res = containers[0].get("resources", {})
                        pod_limits = res.get("limits", {})
                        limits[pod_name] = {
                            "cpu_limit": pod_limits.get("cpu", "-"),
                            "memory_limit": pod_limits.get("memory", "-"),
                            "gpu": pod_limits.get("nvidia.com/gpu", "0"),
                        }
    except Exception as e:
        console.print(f"[dim]Debug: {type(e).__name__}: {e}[/dim]", style="dim")
    return limits


def _build_status_display(
    profile_name: str,
    profile_data,
    backend,
    compact: bool,
) -> Table | str:
    """Build the status display table.

    Args:
        profile_name: Name of the profile
        profile_data: Profile configuration data
        backend: Backend module
        compact: Whether to hide resource metrics

    Returns:
        Rich Table with service status or message string if no services
    """
    from rich.console import Group
    from rich.text import Text

    from linto.model.profile import DeploymentBackend

    # Build header
    backend_name = profile_data.backend.value
    header_lines = [
        Text.from_markup(f"[bold]Profile:[/bold] {profile_name} ({backend_name})"),
        Text.from_markup(f"[bold]Domain:[/bold] {profile_data.domain}"),
    ]

    if profile_data.backend == DeploymentBackend.K3S:
        header_lines.append(Text.from_markup(f"[bold]Namespace:[/bold] {profile_data.k3s_namespace}"))

    # Get service status
    services = backend.status(profile_name)

    if not services:
        header_lines.append(Text())
        header_lines.append(Text.from_markup("[yellow]No services running.[/yellow]"))
        return Group(*header_lines)

    # For k3s with metrics (default), get resource metrics
    metrics = {}
    limits = {}
    if not compact and profile_data.backend == DeploymentBackend.K3S:
        metrics = _get_pod_metrics(profile_data.k3s_namespace, profile_data.kubeconfig)
        limits = _get_pod_resource_limits(profile_data.k3s_namespace, profile_data.kubeconfig)

    # Build table
    table = Table(title="Services")
    table.add_column("Service", style="cyan")
    table.add_column("Status")  # No default style - we color based on status value

    if not compact:
        table.add_column("CPU", style="yellow")
        table.add_column("Memory", style="yellow")
        table.add_column("GPU", style="magenta")

    table.add_column("Age", style="dim")

    for svc in services:
        name = svc.get("name", "unknown")
        status_str = svc.get("status", svc.get("replicas", "unknown"))

        # Add detailed status if available (e.g., ContainerCreating, ImagePullBackOff, Terminating)
        detailed_status = svc.get("detailed_status")
        if detailed_status:
            # Color code based on status type
            if detailed_status in ("ContainerCreating", "PodInitializing") or detailed_status.startswith("Init:"):
                status_str = f"[yellow]{detailed_status}[/yellow]"
            elif "Pull" in detailed_status or "Image" in detailed_status:
                status_str = f"[yellow]{detailed_status}[/yellow]"
            elif detailed_status == "Terminating":
                status_str = f"[red]{detailed_status}[/red]"
            elif detailed_status in ("CrashLoopBackOff", "Error", "OOMKilled"):
                status_str = f"[red]{detailed_status}[/red]"
            else:
                status_str = f"{status_str} ({detailed_status})"
        elif svc.get("health"):
            status_str = f"{status_str} ({svc['health']})"
        else:
            # Color code base status for helm releases and pods
            status_lower = status_str.lower() if isinstance(status_str, str) else ""
            if status_lower in ("deployed", "running"):
                status_str = f"[green]{status_str}[/green]"
            elif status_lower == "failed":
                status_str = f"[red]{status_str}[/red]"
            elif status_lower in ("pending", "pending-install", "pending-upgrade", "pending-rollback"):
                status_str = f"[yellow]{status_str}[/yellow]"
            elif status_lower in ("superseded", "uninstalled"):
                status_str = f"[dim]{status_str}[/dim]"

        # Get age from creation timestamp
        age_str = _format_age(svc.get("creation_timestamp"))

        # Strip stack prefix for swarm, pod/ prefix for k3s
        service_name = name.split("_")[-1] if "_" in name else name
        if service_name.startswith("pod/"):
            service_name = service_name[4:]

        if not compact:
            # Get metrics for this pod
            pod_name = service_name if not name.startswith("pod/") else name[4:]
            pod_metrics = metrics.get(pod_name, {})
            pod_limits = limits.get(pod_name, {})

            cpu_str = pod_metrics.get("cpu", "-")
            if pod_limits.get("cpu_limit") and pod_limits["cpu_limit"] != "-":
                cpu_str = f"{cpu_str}/{pod_limits['cpu_limit']}"

            mem_str = pod_metrics.get("memory", "-")
            if pod_limits.get("memory_limit") and pod_limits["memory_limit"] != "-":
                mem_str = f"{mem_str}/{pod_limits['memory_limit']}"

            gpu_str = pod_limits.get("gpu", "0")
            if gpu_str == "0":
                gpu_str = "-"

            table.add_row(name, status_str, cpu_str, mem_str, gpu_str, age_str)
        else:
            table.add_row(name, status_str, age_str)

    header_lines.append(Text())
    return Group(*header_lines, table)


@app.command()
def status(
    profile: Annotated[
        str,
        typer.Argument(
            help="Profile name",
            metavar="PROFILE_NAME",
            autocompletion=_complete_profile,
        ),
    ],
    compact: Annotated[
        bool,
        typer.Option("--compact", "-c", help="Hide resource metrics (CPU, Memory, GPU)"),
    ] = False,
    follow: Annotated[
        bool,
        typer.Option("--follow", "-f", help="Continuously refresh status"),
    ] = False,
    interval: Annotated[
        int,
        typer.Option("--interval", "-i", help="Refresh interval in seconds"),
    ] = 5,
) -> None:
    """Show status of deployed services.

    [bold]Example:[/bold]
        linto status my-profile
        linto status my-profile --follow
    """
    try:
        from linto.backends import get_backend
        from linto.model.validation import load_profile

        profile_data = load_profile(profile)
        _check_backend_supported(profile_data)
        backend = get_backend(profile_data.backend)

        if follow:
            # Use Rich Live for smooth, flicker-free updates
            try:
                with Live(console=console, refresh_per_second=1) as live:
                    while True:
                        display = _build_status_display(
                            profile,
                            profile_data,
                            backend,
                            compact,
                        )
                        live.update(display)
                        time.sleep(interval)
            except KeyboardInterrupt:
                console.print("\n[yellow]Stopped monitoring.[/yellow]")
        else:
            # Single display without Live wrapper
            display = _build_status_display(
                profile,
                profile_data,
                backend,
                compact,
            )
            console.print(display)
    except ValidationError as e:
        _handle_error(e)


@app.command()
def logs(
    profile: Annotated[
        str,
        typer.Argument(
            help="Profile name",
            autocompletion=_complete_profile,
        ),
    ],
    service: Annotated[
        Optional[str],
        typer.Argument(
            help="Service/deployment name",
            autocompletion=_complete_service,
        ),
    ] = None,
    follow: Annotated[
        bool,
        typer.Option("--follow", "-f", help="Follow log output"),
    ] = False,
    tail: Annotated[
        int,
        typer.Option("--tail", "-n", help="Number of lines to show"),
    ] = 100,
) -> None:
    """Show logs from services with shell autocomplete support."""
    try:
        from linto.backends import get_backend
        from linto.model.validation import load_profile

        profile_data = load_profile(profile)
        _check_backend_supported(profile_data)
        backend = get_backend(profile_data.backend)
        backend.logs(profile, service, follow, tail)
    except ValidationError as e:
        _handle_error(e)
    except KeyboardInterrupt:
        console.print("\n[yellow]Stopped following logs.[/yellow]")
        raise typer.Exit(0)


@app.command()
def redeploy(
    profile: Annotated[
        str,
        typer.Argument(
            help="Profile name",
            autocompletion=_complete_profile,
        ),
    ],
    chart: Annotated[
        Optional[str],
        typer.Argument(help="Specific chart to redeploy (linto-studio, linto-stt, linto-live, linto-llm)"),
    ] = None,
) -> None:
    """Force redeploy by restarting deployments (useful for latest-* tags).

    With imagePullPolicy: Always, Kubernetes automatically pulls new images
    if the digest has changed on the registry.
    """
    try:
        from linto.model.validation import load_profile

        profile_data = load_profile(profile)
        _check_backend_supported(profile_data)

        namespace = profile_data.k3s_namespace

        # Use profile's embedded kubeconfig for all kubectl calls
        from linto.utils.kubeconfig import KubeconfigContext

        with KubeconfigContext(profile_data.kubeconfig):
            # Determine which deployments to restart
            deployments_to_restart = []

            if chart:
                # Get deployments for specific chart
                chart_label = chart.replace("linto-", "")
                result = run_cmd(
                    [
                        "kubectl",
                        "get",
                        "deployments",
                        "-n",
                        namespace,
                        "-l",
                        f"app.kubernetes.io/instance=linto-{chart_label}",
                        "-o",
                        "jsonpath={.items[*].metadata.name}",
                    ],
                    check=False,
                    timeout=15,
                )
                if result.returncode == 0 and result.stdout.strip():
                    deployments_to_restart = result.stdout.strip().split()
            else:
                # Get all deployments in namespace
                result = run_cmd(
                    [
                        "kubectl",
                        "get",
                        "deployments",
                        "-n",
                        namespace,
                        "-o",
                        "jsonpath={.items[*].metadata.name}",
                    ],
                    check=False,
                    timeout=15,
                )
                if result.returncode == 0 and result.stdout.strip():
                    deployments_to_restart = result.stdout.strip().split()

            if not deployments_to_restart:
                console.print("[yellow]No deployments found to restart[/yellow]")
                raise typer.Exit(0)

            console.print(f"\n[cyan]Restarting {len(deployments_to_restart)} deployments...[/cyan]")

            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                console=console,
            ) as progress:
                for deployment in deployments_to_restart:
                    task = progress.add_task(f"Restarting {deployment}...", total=None)
                    result = run_cmd(
                        [
                            "kubectl",
                            "rollout",
                            "restart",
                            f"deployment/{deployment}",
                            "-n",
                            namespace,
                        ],
                        check=False,
                        timeout=30,
                    )
                    progress.remove_task(task)
                    if result.returncode == 0:
                        console.print(f"  [green]Restarted {deployment}[/green]")
                    else:
                        console.print(f"  [red]Failed to restart {deployment}: {result.stderr}[/red]")

            console.print("\n[green]Redeploy complete![/green]")
            console.print("[dim]Use 'linto status <profile>' to monitor rollout progress[/dim]")

    except ValidationError as e:
        _handle_error(e)


def _open_browser_process(url: str) -> subprocess.Popen | None:
    """Open URL in browser and return process handle if possible.

    Args:
        url: URL to open

    Returns:
        Process handle if we can track it, None otherwise
    """
    import shutil

    # Try to find a browser we can track
    # Priority: firefox (easy to kill), then chromium, then chrome
    browsers = [
        ("firefox", ["firefox", "--new-window", url]),
        ("chromium", ["chromium", "--new-window", url]),
        ("chromium-browser", ["chromium-browser", "--new-window", url]),
        ("google-chrome", ["google-chrome", "--new-window", url]),
    ]

    for name, cmd in browsers:
        if shutil.which(name):
            try:
                return subprocess.Popen(
                    cmd,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            except Exception:
                continue

    # Fallback: use xdg-open (can't track the process)
    import webbrowser

    webbrowser.open(url)
    return None


@app.command()
def grafana(
    profile: Annotated[
        str,
        typer.Argument(
            help="Profile name",
            metavar="PROFILE_NAME",
            autocompletion=_complete_profile,
        ),
    ],
    port: Annotated[
        int,
        typer.Option("--port", "-p", help="Local port for Grafana"),
    ] = 3000,
    no_browser: Annotated[
        bool,
        typer.Option("--no-browser", help="Don't open browser automatically"),
    ] = False,
) -> None:
    """Open Grafana monitoring dashboard.

    Starts port-forward to Grafana and opens browser.
    Requires monitoring to be enabled and deployed.

    [bold]Example:[/bold]
        linto grafana my-profile
        linto grafana my-profile --port 8080
    """
    import tempfile
    from pathlib import Path

    import yaml

    try:
        from linto.model.validation import load_profile

        profile_data = load_profile(profile)
        _check_backend_supported(profile_data)

        if not profile_data.monitoring_enabled:
            console.print("[red]Error:[/red] Monitoring is not enabled for this profile.")
            console.print("[dim]Enable monitoring with: linto wizard (or edit the profile JSON)[/dim]")
            raise typer.Exit(1)

        monitoring_namespace = "monitoring"

        # Prepare kubeconfig args if profile has embedded kubeconfig
        kubeconfig_args: list[str] = []
        temp_kubeconfig: Path | None = None

        if profile_data.kubeconfig:
            # Create temp file for kubeconfig (will be cleaned up in finally block)
            fd, path = tempfile.mkstemp(suffix=".yaml", prefix="kubeconfig-")
            temp_kubeconfig = Path(path)
            with open(fd, "w") as f:
                yaml.dump(profile_data.kubeconfig, f)
            kubeconfig_args = ["--kubeconfig", str(temp_kubeconfig)]

        try:
            # Check if Grafana is deployed
            result = subprocess.run(
                ["kubectl", *kubeconfig_args, "get", "svc", "prometheus-grafana", "-n", monitoring_namespace],
                capture_output=True,
                text=True,
                check=False,
                timeout=15,
            )
            if result.returncode != 0:
                console.print("[red]Error:[/red] Grafana service not found.")
                console.print(f"[dim]Make sure monitoring is deployed (namespace '{monitoring_namespace}')[/dim]")
                console.print("[dim]Run 'linto deploy <profile>' to deploy monitoring[/dim]")
                raise typer.Exit(1)

            console.print(f"[cyan]Starting port-forward to Grafana on port {port}...[/cyan]")

            # Start port-forward
            pf_process = subprocess.Popen(
                [
                    "kubectl",
                    *kubeconfig_args,
                    "port-forward",
                    "svc/prometheus-grafana",
                    f"{port}:80",
                    "-n",
                    monitoring_namespace,
                ],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            # Wait a moment for port-forward to establish
            time.sleep(1)

            # Check if process is still running
            if pf_process.poll() is not None:
                stderr = pf_process.stderr.read().decode() if pf_process.stderr else ""
                console.print(f"[red]Error starting port-forward:[/red] {stderr}")
                raise typer.Exit(1)

            url = f"http://localhost:{port}"
            console.print(f"[green]Grafana available at:[/green] {url}")

            browser_process = None
            if not no_browser:
                console.print("[dim]Opening browser...[/dim]")
                browser_process = _open_browser_process(url)

            console.print("[dim]Press Ctrl+C to stop[/dim]")

            try:
                # Wait for the port-forward to complete (or be interrupted)
                pf_process.wait()
            except KeyboardInterrupt:
                pf_process.terminate()
                if browser_process:
                    browser_process.terminate()
                    console.print("\n[yellow]Port-forward and browser closed.[/yellow]")
                else:
                    console.print("\n[yellow]Port-forward stopped.[/yellow]")

        finally:
            # Clean up temp kubeconfig file
            if temp_kubeconfig and temp_kubeconfig.exists():
                temp_kubeconfig.unlink()

    except ValidationError as e:
        _handle_error(e)


@app.command()
def version() -> None:
    """Show version information."""
    from linto import __version__

    console.print(f"linto-deploy version {__version__}")


@kubeconfig_app.command("export")
def kubeconfig_export(
    profile: Annotated[
        str,
        typer.Argument(
            help="Profile name",
            metavar="PROFILE_NAME",
            autocompletion=_complete_profile,
        ),
    ],
    output: Annotated[
        Optional[str],
        typer.Option("-o", "--output", help="Write to file instead of stdout"),
    ] = None,
    merge: Annotated[
        bool,
        typer.Option("--merge", help="Merge into ~/.kube/config"),
    ] = False,
) -> None:
    """Export kubeconfig from profile.

    [bold]Example:[/bold]
        linto kubeconfig export my-profile
        linto kubeconfig export my-profile -o kubeconfig.yaml
        linto kubeconfig export my-profile --merge
    """
    from linto.model.validation import load_profile
    from linto.utils.kubeconfig import merge_into_kubeconfig

    try:
        profile_data = load_profile(profile)

        if not profile_data.kubeconfig:
            console.print(f"[red]Error:[/red] Profile '{profile}' has no kubeconfig configured.")
            console.print("[dim]Use 'linto profile set-kubeconfig <profile> <file>' to add one.[/dim]")
            raise typer.Exit(1)

        if merge:
            merge_into_kubeconfig(profile, profile_data.kubeconfig)
            console.print("[green]Merged kubeconfig into ~/.kube/config[/green]")
            msg = f"[dim]Context '{profile}' added. Use 'kubectl config use-context {profile}' to switch.[/dim]"
            console.print(msg)
        elif output:
            output_path = Path(output)
            with output_path.open("w") as f:
                yaml.dump(profile_data.kubeconfig, f, default_flow_style=False)
            console.print(f"[green]Kubeconfig written to {output_path}[/green]")
        else:
            # Output to stdout
            print(yaml.dump(profile_data.kubeconfig, default_flow_style=False))

    except ValidationError as e:
        _handle_error(e)


def _resolve_pod_name(
    service: str,
    namespace: str,
    kubeconfig: dict | None = None,
) -> str | None:
    """Resolve a service/label to a pod name.

    Args:
        service: Service identifier (pod/name, deployment/name, or label value)
        namespace: Kubernetes namespace
        kubeconfig: Optional kubeconfig dict

    Returns:
        Pod name or None if not found
    """
    from linto.utils.kubeconfig import KubeconfigContext

    with KubeconfigContext(kubeconfig):
        # If already a pod reference, extract the name
        if service.startswith("pod/"):
            return service[4:]

        # If deployment reference, get pods for the deployment
        if service.startswith("deployment/"):
            deployment_name = service[11:]
            result = subprocess.run(
                [
                    "kubectl", "get", "pods", "-n", namespace,
                    "-l", f"app.kubernetes.io/name={deployment_name}",
                    "-o", "jsonpath={.items[0].metadata.name}",
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=15,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()

        # Try as a label selector (app.kubernetes.io/name=<service>)
        result = subprocess.run(
            [
                "kubectl", "get", "pods", "-n", namespace,
                "-l", f"app.kubernetes.io/name={service}",
                "-o", "jsonpath={.items[0].metadata.name}",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()

        # Try as direct pod name
        result = subprocess.run(
            [
                "kubectl", "get", "pod", service, "-n", namespace,
                "-o", "jsonpath={.metadata.name}",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        if result.returncode == 0 and result.stdout.strip():
            return result.stdout.strip()

        return None


# Note: 'exec' is a Python reserved word, so we use exec_ as the function name
@app.command(name="exec")
def exec_(
    profile: Annotated[
        str,
        typer.Argument(
            help="Profile name",
            autocompletion=_complete_profile,
        ),
    ],
    service: Annotated[
        str,
        typer.Argument(
            help="Service/pod name",
            autocompletion=_complete_service,
        ),
    ],
    container: Annotated[
        Optional[str],
        typer.Option("--container", "-c", help="Container name for multi-container pods"),
    ] = None,
    command: Annotated[
        str,
        typer.Option("--command", help="Command to execute (non-interactive)"),
    ] = "/bin/sh",
) -> None:
    """Execute an interactive shell inside a running pod.

    [bold]Example:[/bold]
        linto exec my-profile studio-api
        linto exec my-profile studio-api --command "ls -la"
        linto exec my-profile pod/studio-api-xyz -c nginx
    """
    try:
        from linto.model.validation import load_profile
        from linto.utils.kubeconfig import KubeconfigContext

        profile_data = load_profile(profile)
        _check_backend_supported(profile_data)

        namespace = profile_data.k3s_namespace

        # Resolve service to pod name
        pod_name = _resolve_pod_name(service, namespace, profile_data.kubeconfig)
        if not pod_name:
            console.print(f"[red]Error:[/red] No running pod found for '{service}'")
            raise typer.Exit(1)

        # Build kubectl exec command
        kubectl_cmd = ["kubectl", "exec"]

        # Determine if interactive (no --command option means interactive)
        # Check if command was explicitly provided vs default
        is_interactive = command == "/bin/sh"
        if is_interactive:
            kubectl_cmd.extend(["-it"])

        kubectl_cmd.extend([pod_name, "-n", namespace])

        if container:
            kubectl_cmd.extend(["--container", container])

        kubectl_cmd.extend(["--", command])

        with KubeconfigContext(profile_data.kubeconfig):
            try:
                # Use Popen for interactive sessions
                process = subprocess.Popen(
                    kubectl_cmd,
                    stdin=sys.stdin,
                    stdout=sys.stdout,
                    stderr=sys.stderr,
                )
                process.wait()
                raise typer.Exit(process.returncode)
            except KeyboardInterrupt:
                process.terminate()
                console.print("\n[yellow]Session terminated.[/yellow]")
                raise typer.Exit(0)

    except ValidationError as e:
        _handle_error(e)


@app.command(name="port-forward")
def port_forward(
    profile: Annotated[
        str,
        typer.Argument(
            help="Profile name",
            autocompletion=_complete_profile,
        ),
    ],
    service: Annotated[
        str,
        typer.Argument(
            help="Service/pod name",
            autocompletion=_complete_service,
        ),
    ],
    port_spec: Annotated[
        Optional[str],
        typer.Argument(help="Port specification: [local_port:]remote_port"),
    ] = None,
    address: Annotated[
        str,
        typer.Option("--address", "-a", help="Local address to bind to"),
    ] = "127.0.0.1",
) -> None:
    """Forward local ports to cluster services.

    [bold]Example:[/bold]
        linto port-forward my-profile studio-api 8080:80
        linto port-forward my-profile studio-api 8080
        linto pf my-profile studio-api 8080:80
    """
    try:
        from linto.model.validation import load_profile
        from linto.utils.kubeconfig import KubeconfigContext

        profile_data = load_profile(profile)
        _check_backend_supported(profile_data)

        namespace = profile_data.k3s_namespace

        # Resolve service to pod name
        pod_name = _resolve_pod_name(service, namespace, profile_data.kubeconfig)
        if not pod_name:
            console.print(f"[red]Error:[/red] No running pod found for '{service}'")
            raise typer.Exit(1)

        # Parse port specification
        local_port: str
        remote_port: str

        if port_spec:
            if ":" in port_spec:
                local_port, remote_port = port_spec.split(":", 1)
            else:
                local_port = remote_port = port_spec
        else:
            # Auto-detect port from pod spec
            with KubeconfigContext(profile_data.kubeconfig):
                result = subprocess.run(
                    [
                        "kubectl", "get", "pod", pod_name, "-n", namespace,
                        "-o", "jsonpath={.spec.containers[0].ports[0].containerPort}",
                    ],
                    capture_output=True,
                    text=True,
                    check=False,
                    timeout=15,
                )
                if result.returncode == 0 and result.stdout.strip():
                    local_port = remote_port = result.stdout.strip()
                else:
                    console.print("[red]Error:[/red] Could not auto-detect port. Please specify port_spec.")
                    raise typer.Exit(1)

        # Build kubectl port-forward command
        kubectl_cmd = [
            "kubectl", "port-forward",
            pod_name,
            f"{local_port}:{remote_port}",
            "-n", namespace,
            "--address", address,
        ]

        console.print(f"Forwarding {address}:{local_port} -> {service}:{remote_port}")
        console.print("[dim]Press Ctrl+C to stop[/dim]")

        with KubeconfigContext(profile_data.kubeconfig):
            try:
                process = subprocess.Popen(
                    kubectl_cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                )
                process.wait()
            except KeyboardInterrupt:
                process.terminate()
                console.print("\n[yellow]Port-forward stopped.[/yellow]")
                raise typer.Exit(0)

    except ValidationError as e:
        _handle_error(e)


# Register pf as alias for port-forward
def _port_forward_alias(
    profile: Annotated[
        str,
        typer.Argument(
            help="Profile name",
            autocompletion=_complete_profile,
        ),
    ],
    service: Annotated[
        str,
        typer.Argument(
            help="Service/pod name",
            autocompletion=_complete_service,
        ),
    ],
    port_spec: Annotated[
        Optional[str],
        typer.Argument(help="Port specification: [local_port:]remote_port"),
    ] = None,
    address: Annotated[
        str,
        typer.Option("--address", "-a", help="Local address to bind to"),
    ] = "127.0.0.1",
) -> None:
    """Alias for port-forward command."""
    port_forward(profile, service, port_spec, address)


app.command(name="pf", hidden=True)(_port_forward_alias)


@app.command()
def backup(
    profile: Annotated[
        str,
        typer.Argument(
            help="Profile name",
            autocompletion=_complete_profile,
        ),
    ],
    output: Annotated[
        Optional[str],
        typer.Option("--output", "-o", help="Output directory"),
    ] = None,
    databases: Annotated[
        Optional[str],
        typer.Option("--databases", "-d", help="Comma-separated list of databases to backup"),
    ] = None,
) -> None:
    """Backup MongoDB and PostgreSQL databases to local files.

    [bold]Example:[/bold]
        linto backup my-profile
        linto backup my-profile -o ./backups
        linto backup my-profile -d studio-mongodb,live-postgres
    """
    try:
        from linto.backup import run_backup
        from linto.model.validation import load_profile

        profile_data = load_profile(profile)
        _check_backend_supported(profile_data)

        exit_code = run_backup(profile, output, databases)
        raise typer.Exit(exit_code)

    except ValidationError as e:
        _handle_error(e)


@profile_app.command("set-kubeconfig")
def profile_set_kubeconfig(
    profile: Annotated[
        str,
        typer.Argument(
            help="Profile name",
            metavar="PROFILE_NAME",
            autocompletion=_complete_profile,
        ),
    ],
    kubeconfig_file: Annotated[
        str,
        typer.Argument(
            help="Path to kubeconfig file",
            metavar="KUBECONFIG_FILE",
        ),
    ],
) -> None:
    """Set kubeconfig for a profile.

    [bold]Example:[/bold]
        linto profile set-kubeconfig my-profile /path/to/kubeconfig.yaml
    """
    from linto.model.validation import load_profile, save_profile
    from linto.utils.kubeconfig import get_server_url, load_kubeconfig

    try:
        # Load and validate kubeconfig
        kubeconfig_path = Path(kubeconfig_file).expanduser()
        try:
            kubeconfig = load_kubeconfig(kubeconfig_path)
        except FileNotFoundError:
            console.print(f"[red]Error:[/red] Kubeconfig file not found: {kubeconfig_path}")
            raise typer.Exit(1)
        except ValueError as e:
            console.print(f"[red]Error:[/red] Invalid kubeconfig: {e}")
            raise typer.Exit(1)

        # Load existing profile
        profile_data = load_profile(profile)

        # Update kubeconfig field
        profile_data.kubeconfig = kubeconfig

        # Save profile
        save_profile(profile_data)

        server_url = get_server_url(kubeconfig)
        console.print(f"[green]Kubeconfig set for profile '{profile}'[/green]")
        console.print(f"[dim]Server: {server_url}[/dim]")

    except ValidationError as e:
        _handle_error(e)


if __name__ == "__main__":
    app()
