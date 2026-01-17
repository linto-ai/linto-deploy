"""Docker utilities."""

import subprocess
from pathlib import Path

from linto.model.validation import ValidationError


def check_docker_running() -> bool:
    """Check if Docker daemon is accessible."""
    try:
        result = subprocess.run(
            ["docker", "info"],
            capture_output=True,
            check=False,
            timeout=10,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def check_swarm_mode() -> bool:
    """Check if Docker is in Swarm mode.

    Returns:
        True if Docker is in Swarm mode (manager or worker)
    """
    try:
        result = subprocess.run(
            ["docker", "info", "--format", "{{.Swarm.LocalNodeState}}"],
            capture_output=True,
            text=True,
            check=False,
            timeout=10,
        )
        return result.returncode == 0 and result.stdout.strip() == "active"
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def init_swarm() -> bool:
    """Initialize Docker Swarm if not already initialized.

    Returns:
        True if Swarm is initialized (either already was or just initialized)

    Raises:
        ValidationError: If Swarm initialization fails
    """
    if check_swarm_mode():
        return True

    try:
        result = subprocess.run(
            ["docker", "swarm", "init"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if result.returncode == 0:
            return True
        # Try with advertise-addr if automatic fails
        result = subprocess.run(
            ["docker", "swarm", "init", "--advertise-addr", "127.0.0.1"],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        return result.returncode == 0
    except subprocess.TimeoutExpired:
        raise ValidationError(
            "SWARM_INIT_TIMEOUT",
            "Docker swarm init timed out",
        )
    except FileNotFoundError:
        raise ValidationError(
            "DOCKER_NOT_FOUND",
            "Docker command not found",
        )


def create_overlay_network(network_name: str) -> bool:
    """Create an overlay network for Swarm.

    Args:
        network_name: Name of the network to create

    Returns:
        True if network was created or already exists
    """
    try:
        # Check if network exists
        result = subprocess.run(
            ["docker", "network", "inspect", network_name],
            capture_output=True,
            check=False,
            timeout=10,
        )
        if result.returncode == 0:
            return True

        # Create overlay network
        result = subprocess.run(
            [
                "docker",
                "network",
                "create",
                "--driver",
                "overlay",
                "--attachable",
                network_name,
            ],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return False


def run_docker_compose(
    compose_dir: Path,
    command: list[str],
    *,
    capture_output: bool = False,
) -> subprocess.CompletedProcess[str]:
    """Run docker compose command in the specified directory.

    Args:
        compose_dir: Directory containing docker-compose.yml
        command: Docker compose subcommand and arguments
        capture_output: Whether to capture stdout/stderr

    Returns:
        Completed process result

    Raises:
        ValidationError: If docker compose command fails
    """
    if not check_docker_running():
        raise ValidationError(
            "DOCKER_NOT_RUNNING",
            "Docker daemon is not accessible. Please start Docker.",
        )

    compose_file = compose_dir / "docker-compose.yml"
    if not compose_file.exists():
        raise ValidationError(
            "COMPOSE_GENERATION_FAILED",
            f"docker-compose.yml not found at {compose_file}",
        )

    full_command = [
        "docker",
        "compose",
        "-f",
        str(compose_file),
        *command,
    ]

    try:
        result = subprocess.run(
            full_command,
            cwd=compose_dir,
            capture_output=capture_output,
            text=True,
            check=False,
        )
        return result
    except subprocess.SubprocessError as e:
        raise ValidationError(
            "APPLY_FAILED",
            f"Docker compose command failed: {e}",
        ) from e


def run_docker_stack_deploy(
    stack_file: Path,
    stack_name: str = "linto",
) -> subprocess.CompletedProcess[str]:
    """Run docker stack deploy.

    Args:
        stack_file: Path to stack YAML file
        stack_name: Name for the stack

    Returns:
        Completed process result

    Raises:
        ValidationError: If docker stack deploy fails
    """
    if not check_docker_running():
        raise ValidationError(
            "DOCKER_NOT_RUNNING",
            "Docker daemon is not accessible. Please start Docker.",
        )

    if not check_swarm_mode():
        # Try to initialize swarm
        if not init_swarm():
            raise ValidationError(
                "SWARM_NOT_ACTIVE",
                "Docker is not in Swarm mode. Run 'docker swarm init' first.",
            )

    if not stack_file.exists():
        raise ValidationError(
            "STACK_FILE_NOT_FOUND",
            f"Stack file not found at {stack_file}",
        )

    # Ensure linto network exists
    create_overlay_network("linto")

    full_command = [
        "docker",
        "stack",
        "deploy",
        "-c",
        str(stack_file),
        stack_name,
    ]

    try:
        result = subprocess.run(
            full_command,
            capture_output=False,
            text=True,
            check=False,
        )
        return result
    except subprocess.SubprocessError as e:
        raise ValidationError(
            "APPLY_FAILED",
            f"Docker stack deploy failed: {e}",
        ) from e


def run_docker_stack_rm(stack_name: str = "linto") -> subprocess.CompletedProcess[str]:
    """Run docker stack rm.

    Args:
        stack_name: Name of the stack to remove

    Returns:
        Completed process result

    Raises:
        ValidationError: If docker stack rm fails
    """
    if not check_docker_running():
        raise ValidationError(
            "DOCKER_NOT_RUNNING",
            "Docker daemon is not accessible. Please start Docker.",
        )

    full_command = [
        "docker",
        "stack",
        "rm",
        stack_name,
    ]

    try:
        result = subprocess.run(
            full_command,
            capture_output=False,
            text=True,
            check=False,
        )
        return result
    except subprocess.SubprocessError as e:
        raise ValidationError(
            "DESTROY_FAILED",
            f"Docker stack rm failed: {e}",
        ) from e


def list_stack_services(stack_name: str = "linto") -> list[str]:
    """List services in a stack.

    Args:
        stack_name: Name of the stack

    Returns:
        List of service names
    """
    try:
        result = subprocess.run(
            ["docker", "stack", "services", "--format", "{{.Name}}", stack_name],
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
        if result.returncode == 0:
            return [s.strip() for s in result.stdout.strip().split("\n") if s.strip()]
        return []
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []
