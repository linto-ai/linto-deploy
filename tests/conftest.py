"""Pytest configuration and shared fixtures."""

import json

import pytest
from typer.testing import CliRunner


@pytest.fixture
def cli_runner():
    """CLI runner for typer testing."""
    return CliRunner()


@pytest.fixture
def temp_profiles_dir(tmp_path):
    """Create temporary profiles directory."""
    profiles_dir = tmp_path / ".linto" / "profiles"
    profiles_dir.mkdir(parents=True)
    return profiles_dir


@pytest.fixture
def sample_k3s_profile():
    """Sample k3s profile data."""
    return {
        "name": "test-k3s",
        "domain": "test.local",
        "backend": "k3s",
        "k3s_namespace": "test-ns",
        "studio_enabled": True,
        "stt_enabled": False,
        "live_session_enabled": False,
        "llm_enabled": False,
        "super_admin_email": "test@test.local",
        "tls_mode": "off",
        "image_tag": "latest",
    }


@pytest.fixture
def sample_compose_profile():
    """Sample compose profile data (unsupported backend)."""
    return {
        "name": "test-compose",
        "domain": "test.local",
        "backend": "compose",
        "studio_enabled": True,
        "stt_enabled": False,
        "live_session_enabled": False,
        "llm_enabled": False,
        "super_admin_email": "test@test.local",
        "tls_mode": "off",
        "image_tag": "latest",
    }


@pytest.fixture
def sample_swarm_profile():
    """Sample swarm profile data (unsupported backend)."""
    return {
        "name": "test-swarm",
        "domain": "test.local",
        "backend": "swarm",
        "studio_enabled": True,
        "stt_enabled": False,
        "live_session_enabled": False,
        "llm_enabled": False,
        "super_admin_email": "test@test.local",
        "tls_mode": "off",
        "image_tag": "latest",
    }


@pytest.fixture
def create_profile(temp_profiles_dir):
    """Factory fixture to create profile files."""

    def _create(profile_data: dict):
        profile_path = temp_profiles_dir / f"{profile_data['name']}.json"
        profile_path.write_text(json.dumps(profile_data))
        return profile_path

    return _create
