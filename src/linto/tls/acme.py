"""ACME/Let's Encrypt TLS configuration."""

import os
from pathlib import Path
from typing import Any

from linto.model.validation import ValidationError


def generate_acme_traefik_config(
    email: str,
    domain: str,
) -> dict[str, Any]:
    """Generate Traefik ACME configuration.

    Args:
        email: Email address for ACME registration
        domain: Domain for certificate

    Returns:
        Traefik configuration dictionary for ACME
    """
    return {
        "certificatesResolvers": {
            "leresolver": {
                "acme": {
                    "email": email,
                    "storage": "/acme.json",
                    "httpChallenge": {
                        "entryPoint": "web",
                    },
                },
            },
        },
    }


def setup_acme_storage(base_dir: Path) -> Path:
    """Create acme.json with correct permissions (600).

    Args:
        base_dir: Base directory for .linto folder

    Returns:
        Path to acme.json file

    Raises:
        ValidationError: If unable to create or set permissions
    """
    tls_dir = base_dir / ".linto" / "tls"
    tls_dir.mkdir(parents=True, exist_ok=True)

    acme_path = tls_dir / "acme.json"

    try:
        # Create empty file if it doesn't exist
        if not acme_path.exists():
            acme_path.touch()

        # Set permissions to 600 (required by Traefik)
        os.chmod(acme_path, 0o600)

        return acme_path

    except OSError as e:
        raise ValidationError(
            "ACME_SETUP_FAILED",
            f"Failed to create or set permissions on acme.json: {e}",
        ) from e


def validate_acme_config(email: str, domain: str) -> bool:
    """Validate ACME configuration.

    Args:
        email: Email address for ACME registration
        domain: Domain for certificate

    Returns:
        True if configuration is valid

    Raises:
        ValidationError: If configuration is invalid
    """
    import re

    # Validate email
    email_pattern = r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$"
    if not re.match(email_pattern, email):
        raise ValidationError(
            "INVALID_ACME_EMAIL",
            f"Invalid email address for ACME: {email}",
        )

    # Domain cannot be localhost for ACME
    if domain == "localhost":
        raise ValidationError(
            "INVALID_ACME_DOMAIN",
            "ACME/Let's Encrypt cannot be used with localhost. Use a real domain or mkcert.",
        )

    return True
