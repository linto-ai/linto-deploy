"""Validation utilities for deployment configuration."""

from pathlib import Path

from linto.model.profile import ProfileConfig


class ValidationError(Exception):
    """Validation error with error code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(f"{code}: {message}")


def validate_profile_exists(profile_name: str, base_dir: Path | None = None) -> Path:
    """Validate that a profile exists and return its path."""
    if base_dir is None:
        base_dir = Path.cwd()
    profile_path = base_dir / ".linto" / "profiles" / f"{profile_name}.json"
    if not profile_path.exists():
        raise ValidationError(
            "PROFILE_NOT_FOUND",
            f"Profile '{profile_name}' not found at {profile_path}",
        )
    return profile_path


def load_profile(profile_name: str, base_dir: Path | None = None) -> ProfileConfig:
    """Load a profile from disk."""
    import json

    profile_path = validate_profile_exists(profile_name, base_dir)
    with profile_path.open() as f:
        data = json.load(f)
    return ProfileConfig(**data)


def save_profile(profile: ProfileConfig, base_dir: Path | None = None) -> Path:
    """Save a profile to disk."""
    import json

    if base_dir is None:
        base_dir = Path.cwd()
    profiles_dir = base_dir / ".linto" / "profiles"
    profiles_dir.mkdir(parents=True, exist_ok=True)
    profile_path = profiles_dir / f"{profile.name}.json"
    with profile_path.open("w") as f:
        json.dump(profile.model_dump(), f, indent=2)
    return profile_path
