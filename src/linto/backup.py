"""Database backup utilities for MongoDB and PostgreSQL."""

import json
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.table import Table

from linto.model.validation import load_profile
from linto.utils.kubeconfig import KubeconfigContext

console = Console()

# Database configuration
# Labels match the Helm chart patterns: app.kubernetes.io/name=<chart-name>,app.kubernetes.io/component=<db-type>
DATABASE_CONFIGS = [
    {"name": "studio-mongodb", "type": "mongodb", "label": "app.kubernetes.io/name=linto-studio,app.kubernetes.io/component=mongodb"},
    {"name": "stt-mongodb", "type": "mongodb", "label": "app.kubernetes.io/name=linto-stt,app.kubernetes.io/component=mongodb"},
    {"name": "live-postgres", "type": "postgres", "label": "app.kubernetes.io/name=linto-live,app.kubernetes.io/component=postgres"},
    {"name": "llm-postgres", "type": "postgres", "label": "app.kubernetes.io/name=linto-llm,app.kubernetes.io/component=postgres"},
]


@dataclass
class BackupResult:
    """Result of a database backup operation."""

    name: str
    db_type: Literal["mongodb", "postgres"]
    file: str
    size_bytes: int
    status: Literal["success", "failed"]
    error: str | None = None


def find_database_pods(
    namespace: str,
    kubeconfig: dict | None = None,
    database_filter: list[str] | None = None,
) -> list[dict]:
    """Find running database pods in namespace.

    Args:
        namespace: Kubernetes namespace
        kubeconfig: Optional kubeconfig dict
        database_filter: Optional list of database names to filter

    Returns:
        List of dicts with keys: name, type, pod_name, label
    """
    found_pods = []

    with KubeconfigContext(kubeconfig):
        for db_config in DATABASE_CONFIGS:
            # Filter by database name if specified
            if database_filter and db_config["name"] not in database_filter:
                continue

            # Try to find pod with this label
            result = subprocess.run(
                [
                    "kubectl", "get", "pods", "-n", namespace,
                    "-l", db_config["label"],
                    "--field-selector=status.phase=Running",
                    "-o", "jsonpath={.items[0].metadata.name}",
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=15,
            )

            if result.returncode == 0 and result.stdout.strip():
                found_pods.append({
                    "name": db_config["name"],
                    "type": db_config["type"],
                    "pod_name": result.stdout.strip(),
                    "label": db_config["label"],
                })

    return found_pods


def backup_mongodb(
    pod_name: str,
    namespace: str,
    output_path: Path,
    kubeconfig: dict | None = None,
) -> BackupResult:
    """Backup MongoDB using mongodump.

    Command: kubectl exec <pod> -n <ns> -- mongodump --archive --gzip > output.gz

    Args:
        pod_name: Name of the MongoDB pod
        namespace: Kubernetes namespace
        output_path: Path to write backup file
        kubeconfig: Optional kubeconfig dict

    Returns:
        BackupResult with operation details
    """
    db_name = output_path.stem.replace(".gz", "")

    try:
        with KubeconfigContext(kubeconfig):
            # Run mongodump and stream to file
            kubectl_cmd = [
                "kubectl", "exec", pod_name, "-n", namespace,
                "--", "mongodump", "--archive", "--gzip",
            ]

            with output_path.open("wb") as f:
                process = subprocess.Popen(
                    kubectl_cmd,
                    stdout=f,
                    stderr=subprocess.PIPE,
                )
                _, stderr = process.communicate(timeout=600)  # 10 minute timeout

                if process.returncode != 0:
                    error_msg = stderr.decode() if stderr else "Unknown error"
                    return BackupResult(
                        name=db_name,
                        db_type="mongodb",
                        file=str(output_path),
                        size_bytes=0,
                        status="failed",
                        error=error_msg.strip(),
                    )

            # Get file size
            size_bytes = output_path.stat().st_size

            return BackupResult(
                name=db_name,
                db_type="mongodb",
                file=str(output_path),
                size_bytes=size_bytes,
                status="success",
            )

    except subprocess.TimeoutExpired:
        return BackupResult(
            name=db_name,
            db_type="mongodb",
            file=str(output_path),
            size_bytes=0,
            status="failed",
            error="Backup timed out after 10 minutes",
        )
    except Exception as e:
        return BackupResult(
            name=db_name,
            db_type="mongodb",
            file=str(output_path),
            size_bytes=0,
            status="failed",
            error=str(e),
        )


def backup_postgres(
    pod_name: str,
    namespace: str,
    output_path: Path,
    kubeconfig: dict | None = None,
) -> BackupResult:
    """Backup PostgreSQL using pg_dumpall.

    Command: kubectl exec <pod> -n <ns> -- sh -c "pg_dumpall -U postgres | gzip" > output.sql.gz

    Args:
        pod_name: Name of the PostgreSQL pod
        namespace: Kubernetes namespace
        output_path: Path to write backup file
        kubeconfig: Optional kubeconfig dict

    Returns:
        BackupResult with operation details
    """
    db_name = output_path.stem.replace(".sql", "")

    try:
        with KubeconfigContext(kubeconfig):
            # Run pg_dumpall with gzip and stream to file
            kubectl_cmd = [
                "kubectl", "exec", pod_name, "-n", namespace,
                "--", "sh", "-c", "pg_dumpall -U postgres | gzip",
            ]

            with output_path.open("wb") as f:
                process = subprocess.Popen(
                    kubectl_cmd,
                    stdout=f,
                    stderr=subprocess.PIPE,
                )
                _, stderr = process.communicate(timeout=600)  # 10 minute timeout

                if process.returncode != 0:
                    error_msg = stderr.decode() if stderr else "Unknown error"
                    return BackupResult(
                        name=db_name,
                        db_type="postgres",
                        file=str(output_path),
                        size_bytes=0,
                        status="failed",
                        error=error_msg.strip(),
                    )

            # Get file size
            size_bytes = output_path.stat().st_size

            return BackupResult(
                name=db_name,
                db_type="postgres",
                file=str(output_path),
                size_bytes=size_bytes,
                status="success",
            )

    except subprocess.TimeoutExpired:
        return BackupResult(
            name=db_name,
            db_type="postgres",
            file=str(output_path),
            size_bytes=0,
            status="failed",
            error="Backup timed out after 10 minutes",
        )
    except Exception as e:
        return BackupResult(
            name=db_name,
            db_type="postgres",
            file=str(output_path),
            size_bytes=0,
            status="failed",
            error=str(e),
        )


def write_manifest(
    output_dir: Path,
    profile: str,
    results: list[BackupResult],
) -> None:
    """Write manifest.json with backup metadata.

    Args:
        output_dir: Directory containing backups
        profile: Profile name
        results: List of BackupResult objects
    """
    manifest = {
        "profile": profile,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "databases": [
            {
                "name": r.name,
                "type": r.db_type,
                "file": Path(r.file).name,
                "size_bytes": r.size_bytes,
                "status": r.status,
                "error": r.error,
            }
            for r in results
        ],
    }

    manifest_path = output_dir / "manifest.json"
    with manifest_path.open("w") as f:
        json.dump(manifest, f, indent=2)


def _format_size(size_bytes: int) -> str:
    """Format bytes as human-readable size."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"


def run_backup(
    profile_name: str,
    output_dir: str | None = None,
    database_filter: str | None = None,
    base_dir: Path | None = None,
) -> int:
    """Run backup for all databases in profile.

    Args:
        profile_name: Profile to backup
        output_dir: Custom output directory
        database_filter: Comma-separated list of database names
        base_dir: Base directory for .linto folder

    Returns:
        0 = all success, 1 = all failed/no databases, 2 = partial
    """
    # Load profile
    profile_data = load_profile(profile_name)
    namespace = profile_data.k3s_namespace

    # Parse database filter
    db_filter: list[str] | None = None
    if database_filter:
        db_filter = [d.strip() for d in database_filter.split(",")]

    # Find database pods
    console.print(f"[cyan]Finding databases in namespace '{namespace}'...[/cyan]")
    db_pods = find_database_pods(namespace, profile_data.kubeconfig, db_filter)

    if not db_pods:
        console.print("[red]Error:[/red] No running database pods found.")
        if db_filter:
            console.print(f"[dim]Requested databases: {', '.join(db_filter)}[/dim]")
        return 1

    console.print(f"[green]Found {len(db_pods)} database(s) to backup[/green]")

    # Determine output directory
    if output_dir:
        backup_dir = Path(output_dir)
    else:
        if base_dir is None:
            base_dir = Path.cwd()
        timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        backup_dir = base_dir / ".linto" / "backups" / profile_name / timestamp

    # Create output directory
    backup_dir.mkdir(parents=True, exist_ok=True)
    console.print(f"[dim]Output directory: {backup_dir}[/dim]")

    # Run backups with progress
    results: list[BackupResult] = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console,
    ) as progress:
        for db in db_pods:
            task = progress.add_task(f"Backing up {db['name']}...", total=None)

            if db["type"] == "mongodb":
                output_path = backup_dir / f"{db['name']}.gz"
                result = backup_mongodb(
                    db["pod_name"],
                    namespace,
                    output_path,
                    profile_data.kubeconfig,
                )
            else:  # postgres
                output_path = backup_dir / f"{db['name']}.sql.gz"
                result = backup_postgres(
                    db["pod_name"],
                    namespace,
                    output_path,
                    profile_data.kubeconfig,
                )

            results.append(result)
            progress.remove_task(task)

            # Show immediate result
            if result.status == "success":
                console.print(f"  [green]OK[/green] {db['name']} ({_format_size(result.size_bytes)})")
            else:
                console.print(f"  [red]FAILED[/red] {db['name']}: {result.error}")

    # Write manifest
    write_manifest(backup_dir, profile_name, results)

    # Print summary table
    console.print()
    table = Table(title="Backup Summary")
    table.add_column("Database", style="cyan")
    table.add_column("Type", style="dim")
    table.add_column("Status")
    table.add_column("Size", style="yellow")
    table.add_column("File", style="dim")

    for r in results:
        status_str = "[green]success[/green]" if r.status == "success" else "[red]failed[/red]"
        size_str = _format_size(r.size_bytes) if r.status == "success" else "-"
        file_str = Path(r.file).name if r.status == "success" else "-"
        table.add_row(r.name, r.db_type, status_str, size_str, file_str)

    console.print(table)

    # Determine exit code
    success_count = sum(1 for r in results if r.status == "success")
    if success_count == len(results):
        console.print(f"\n[green]All {len(results)} backup(s) completed successfully![/green]")
        console.print(f"[dim]Manifest: {backup_dir / 'manifest.json'}[/dim]")
        return 0
    elif success_count == 0:
        console.print(f"\n[red]All {len(results)} backup(s) failed![/red]")
        return 1
    else:
        console.print(f"\n[yellow]{success_count}/{len(results)} backup(s) completed.[/yellow]")
        console.print(f"[dim]Manifest: {backup_dir / 'manifest.json'}[/dim]")
        return 2
