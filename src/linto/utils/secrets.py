"""Secret generation utilities."""

import secrets
import string

from linto.model.profile import ProfileConfig


def generate_password(length: int = 32) -> str:
    """Generate a secure random password."""
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def generate_crypt_key(length: int = 10) -> str:
    """Generate a crypt key for session encryption.

    Args:
        length: Length of the key (default 10)

    Returns:
        Alphanumeric crypt key
    """
    # Use uppercase letters and digits for crypt key
    alphabet = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def generate_fernet_key() -> str:
    """Generate a Fernet encryption key (base64-encoded 32 bytes).

    Returns:
        URL-safe base64-encoded 32-byte key
    """
    import base64

    key = secrets.token_bytes(32)
    return base64.urlsafe_b64encode(key).decode()


def generate_secrets(profile: ProfileConfig) -> ProfileConfig:
    """Fill in any missing secrets with generated values.

    Returns a new ProfileConfig with all secrets populated.
    """
    data = profile.model_dump()

    # Core secrets
    if not data.get("redis_password"):
        data["redis_password"] = generate_password()
    if not data.get("jwt_secret"):
        data["jwt_secret"] = generate_password()
    if not data.get("jwt_refresh_secret"):
        data["jwt_refresh_secret"] = generate_password()
    if not data.get("super_admin_password"):
        data["super_admin_password"] = generate_password(16)

    # Session secrets (for Live Session)
    if data.get("live_session_enabled"):
        if not data.get("session_postgres_password"):
            data["session_postgres_password"] = generate_password()
        if not data.get("session_crypt_key"):
            data["session_crypt_key"] = generate_crypt_key(10)

    # LLM secrets
    if data.get("llm_enabled"):
        if not data.get("llm_postgres_password"):
            data["llm_postgres_password"] = generate_password()
        if not data.get("llm_redis_password"):
            data["llm_redis_password"] = generate_password()
        if not data.get("llm_encryption_key"):
            data["llm_encryption_key"] = generate_fernet_key()
        if not data.get("llm_admin_password"):
            data["llm_admin_password"] = generate_password(16)

    return ProfileConfig(**data)
