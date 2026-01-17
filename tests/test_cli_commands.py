"""Tests for CLI commands and argument parsing."""

import json

from linto.cli import app


class TestBasicCLICommands:
    """Test basic CLI commands work correctly."""

    def test_help_command(self, cli_runner):
        """Test --help shows all commands."""
        result = cli_runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "wizard" in result.output
        assert "list" in result.output
        assert "show" in result.output
        assert "render" in result.output
        assert "deploy" in result.output
        assert "destroy" in result.output
        assert "status" in result.output
        assert "logs" in result.output
        assert "redeploy" in result.output
        assert "version" in result.output

    def test_version_command(self, cli_runner):
        """Test version command returns version info."""
        result = cli_runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert "linto-deploy version" in result.output

    def test_list_command_no_profiles(self, cli_runner, tmp_path, monkeypatch):
        """Test list command with no profiles."""
        monkeypatch.chdir(tmp_path)
        result = cli_runner.invoke(app, ["list"])
        assert result.exit_code == 0
        assert "No profiles found" in result.output


class TestCLIArgumentConsistency:
    """Test that CLI commands accept positional arguments consistently."""

    def test_show_accepts_positional_argument(self, cli_runner, tmp_path, sample_k3s_profile, monkeypatch):
        """Test show command accepts profile as positional arg."""
        profiles_dir = tmp_path / ".linto" / "profiles"
        profiles_dir.mkdir(parents=True)
        profile_path = profiles_dir / f"{sample_k3s_profile['name']}.json"
        profile_path.write_text(json.dumps(sample_k3s_profile))

        monkeypatch.chdir(tmp_path)
        result = cli_runner.invoke(app, ["show", sample_k3s_profile["name"]])
        assert result.exit_code == 0
        assert sample_k3s_profile["name"] in result.output
        assert sample_k3s_profile["domain"] in result.output

    def test_render_accepts_positional_argument(self, cli_runner, tmp_path, sample_k3s_profile, monkeypatch):
        """Test render command accepts profile as positional arg."""
        profiles_dir = tmp_path / ".linto" / "profiles"
        profiles_dir.mkdir(parents=True)
        profile_path = profiles_dir / f"{sample_k3s_profile['name']}.json"
        profile_path.write_text(json.dumps(sample_k3s_profile))

        monkeypatch.chdir(tmp_path)
        result = cli_runner.invoke(app, ["render", sample_k3s_profile["name"]])
        # Should not fail on argument parsing
        assert "No such option" not in result.output

    def test_destroy_help_shows_positional_argument_and_force(self, cli_runner):
        """Test destroy command help shows profile as positional arg with --force."""
        result = cli_runner.invoke(app, ["destroy", "--help"])
        assert result.exit_code == 0
        assert "PROFILE" in result.output
        assert "--force" in result.output
        # Should not show --profile as option
        assert "--profile" not in result.output


class TestStatusCommandOptions:
    """Test status command options."""

    def test_status_help_shows_options(self, cli_runner):
        """Test status --help shows required options."""
        result = cli_runner.invoke(app, ["status", "--help"])
        assert result.exit_code == 0
        assert "--compact" in result.output or "-c" in result.output
        assert "--follow" in result.output or "-f" in result.output
        assert "--interval" in result.output or "-i" in result.output

    def test_status_requires_profile_argument(self, cli_runner):
        """Test status command requires profile argument."""
        result = cli_runner.invoke(app, ["status"])
        assert result.exit_code != 0
        assert "Missing argument" in result.output or "PROFILE" in result.output


class TestErrorHandling:
    """Test error handling for various scenarios."""

    def test_nonexistent_profile_error(self, cli_runner, tmp_path, monkeypatch):
        """Test clear error for nonexistent profile."""
        monkeypatch.chdir(tmp_path)
        result = cli_runner.invoke(app, ["show", "nonexistent-profile"])
        assert result.exit_code == 1
        assert "PROFILE_NOT_FOUND" in result.output or "not found" in result.output.lower()

    def test_status_nonexistent_profile_error(self, cli_runner, tmp_path, monkeypatch):
        """Test status command error for nonexistent profile."""
        monkeypatch.chdir(tmp_path)
        result = cli_runner.invoke(app, ["status", "nonexistent-profile"])
        assert result.exit_code == 1
        assert "PROFILE_NOT_FOUND" in result.output or "not found" in result.output.lower()
