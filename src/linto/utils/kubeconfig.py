"""Kubeconfig utilities for embedded cluster credentials."""

import os
import tempfile
from pathlib import Path
from typing import Any

import yaml


def load_kubeconfig(path: Path) -> dict[str, Any]:
    """Load and validate a kubeconfig file.

    Args:
        path: Path to kubeconfig file

    Returns:
        Parsed kubeconfig dict

    Raises:
        FileNotFoundError: If file doesn't exist
        ValueError: If not valid kubeconfig
    """
    if not path.exists():
        raise FileNotFoundError(f"Kubeconfig not found: {path}")

    with path.open() as f:
        data = yaml.safe_load(f)

    # Basic validation
    if not isinstance(data, dict):
        raise ValueError("Invalid kubeconfig: not a dict")
    if data.get("kind") != "Config":
        raise ValueError("Invalid kubeconfig: missing kind=Config")
    if not data.get("clusters"):
        raise ValueError("Invalid kubeconfig: no clusters defined")

    return data


def get_server_url(kubeconfig: dict) -> str:
    """Extract server URL from kubeconfig.

    Args:
        kubeconfig: Parsed kubeconfig dict

    Returns:
        Server URL string
    """
    clusters = kubeconfig.get("clusters", [])
    if clusters:
        return clusters[0].get("cluster", {}).get("server", "unknown")
    return "unknown"


def extract_current_context() -> dict[str, Any] | None:
    """Extract kubeconfig from current kubectl context.

    Returns:
        Kubeconfig dict or None if not available
    """
    # Try KUBECONFIG env var first, then default location
    kubeconfig_path = os.environ.get("KUBECONFIG", str(Path.home() / ".kube" / "config"))

    path = Path(kubeconfig_path)
    if not path.exists():
        return None

    try:
        return load_kubeconfig(path)
    except (ValueError, yaml.YAMLError):
        return None


class KubeconfigContext:
    """Context manager for using profile's embedded kubeconfig."""

    def __init__(self, kubeconfig: dict | None):
        self.kubeconfig = kubeconfig
        self.temp_file: Path | None = None
        self.original_env: str | None = None

    def __enter__(self) -> "KubeconfigContext":
        if self.kubeconfig is None:
            return self

        # Create temp file with kubeconfig
        fd, path = tempfile.mkstemp(suffix=".yaml", prefix="kubeconfig-")
        self.temp_file = Path(path)

        with os.fdopen(fd, "w") as f:
            yaml.dump(self.kubeconfig, f)

        # Save and set KUBECONFIG env var
        self.original_env = os.environ.get("KUBECONFIG")
        os.environ["KUBECONFIG"] = str(self.temp_file)

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        # Restore original KUBECONFIG
        if self.original_env is not None:
            os.environ["KUBECONFIG"] = self.original_env
        elif "KUBECONFIG" in os.environ and self.kubeconfig is not None:
            del os.environ["KUBECONFIG"]

        # Clean up temp file
        if self.temp_file and self.temp_file.exists():
            self.temp_file.unlink()

        return False

    @property
    def path(self) -> Path | None:
        """Return path to temp kubeconfig file."""
        return self.temp_file


def merge_into_kubeconfig(profile_name: str, kubeconfig: dict) -> None:
    """Merge profile kubeconfig into ~/.kube/config.

    Args:
        profile_name: Name to use for the context
        kubeconfig: Kubeconfig to merge
    """
    kube_dir = Path.home() / ".kube"
    kube_dir.mkdir(parents=True, exist_ok=True)
    config_path = kube_dir / "config"

    # Load existing config or create new
    if config_path.exists():
        with config_path.open() as f:
            existing = yaml.safe_load(f) or {}
    else:
        existing = {
            "apiVersion": "v1",
            "kind": "Config",
            "clusters": [],
            "users": [],
            "contexts": [],
            "current-context": "",
        }

    # Extract from incoming kubeconfig
    cluster_name = f"{profile_name}-cluster"
    user_name = f"{profile_name}-user"
    context_name = profile_name

    incoming_cluster = kubeconfig.get("clusters", [{}])[0].get("cluster", {})
    incoming_user = kubeconfig.get("users", [{}])[0].get("user", {})
    incoming_context = kubeconfig.get("contexts", [{}])[0].get("context", {})

    # Remove existing entries with same name
    existing["clusters"] = [c for c in existing.get("clusters", []) if c.get("name") != cluster_name]
    existing["users"] = [u for u in existing.get("users", []) if u.get("name") != user_name]
    existing["contexts"] = [c for c in existing.get("contexts", []) if c.get("name") != context_name]

    # Add new entries
    existing["clusters"].append({
        "name": cluster_name,
        "cluster": incoming_cluster,
    })
    existing["users"].append({
        "name": user_name,
        "user": incoming_user,
    })
    existing["contexts"].append({
        "name": context_name,
        "context": {
            "cluster": cluster_name,
            "user": user_name,
            "namespace": incoming_context.get("namespace", "default"),
        },
    })

    # Write back
    with config_path.open("w") as f:
        yaml.dump(existing, f, default_flow_style=False)
