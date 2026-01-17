"""Tests for backend validation and unsupported backend rejection."""

import json

from linto.cli import app


class TestBackendValidation:
    """Test that unsupported backends are properly rejected."""

    def test_compose_backend_rejected_on_render(self, cli_runner, tmp_path, sample_compose_profile, monkeypatch):
        """Test that compose backend is rejected when rendering."""
        profiles_dir = tmp_path / ".linto" / "profiles"
        profiles_dir.mkdir(parents=True)
        profile_path = profiles_dir / f"{sample_compose_profile['name']}.json"
        profile_path.write_text(json.dumps(sample_compose_profile))

        monkeypatch.chdir(tmp_path)
        result = cli_runner.invoke(app, ["render", sample_compose_profile["name"]])

        assert result.exit_code == 1
        assert "Backend 'compose' is not yet supported" in result.output
        assert "only 'k3s' backend is available" in result.output

    def test_compose_backend_rejected_on_deploy(self, cli_runner, tmp_path, sample_compose_profile, monkeypatch):
        """Test that compose backend is rejected when deploying."""
        profiles_dir = tmp_path / ".linto" / "profiles"
        profiles_dir.mkdir(parents=True)
        profile_path = profiles_dir / f"{sample_compose_profile['name']}.json"
        profile_path.write_text(json.dumps(sample_compose_profile))

        monkeypatch.chdir(tmp_path)
        result = cli_runner.invoke(app, ["deploy", sample_compose_profile["name"]])

        assert result.exit_code == 1
        assert "Backend 'compose' is not yet supported" in result.output

    def test_compose_backend_rejected_on_status(self, cli_runner, tmp_path, sample_compose_profile, monkeypatch):
        """Test that compose backend is rejected on status check."""
        profiles_dir = tmp_path / ".linto" / "profiles"
        profiles_dir.mkdir(parents=True)
        profile_path = profiles_dir / f"{sample_compose_profile['name']}.json"
        profile_path.write_text(json.dumps(sample_compose_profile))

        monkeypatch.chdir(tmp_path)
        result = cli_runner.invoke(app, ["status", sample_compose_profile["name"]])

        assert result.exit_code == 1
        assert "Backend 'compose' is not yet supported" in result.output

    def test_swarm_backend_rejected_on_deploy(self, cli_runner, tmp_path, sample_swarm_profile, monkeypatch):
        """Test that swarm backend is rejected when deploying."""
        profiles_dir = tmp_path / ".linto" / "profiles"
        profiles_dir.mkdir(parents=True)
        profile_path = profiles_dir / f"{sample_swarm_profile['name']}.json"
        profile_path.write_text(json.dumps(sample_swarm_profile))

        monkeypatch.chdir(tmp_path)
        result = cli_runner.invoke(app, ["deploy", sample_swarm_profile["name"]])

        assert result.exit_code == 1
        assert "Backend 'swarm' is not yet supported" in result.output
        assert "only 'k3s' backend is available" in result.output

    def test_swarm_backend_rejected_on_render(self, cli_runner, tmp_path, sample_swarm_profile, monkeypatch):
        """Test that swarm backend is rejected when rendering."""
        profiles_dir = tmp_path / ".linto" / "profiles"
        profiles_dir.mkdir(parents=True)
        profile_path = profiles_dir / f"{sample_swarm_profile['name']}.json"
        profile_path.write_text(json.dumps(sample_swarm_profile))

        monkeypatch.chdir(tmp_path)
        result = cli_runner.invoke(app, ["render", sample_swarm_profile["name"]])

        assert result.exit_code == 1
        assert "Backend 'swarm' is not yet supported" in result.output

    def test_k3s_backend_accepted(self, cli_runner, tmp_path, sample_k3s_profile, monkeypatch):
        """Test that k3s backend is accepted."""
        profiles_dir = tmp_path / ".linto" / "profiles"
        profiles_dir.mkdir(parents=True)
        profile_path = profiles_dir / f"{sample_k3s_profile['name']}.json"
        profile_path.write_text(json.dumps(sample_k3s_profile))

        monkeypatch.chdir(tmp_path)
        result = cli_runner.invoke(app, ["show", sample_k3s_profile["name"]])

        assert result.exit_code == 0
        assert "Backend 'k3s' is not yet supported" not in result.output


class TestBackendErrorMessageFormat:
    """Test that backend error messages have correct format."""

    def test_error_message_mentions_compose_and_swarm_future(
        self, cli_runner, tmp_path, sample_compose_profile, monkeypatch
    ):
        """Test error message mentions future support for compose/swarm."""
        profiles_dir = tmp_path / ".linto" / "profiles"
        profiles_dir.mkdir(parents=True)
        profile_path = profiles_dir / f"{sample_compose_profile['name']}.json"
        profile_path.write_text(json.dumps(sample_compose_profile))

        monkeypatch.chdir(tmp_path)
        result = cli_runner.invoke(app, ["render", sample_compose_profile["name"]])

        assert "Docker Compose and Swarm support is planned for a future release" in result.output
