"""Tests for KubeconfigContext utility."""

import os
from pathlib import Path

import pytest
import yaml

from linto.utils.kubeconfig import KubeconfigContext


@pytest.fixture
def sample_kubeconfig():
    """Sample kubeconfig data for testing."""
    return {
        "apiVersion": "v1",
        "kind": "Config",
        "clusters": [
            {
                "name": "test-cluster",
                "cluster": {
                    "server": "https://test.example.com:6443",
                    "certificate-authority-data": "dGVzdC1jYS1kYXRh",
                },
            }
        ],
        "users": [
            {
                "name": "test-user",
                "user": {
                    "client-certificate-data": "dGVzdC1jZXJ0LWRhdGE=",
                    "client-key-data": "dGVzdC1rZXktZGF0YQ==",
                },
            }
        ],
        "contexts": [
            {
                "name": "test-context",
                "context": {
                    "cluster": "test-cluster",
                    "user": "test-user",
                },
            }
        ],
        "current-context": "test-context",
    }


class TestKubeconfigContext:
    """Tests for KubeconfigContext context manager."""

    def test_kubeconfig_context_creates_temp_file(self, sample_kubeconfig):
        """Verify temp file is created with kubeconfig content."""
        with KubeconfigContext(sample_kubeconfig) as ctx:
            # Temp file should exist
            assert ctx.path is not None
            assert ctx.path.exists()

            # Temp file should contain the kubeconfig content
            with ctx.path.open() as f:
                loaded = yaml.safe_load(f)
            assert loaded["kind"] == "Config"
            assert loaded["clusters"][0]["name"] == "test-cluster"
            assert loaded["clusters"][0]["cluster"]["server"] == "https://test.example.com:6443"

    def test_kubeconfig_context_sets_env_var(self, sample_kubeconfig):
        """Verify KUBECONFIG env var is set."""
        # Ensure no KUBECONFIG is set initially
        original = os.environ.pop("KUBECONFIG", None)
        try:
            with KubeconfigContext(sample_kubeconfig) as ctx:
                # KUBECONFIG should be set to the temp file path
                assert "KUBECONFIG" in os.environ
                assert os.environ["KUBECONFIG"] == str(ctx.path)
        finally:
            if original is not None:
                os.environ["KUBECONFIG"] = original

    def test_kubeconfig_context_cleans_up(self, sample_kubeconfig):
        """Verify temp file is deleted after context exits."""
        temp_path = None
        with KubeconfigContext(sample_kubeconfig) as ctx:
            temp_path = ctx.path
            assert temp_path.exists()

        # After exiting context, temp file should be deleted
        assert temp_path is not None
        assert not temp_path.exists()

    def test_kubeconfig_context_with_none(self):
        """Verify None kubeconfig is a no-op (no file created, no env var set)."""
        # Remove KUBECONFIG if set
        original = os.environ.pop("KUBECONFIG", None)
        try:
            with KubeconfigContext(None) as ctx:
                # No temp file should be created
                assert ctx.path is None
                # KUBECONFIG should not be set by us
                assert "KUBECONFIG" not in os.environ
        finally:
            if original is not None:
                os.environ["KUBECONFIG"] = original

    def test_kubeconfig_context_restores_original_env(self, sample_kubeconfig):
        """If KUBECONFIG was already set, it should be restored."""
        original_value = "/path/to/original/kubeconfig"
        os.environ["KUBECONFIG"] = original_value

        try:
            with KubeconfigContext(sample_kubeconfig) as ctx:
                # During context, KUBECONFIG should point to temp file
                assert os.environ["KUBECONFIG"] == str(ctx.path)
                assert os.environ["KUBECONFIG"] != original_value

            # After context exits, original value should be restored
            assert os.environ["KUBECONFIG"] == original_value
        finally:
            # Clean up
            if "KUBECONFIG" in os.environ:
                del os.environ["KUBECONFIG"]

    def test_kubeconfig_context_removes_env_when_none_originally(self, sample_kubeconfig):
        """If KUBECONFIG was not set originally, it should be removed after context."""
        # Ensure KUBECONFIG is not set
        original = os.environ.pop("KUBECONFIG", None)
        try:
            with KubeconfigContext(sample_kubeconfig) as ctx:
                # KUBECONFIG should be set during context
                assert "KUBECONFIG" in os.environ

            # After context exits, KUBECONFIG should not be set
            assert "KUBECONFIG" not in os.environ
        finally:
            if original is not None:
                os.environ["KUBECONFIG"] = original

    def test_kubeconfig_context_path_property(self, sample_kubeconfig):
        """Test that path property returns the temp file path."""
        with KubeconfigContext(sample_kubeconfig) as ctx:
            path = ctx.path
            assert path is not None
            assert isinstance(path, Path)
            assert path.suffix == ".yaml"
            assert "kubeconfig-" in path.name

    def test_kubeconfig_context_none_path_property(self):
        """Test that path property returns None when kubeconfig is None."""
        with KubeconfigContext(None) as ctx:
            assert ctx.path is None
