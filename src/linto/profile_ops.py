"""Profile management operations."""

from pathlib import Path

from linto.model.profile import ProfileConfig
from linto.model.validation import ValidationError, load_profile, save_profile


def list_profiles(base_dir: Path | None = None) -> list[ProfileConfig]:
    """
    List all profiles in the profiles directory.

    Args:
        base_dir: Base directory for .linto folder. Defaults to cwd.

    Returns:
        List of ProfileConfig objects, sorted by name.
    """
    if base_dir is None:
        base_dir = Path.cwd()
    profiles_dir = base_dir / ".linto" / "profiles"

    if not profiles_dir.exists():
        return []

    profiles = []
    for profile_file in profiles_dir.glob("*.json"):
        try:
            profile = load_profile(profile_file.stem, base_dir)
            profiles.append(profile)
        except ValidationError:
            # Skip invalid profiles
            continue

    return sorted(profiles, key=lambda p: p.name)


def delete_profile(name: str, base_dir: Path | None = None) -> None:
    """
    Delete a profile by name.

    Args:
        name: Profile name to delete.
        base_dir: Base directory for .linto folder. Defaults to cwd.

    Raises:
        ValidationError: If profile doesn't exist (PROFILE_NOT_FOUND).
    """
    if base_dir is None:
        base_dir = Path.cwd()
    profile_path = base_dir / ".linto" / "profiles" / f"{name}.json"

    if not profile_path.exists():
        raise ValidationError(
            "PROFILE_NOT_FOUND",
            f"Profile '{name}' not found",
        )

    profile_path.unlink()


def copy_profile(src: str, dst: str, base_dir: Path | None = None) -> Path:
    """
    Copy a profile to a new name.

    Args:
        src: Source profile name.
        dst: Destination profile name.
        base_dir: Base directory for .linto folder. Defaults to cwd.

    Returns:
        Path to the new profile file.

    Raises:
        ValidationError: If source doesn't exist (PROFILE_NOT_FOUND)
                        or destination already exists (PROFILE_EXISTS).
    """
    if base_dir is None:
        base_dir = Path.cwd()

    # Load source profile (raises PROFILE_NOT_FOUND if not found)
    source_profile = load_profile(src, base_dir)

    # Check destination doesn't exist
    dst_path = base_dir / ".linto" / "profiles" / f"{dst}.json"
    if dst_path.exists():
        raise ValidationError(
            "PROFILE_EXISTS",
            f"Profile '{dst}' already exists",
        )

    # Create new profile with new name
    new_profile = source_profile.model_copy(update={"name": dst})

    # Save new profile
    return save_profile(new_profile, base_dir)


def get_profile_summary(profile: ProfileConfig) -> dict[str, str]:
    """
    Get summary information for display in list view.

    Args:
        profile: ProfileConfig instance.

    Returns:
        Dict with keys: name, backend, domain, services (comma-separated string).
    """
    services = []
    if profile.studio_enabled:
        services.append("studio")
    if profile.stt_enabled:
        services.append("stt")
    if profile.live_session_enabled:
        services.append("live")
    if profile.llm_enabled:
        services.append("llm")

    return {
        "name": profile.name,
        "backend": profile.backend.value,
        "domain": profile.domain,
        "services": ", ".join(services) if services else "none",
    }
