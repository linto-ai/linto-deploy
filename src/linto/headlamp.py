"""Manage Headlamp (Kubernetes UI) on a LinTO cluster.

Exposes install/upgrade/uninstall + helpers for opening the UI via port-forward
with a freshly-minted bearer token.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path

import yaml

from linto.model.profile import ProfileConfig

NAMESPACE = "headlamp"
RELEASE_NAME = "headlamp"
CHART_REPO_URL = "https://kubernetes-sigs.github.io/headlamp/"
CHART_NAME = "headlamp/headlamp"
SERVICE_ACCOUNT = "headlamp"
CLUSTER_ROLE_BINDING = "headlamp-admin"
DEFAULT_LOCAL_PORT = 4466

# Headlamp service listens on port 80 by default (proxy to container port 4466).
SERVICE_PORT = 80


def _kubectl_args(profile: ProfileConfig) -> tuple[list[str], Path | None]:
    """Return ``(args, tmp_path)`` with ``--kubeconfig`` pointing at a temp file.

    Caller is responsible for ``tmp_path.unlink(missing_ok=True)`` once done.
    If the profile has no kubeconfig, returns ``([], None)``.
    """
    if not profile.kubeconfig:
        return [], None
    fd, path = tempfile.mkstemp(suffix=".yaml", prefix="linto-kubeconfig-")
    with open(fd, "w") as f:
        yaml.dump(profile.kubeconfig, f)
    return ["--kubeconfig", path], Path(path)


_CLUSTER_ADMIN_BINDING = f"""\
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: {CLUSTER_ROLE_BINDING}
  labels:
    app.kubernetes.io/managed-by: linto-deploy
    app.kubernetes.io/part-of: headlamp
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: cluster-admin
subjects:
- kind: ServiceAccount
  name: {SERVICE_ACCOUNT}
  namespace: {NAMESPACE}
"""


def install(profile: ProfileConfig) -> None:
    """Install or upgrade Headlamp on the cluster described by ``profile``.

    Creates the ``headlamp`` namespace, runs ``helm upgrade --install`` with
    minimal values, and binds the service account to ``cluster-admin`` so the
    UI can read/write every resource the connected user could.
    """
    kargs, tmp = _kubectl_args(profile)
    try:
        subprocess.run(
            [
                "helm",
                "repo",
                "add",
                "headlamp",
                CHART_REPO_URL,
                "--force-update",
            ],
            check=True,
            timeout=30,
        )
        subprocess.run(["helm", "repo", "update", "headlamp"], check=True, timeout=60)
        subprocess.run(
            [
                "helm",
                *kargs,
                "upgrade",
                "--install",
                RELEASE_NAME,
                CHART_NAME,
                "--namespace",
                NAMESPACE,
                "--create-namespace",
                "--set",
                "serviceAccount.create=true",
                "--set",
                f"serviceAccount.name={SERVICE_ACCOUNT}",
                "--wait",
                "--timeout",
                "5m",
            ],
            check=True,
            timeout=360,
        )
        # Bind SA → cluster-admin so Headlamp can do anything in the cluster.
        subprocess.run(
            ["kubectl", *kargs, "apply", "-f", "-"],
            input=_CLUSTER_ADMIN_BINDING,
            text=True,
            check=True,
            timeout=30,
        )
    finally:
        if tmp:
            tmp.unlink(missing_ok=True)


def uninstall(profile: ProfileConfig, *, purge_namespace: bool = False) -> None:
    """Uninstall the Helm release, drop the ClusterRoleBinding, optionally purge ns."""
    kargs, tmp = _kubectl_args(profile)
    try:
        subprocess.run(
            ["helm", *kargs, "uninstall", RELEASE_NAME, "-n", NAMESPACE],
            check=False,
            timeout=120,
        )
        subprocess.run(
            ["kubectl", *kargs, "delete", "clusterrolebinding", CLUSTER_ROLE_BINDING],
            check=False,
            timeout=30,
        )
        if purge_namespace:
            subprocess.run(
                ["kubectl", *kargs, "delete", "namespace", NAMESPACE],
                check=False,
                timeout=120,
            )
    finally:
        if tmp:
            tmp.unlink(missing_ok=True)


def create_token(profile: ProfileConfig, *, duration: str = "24h") -> str:
    """Mint a fresh bearer token for the Headlamp service account."""
    kargs, tmp = _kubectl_args(profile)
    try:
        result = subprocess.run(
            [
                "kubectl",
                *kargs,
                "create",
                "token",
                SERVICE_ACCOUNT,
                "-n",
                NAMESPACE,
                f"--duration={duration}",
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        return result.stdout.strip()
    finally:
        if tmp:
            tmp.unlink(missing_ok=True)


def copy_to_clipboard(text: str) -> str | None:
    """Copy ``text`` to the system clipboard.

    Tries ``wl-copy`` (Wayland), ``xclip``, ``xsel`` in order. Returns the
    name of the tool used, or ``None`` if no clipboard tool is available
    (caller should fall back to printing the token).
    """
    import shutil

    for cmd_name, cmd in (
        ("wl-copy", ["wl-copy"]),
        ("xclip", ["xclip", "-selection", "clipboard"]),
        ("xsel", ["xsel", "--clipboard", "--input"]),
    ):
        if shutil.which(cmd_name) is None:
            continue
        try:
            subprocess.run(cmd, input=text, text=True, check=True, timeout=5)
            return cmd_name
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
            continue
    return None


def status(profile: ProfileConfig) -> dict:
    """Return ``kubectl get pods -n headlamp -o json`` as a Python dict."""
    kargs, tmp = _kubectl_args(profile)
    try:
        result = subprocess.run(
            [
                "kubectl",
                *kargs,
                "get",
                "pods",
                "-n",
                NAMESPACE,
                "-l",
                f"app.kubernetes.io/instance={RELEASE_NAME}",
                "-o",
                "json",
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if result.returncode != 0:
            return {"items": [], "_error": result.stderr.strip()}
        return json.loads(result.stdout)
    finally:
        if tmp:
            tmp.unlink(missing_ok=True)
