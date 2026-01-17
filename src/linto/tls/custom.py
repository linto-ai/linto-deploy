"""Custom TLS certificate handling."""

import shutil
from pathlib import Path

from linto.model.validation import ValidationError


def import_custom_certs(
    cert_path: Path,
    key_path: Path,
    domain: str,
    base_dir: Path,
) -> tuple[Path, Path]:
    """Copy and validate custom certificates.

    Args:
        cert_path: Path to certificate file
        key_path: Path to private key file
        domain: Domain name for certificate
        base_dir: Base directory for .linto folder

    Returns:
        Tuple of (destination_cert_path, destination_key_path)

    Raises:
        ValidationError: If certificates cannot be imported
    """
    # Validate source files exist
    if not cert_path.exists():
        raise ValidationError(
            "CERT_NOT_FOUND",
            f"Certificate file not found: {cert_path}",
        )

    if not key_path.exists():
        raise ValidationError(
            "KEY_NOT_FOUND",
            f"Private key file not found: {key_path}",
        )

    # Create destination directory
    certs_dir = base_dir / ".linto" / "tls" / "certs"
    certs_dir.mkdir(parents=True, exist_ok=True)

    # Destination paths use domain name
    dest_cert = certs_dir / f"{domain}.pem"
    dest_key = certs_dir / f"{domain}-key.pem"

    try:
        # Copy certificate
        shutil.copy2(cert_path, dest_cert)

        # Copy private key
        shutil.copy2(key_path, dest_key)

        return dest_cert, dest_key

    except OSError as e:
        raise ValidationError(
            "CERT_IMPORT_FAILED",
            f"Failed to import certificates: {e}",
        ) from e


def validate_certificate(cert_path: Path, domain: str) -> bool:
    """Validate certificate matches domain (best effort).

    This is a basic validation that checks if the certificate file
    exists and is readable. For full validation, use OpenSSL.

    Args:
        cert_path: Path to certificate file
        domain: Expected domain name

    Returns:
        True if certificate appears valid

    Raises:
        ValidationError: If certificate validation fails
    """
    if not cert_path.exists():
        raise ValidationError(
            "CERT_NOT_FOUND",
            f"Certificate file not found: {cert_path}",
        )

    try:
        # Try to read the certificate file
        content = cert_path.read_text()

        # Check for PEM format markers
        if "-----BEGIN CERTIFICATE-----" not in content:
            raise ValidationError(
                "INVALID_CERT_FORMAT",
                "Certificate file does not appear to be in PEM format",
            )

        return True

    except OSError as e:
        raise ValidationError(
            "CERT_READ_FAILED",
            f"Failed to read certificate file: {e}",
        ) from e


def validate_private_key(key_path: Path) -> bool:
    """Validate private key file (best effort).

    Args:
        key_path: Path to private key file

    Returns:
        True if key appears valid

    Raises:
        ValidationError: If key validation fails
    """
    if not key_path.exists():
        raise ValidationError(
            "KEY_NOT_FOUND",
            f"Private key file not found: {key_path}",
        )

    try:
        # Try to read the key file
        content = key_path.read_text()

        # Check for PEM format markers
        if "-----BEGIN" not in content or "PRIVATE KEY-----" not in content:
            raise ValidationError(
                "INVALID_KEY_FORMAT",
                "Key file does not appear to be in PEM format",
            )

        return True

    except OSError as e:
        raise ValidationError(
            "KEY_READ_FAILED",
            f"Failed to read private key file: {e}",
        ) from e
