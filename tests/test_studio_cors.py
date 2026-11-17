"""Tests for studio-api CORS whitelist generation."""

from linto.backends.k3s import generate_studio_values
from linto.model.profile import DeploymentBackend, ProfileConfig, TLSMode


def _env(**kwargs) -> dict:
    profile = ProfileConfig(
        name="test",
        domain="preprod.linto.ai",
        backend=DeploymentBackend.K3S,
        tls_mode=TLSMode.ACME,
        acme_email="admin@example.com",
        **kwargs,
    )
    return generate_studio_values(profile)["studioApi"]["env"]


def test_no_extra_origins_keeps_chart_defaults():
    env = _env()
    assert "CORS_API_WHITELIST" not in env


def test_extra_origins_extend_whitelist():
    env = _env(studio_cors_extra_origins=["https://localhost", "capacitor://localhost"])
    assert env["CORS_API_WHITELIST"] == (
        "https://preprod.linto.ai,https://localhost,capacitor://localhost"
    )
