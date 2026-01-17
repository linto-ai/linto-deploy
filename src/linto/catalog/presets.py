"""Preset configurations for common deployment scenarios."""

from linto.model.profile import ProfileConfig

PRESETS: dict[str, ProfileConfig] = {
    "minimal": ProfileConfig(
        name="minimal",
        domain="localhost",
        image_tag="latest-unstable",
        tls_mode="mkcert",
        studio_enabled=True,
        stt_enabled=False,
    ),
    "full": ProfileConfig(
        name="full",
        domain="localhost",
        image_tag="latest-unstable",
        tls_mode="mkcert",
        studio_enabled=True,
        stt_enabled=True,
    ),
    "stt-only": ProfileConfig(
        name="stt-only",
        domain="localhost",
        image_tag="latest-unstable",
        tls_mode="mkcert",
        studio_enabled=False,
        stt_enabled=True,
    ),
}


def get_preset(name: str) -> ProfileConfig | None:
    """Get a preset configuration by name."""
    return PRESETS.get(name)
