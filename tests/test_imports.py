"""Tests for module imports to ensure all components are accessible."""


class TestCLIImports:
    """Test CLI module imports."""

    def test_cli_app_import(self):
        """Test CLI app can be imported."""
        from linto.cli import app

        assert app is not None

    def test_cli_console_import(self):
        """Test CLI console can be imported."""
        from linto.cli import console

        assert console is not None


class TestWizardImports:
    """Test wizard module imports."""

    def test_prompt_gpu_mode_import(self):
        """Test prompt_gpu_mode can be imported."""
        from linto.wizard.prompts import prompt_gpu_mode

        assert callable(prompt_gpu_mode)

    def test_prompt_k3s_namespace_import(self):
        """Test prompt_k3s_namespace can be imported."""
        from linto.wizard.prompts import prompt_k3s_namespace

        assert callable(prompt_k3s_namespace)

    def test_wizard_flow_import(self):
        """Test wizard flow can be imported."""
        from linto.wizard.flow import run_wizard

        assert callable(run_wizard)


class TestBackendImports:
    """Test backend module imports."""

    def test_k3s_backend_module_import(self):
        """Test k3s backend module can be imported."""
        from linto.backends import k3s

        assert k3s is not None
        assert hasattr(k3s, "generate")
        assert hasattr(k3s, "apply")
        assert hasattr(k3s, "destroy")

    def test_get_charts_dir_import(self):
        """Test get_charts_dir can be imported."""
        from linto.backends.k3s import get_charts_dir

        assert callable(get_charts_dir)

    def test_get_backend_import(self):
        """Test get_backend can be imported."""
        from linto.backends import get_backend

        assert callable(get_backend)


class TestModelImports:
    """Test model module imports."""

    def test_profile_config_import(self):
        """Test ProfileConfig can be imported."""
        from linto.model.profile import ProfileConfig

        assert ProfileConfig is not None

    def test_deployment_backend_import(self):
        """Test DeploymentBackend enum can be imported."""
        from linto.model.profile import DeploymentBackend

        assert DeploymentBackend is not None
        assert DeploymentBackend.K3S is not None

    def test_validation_error_import(self):
        """Test ValidationError can be imported."""
        from linto.model.validation import ValidationError

        assert ValidationError is not None

    def test_load_profile_import(self):
        """Test load_profile can be imported."""
        from linto.model.validation import load_profile

        assert callable(load_profile)


class TestGPUImports:
    """Test GPU module imports."""

    def test_validate_gpu_capacity_import(self):
        """Test validate_gpu_capacity can be imported."""
        from linto.gpu import validate_gpu_capacity

        assert callable(validate_gpu_capacity)


class TestProfileOpsImports:
    """Test profile_ops module imports."""

    def test_list_profiles_import(self):
        """Test list_profiles can be imported."""
        from linto.profile_ops import list_profiles

        assert callable(list_profiles)

    def test_get_profile_summary_import(self):
        """Test get_profile_summary can be imported."""
        from linto.profile_ops import get_profile_summary

        assert callable(get_profile_summary)

    def test_delete_profile_import(self):
        """Test delete_profile can be imported."""
        from linto.profile_ops import delete_profile

        assert callable(delete_profile)

    def test_copy_profile_import(self):
        """Test copy_profile can be imported."""
        from linto.profile_ops import copy_profile

        assert callable(copy_profile)


class TestVersionImport:
    """Test version import."""

    def test_version_import(self):
        """Test __version__ can be imported."""
        from linto import __version__

        assert isinstance(__version__, str)
        assert len(__version__) > 0
