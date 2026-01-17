"""Backend renderers for deployment artifacts."""

from pathlib import Path
from typing import TYPE_CHECKING, Any, Protocol

from linto.model.profile import DeploymentBackend

if TYPE_CHECKING:
    from linto.model.profile import ProfileConfig


class Backend(Protocol):
    """Backend interface for deployment renderers."""

    def render(self, profile: "ProfileConfig") -> dict[str, Any]:
        """Render deployment artifacts as dictionary."""
        ...

    def generate(
        self,
        profile_name: str,
        output_dir: str | None = None,
        base_dir: Path | None = None,
    ) -> Path:
        """Generate deployment files."""
        ...

    def apply(self, profile_name: str, base_dir: Path | None = None) -> None:
        """Apply deployment."""
        ...

    def destroy(
        self,
        profile_name: str,
        remove_files: bool = False,
        base_dir: Path | None = None,
    ) -> None:
        """Destroy deployment."""
        ...


def get_backend(backend_type: DeploymentBackend | str) -> Any:
    """Get backend renderer based on type.

    Args:
        backend_type: Backend type (compose or swarm)

    Returns:
        Backend module with render, generate, apply, destroy functions
    """
    # Normalize to enum if string
    if isinstance(backend_type, str):
        backend_type = DeploymentBackend(backend_type)

    if backend_type == DeploymentBackend.SWARM:
        from linto.backends import swarm

        return swarm
    elif backend_type == DeploymentBackend.K3S:
        from linto.backends import k3s

        return k3s
    else:
        from linto.backends import compose

        return compose


# Re-export compose functions for backwards compatibility
from linto.backends.compose import (  # noqa: E402
    apply_compose,
    destroy_compose,
    generate_compose,
    render_compose,
)

__all__ = [
    "render_compose",
    "generate_compose",
    "apply_compose",
    "destroy_compose",
    "get_backend",
    "Backend",
]
