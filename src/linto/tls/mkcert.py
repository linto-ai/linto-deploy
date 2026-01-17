"""mkcert integration for local TLS certificates."""

import shutil
import subprocess
from pathlib import Path

from linto.model.validation import ValidationError


def check_mkcert() -> bool:
    """Check if mkcert is installed."""
    return shutil.which("mkcert") is not None


def generate_certs(domain: str, output_dir: Path) -> tuple[Path, Path]:
    """Generate certificates using mkcert.

    Args:
        domain: Domain name for the certificate
        output_dir: Directory to write certificates

    Returns:
        Tuple of (cert_path, key_path)

    Raises:
        ValidationError: If mkcert is not installed or fails
    """
    if not check_mkcert():
        raise ValidationError(
            "MKCERT_NOT_INSTALLED",
            "mkcert is not installed. Please install it: https://github.com/FiloSottile/mkcert",
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    cert_path = output_dir / f"{domain}.pem"
    key_path = output_dir / f"{domain}-key.pem"

    # Build domain arguments
    domains = [domain]
    if domain != "localhost":
        domains.append(f"*.{domain}")

    try:
        subprocess.run(
            [
                "mkcert",
                "-cert-file",
                str(cert_path),
                "-key-file",
                str(key_path),
                *domains,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        raise ValidationError(
            "COMPOSE_GENERATION_FAILED",
            f"mkcert failed: {e.stderr}",
        ) from e

    return cert_path, key_path
