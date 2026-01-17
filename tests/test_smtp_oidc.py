"""Tests for SMTP and OIDC configuration (Sprint 3)."""

import pytest
from pydantic import ValidationError

from linto.backends.k3s import generate_studio_values
from linto.model.profile import (
    DeploymentBackend,
    ProfileConfig,
    TLSMode,
)


class TestSMTPValidation:
    """Test SMTP validation in ProfileConfig model."""

    def test_smtp_enabled_requires_host(self):
        """SMTP enabled without host should raise validation error."""
        with pytest.raises(ValidationError) as exc_info:
            ProfileConfig(
                name="test",
                domain="test.local",
                backend=DeploymentBackend.K3S,
                studio_enabled=True,
                smtp_enabled=True,
                smtp_auth="user@test.com",
                smtp_no_reply_email="noreply@test.com",
                # smtp_host missing
            )
        assert "SMTP host is required" in str(exc_info.value)

    def test_smtp_enabled_requires_auth(self):
        """SMTP enabled without auth should raise validation error."""
        with pytest.raises(ValidationError) as exc_info:
            ProfileConfig(
                name="test",
                domain="test.local",
                backend=DeploymentBackend.K3S,
                studio_enabled=True,
                smtp_enabled=True,
                smtp_host="smtp.test.com",
                smtp_no_reply_email="noreply@test.com",
                # smtp_auth missing
            )
        assert "SMTP auth user is required" in str(exc_info.value)

    def test_smtp_enabled_requires_no_reply_email(self):
        """SMTP enabled without no_reply_email should raise validation error."""
        with pytest.raises(ValidationError) as exc_info:
            ProfileConfig(
                name="test",
                domain="test.local",
                backend=DeploymentBackend.K3S,
                studio_enabled=True,
                smtp_enabled=True,
                smtp_host="smtp.test.com",
                smtp_auth="user@test.com",
                # smtp_no_reply_email missing
            )
        assert "No-reply email is required" in str(exc_info.value)

    def test_smtp_disabled_no_validation(self):
        """SMTP disabled should not require any SMTP fields."""
        profile = ProfileConfig(
            name="test",
            domain="test.local",
            backend=DeploymentBackend.K3S,
            studio_enabled=True,
            smtp_enabled=False,
        )
        assert profile.smtp_enabled is False
        assert profile.smtp_host is None

    def test_smtp_full_config_valid(self):
        """Full SMTP configuration should be valid."""
        profile = ProfileConfig(
            name="test",
            domain="test.local",
            backend=DeploymentBackend.K3S,
            studio_enabled=True,
            smtp_enabled=True,
            smtp_host="smtp.test.com",
            smtp_port=465,
            smtp_secure=True,
            smtp_require_tls=True,
            smtp_auth="user@test.com",
            smtp_password="password123",
            smtp_no_reply_email="noreply@test.com",
        )
        assert profile.smtp_enabled is True
        assert profile.smtp_host == "smtp.test.com"
        assert profile.smtp_port == 465
        assert profile.smtp_password == "password123"


class TestGoogleOIDCValidation:
    """Test Google OIDC validation in ProfileConfig model."""

    def test_google_oidc_enabled_requires_client_id(self):
        """Google OIDC enabled without client_id should raise validation error."""
        with pytest.raises(ValidationError) as exc_info:
            ProfileConfig(
                name="test",
                domain="test.local",
                backend=DeploymentBackend.K3S,
                studio_enabled=True,
                oidc_google_enabled=True,
                oidc_google_client_secret="secret",
                # client_id missing
            )
        assert "Google client ID is required" in str(exc_info.value)

    def test_google_oidc_enabled_requires_client_secret(self):
        """Google OIDC enabled without client_secret should raise validation error."""
        with pytest.raises(ValidationError) as exc_info:
            ProfileConfig(
                name="test",
                domain="test.local",
                backend=DeploymentBackend.K3S,
                studio_enabled=True,
                oidc_google_enabled=True,
                oidc_google_client_id="client-id",
                # client_secret missing
            )
        assert "Google client secret is required" in str(exc_info.value)

    def test_google_oidc_disabled_no_validation(self):
        """Google OIDC disabled should not require client fields."""
        profile = ProfileConfig(
            name="test",
            domain="test.local",
            backend=DeploymentBackend.K3S,
            studio_enabled=True,
            oidc_google_enabled=False,
        )
        assert profile.oidc_google_enabled is False
        assert profile.oidc_google_client_id is None

    def test_google_oidc_full_config_valid(self):
        """Full Google OIDC configuration should be valid."""
        profile = ProfileConfig(
            name="test",
            domain="test.local",
            backend=DeploymentBackend.K3S,
            studio_enabled=True,
            oidc_google_enabled=True,
            oidc_google_client_id="test-client-id",
            oidc_google_client_secret="test-secret",
        )
        assert profile.oidc_google_enabled is True
        assert profile.oidc_google_client_id == "test-client-id"


class TestGitHubOIDCValidation:
    """Test GitHub OIDC validation in ProfileConfig model."""

    def test_github_oidc_enabled_requires_client_id(self):
        """GitHub OIDC enabled without client_id should raise validation error."""
        with pytest.raises(ValidationError) as exc_info:
            ProfileConfig(
                name="test",
                domain="test.local",
                backend=DeploymentBackend.K3S,
                studio_enabled=True,
                oidc_github_enabled=True,
                oidc_github_client_secret="secret",
                # client_id missing
            )
        assert "GitHub client ID is required" in str(exc_info.value)

    def test_github_oidc_enabled_requires_client_secret(self):
        """GitHub OIDC enabled without client_secret should raise validation error."""
        with pytest.raises(ValidationError) as exc_info:
            ProfileConfig(
                name="test",
                domain="test.local",
                backend=DeploymentBackend.K3S,
                studio_enabled=True,
                oidc_github_enabled=True,
                oidc_github_client_id="client-id",
                # client_secret missing
            )
        assert "GitHub client secret is required" in str(exc_info.value)

    def test_github_oidc_disabled_no_validation(self):
        """GitHub OIDC disabled should not require client fields."""
        profile = ProfileConfig(
            name="test",
            domain="test.local",
            backend=DeploymentBackend.K3S,
            studio_enabled=True,
            oidc_github_enabled=False,
        )
        assert profile.oidc_github_enabled is False

    def test_github_oidc_full_config_valid(self):
        """Full GitHub OIDC configuration should be valid."""
        profile = ProfileConfig(
            name="test",
            domain="test.local",
            backend=DeploymentBackend.K3S,
            studio_enabled=True,
            oidc_github_enabled=True,
            oidc_github_client_id="github-client-id",
            oidc_github_client_secret="github-secret",
        )
        assert profile.oidc_github_enabled is True
        assert profile.oidc_github_client_id == "github-client-id"


class TestNativeOIDCValidation:
    """Test Native OIDC (Linagora) validation in ProfileConfig model."""

    def test_native_oidc_type_must_be_valid(self):
        """Native OIDC type must be 'linagora' or 'eu'."""
        with pytest.raises(ValidationError) as exc_info:
            ProfileConfig(
                name="test",
                domain="test.local",
                backend=DeploymentBackend.K3S,
                studio_enabled=True,
                oidc_native_type="invalid",
                oidc_native_client_id="client-id",
                oidc_native_client_secret="secret",
                oidc_native_url="https://sso.example.com",
            )
        assert "must be 'linagora' or 'eu'" in str(exc_info.value)

    def test_native_oidc_type_linagora_valid(self):
        """Native OIDC type 'linagora' should be valid."""
        profile = ProfileConfig(
            name="test",
            domain="test.local",
            backend=DeploymentBackend.K3S,
            studio_enabled=True,
            oidc_native_type="linagora",
            oidc_native_client_id="client-id",
            oidc_native_client_secret="secret",
            oidc_native_url="https://sso.linagora.com",
        )
        assert profile.oidc_native_type == "linagora"

    def test_native_oidc_type_eu_valid(self):
        """Native OIDC type 'eu' should be valid."""
        profile = ProfileConfig(
            name="test",
            domain="test.local",
            backend=DeploymentBackend.K3S,
            studio_enabled=True,
            oidc_native_type="eu",
            oidc_native_client_id="client-id",
            oidc_native_client_secret="secret",
            oidc_native_url="https://sso.eu.example.com",
        )
        assert profile.oidc_native_type == "eu"

    def test_native_oidc_requires_client_id(self):
        """Native OIDC with type set requires client_id."""
        with pytest.raises(ValidationError) as exc_info:
            ProfileConfig(
                name="test",
                domain="test.local",
                backend=DeploymentBackend.K3S,
                studio_enabled=True,
                oidc_native_type="linagora",
                oidc_native_client_secret="secret",
                oidc_native_url="https://sso.linagora.com",
                # client_id missing
            )
        assert "Native OIDC client ID is required" in str(exc_info.value)

    def test_native_oidc_requires_client_secret(self):
        """Native OIDC with type set requires client_secret."""
        with pytest.raises(ValidationError) as exc_info:
            ProfileConfig(
                name="test",
                domain="test.local",
                backend=DeploymentBackend.K3S,
                studio_enabled=True,
                oidc_native_type="linagora",
                oidc_native_client_id="client-id",
                oidc_native_url="https://sso.linagora.com",
                # client_secret missing
            )
        assert "Native OIDC client secret is required" in str(exc_info.value)

    def test_native_oidc_requires_url(self):
        """Native OIDC with type set requires URL."""
        with pytest.raises(ValidationError) as exc_info:
            ProfileConfig(
                name="test",
                domain="test.local",
                backend=DeploymentBackend.K3S,
                studio_enabled=True,
                oidc_native_type="linagora",
                oidc_native_client_id="client-id",
                oidc_native_client_secret="secret",
                # oidc_native_url missing
            )
        assert "Native OIDC URL is required" in str(exc_info.value)

    def test_native_oidc_empty_type_no_validation(self):
        """Empty native OIDC type should not require any fields."""
        profile = ProfileConfig(
            name="test",
            domain="test.local",
            backend=DeploymentBackend.K3S,
            studio_enabled=True,
            oidc_native_type=None,
        )
        assert profile.oidc_native_type is None

    def test_native_oidc_default_scope(self):
        """Native OIDC should have default scope."""
        profile = ProfileConfig(
            name="test",
            domain="test.local",
            backend=DeploymentBackend.K3S,
            studio_enabled=True,
            oidc_native_type="linagora",
            oidc_native_client_id="client-id",
            oidc_native_client_secret="secret",
            oidc_native_url="https://sso.linagora.com",
        )
        assert profile.oidc_native_scope == "openid,email,profile"


class TestHelmValuesGeneration:
    """Test Helm values generation for SMTP and OIDC."""

    @pytest.fixture
    def base_profile(self):
        """Base profile for testing."""
        return ProfileConfig(
            name="test",
            domain="test.local",
            backend=DeploymentBackend.K3S,
            studio_enabled=True,
            stt_enabled=False,
            live_session_enabled=False,
            llm_enabled=False,
            super_admin_email="admin@test.local",
            tls_mode=TLSMode.MKCERT,
        )

    def test_generate_studio_values_with_smtp(self):
        """SMTP enabled should include SMTP env vars in values."""
        profile = ProfileConfig(
            name="test",
            domain="test.local",
            backend=DeploymentBackend.K3S,
            studio_enabled=True,
            tls_mode=TLSMode.MKCERT,
            smtp_enabled=True,
            smtp_host="smtp.test.com",
            smtp_port=465,
            smtp_secure=True,
            smtp_require_tls=True,
            smtp_auth="user@test.com",
            smtp_password="password123",
            smtp_no_reply_email="noreply@test.com",
        )
        values = generate_studio_values(profile)

        assert values["studioApi"]["env"]["SMTP_HOST"] == "smtp.test.com"
        assert values["studioApi"]["env"]["SMTP_PORT"] == "465"
        assert values["studioApi"]["env"]["SMTP_SECURE"] == "true"
        assert values["studioApi"]["env"]["SMTP_REQUIRE_TLS"] == "true"
        assert values["studioApi"]["env"]["SMTP_AUTH"] == "user@test.com"
        assert values["studioApi"]["env"]["NO_REPLY_EMAIL"] == "noreply@test.com"
        assert values["studioApi"]["secrets"]["SMTP_PSWD"] == "password123"

    def test_generate_studio_values_without_smtp(self, base_profile):
        """SMTP disabled should not include SMTP env vars."""
        values = generate_studio_values(base_profile)

        assert "SMTP_HOST" not in values["studioApi"]["env"]
        assert "SMTP_PORT" not in values["studioApi"]["env"]
        # Secrets dict should exist but not have SMTP_PSWD
        assert "SMTP_PSWD" not in values["studioApi"].get("secrets", {})

    def test_generate_studio_values_with_google_oidc(self):
        """Google OIDC enabled should include Google env vars."""
        profile = ProfileConfig(
            name="test",
            domain="test.local",
            backend=DeploymentBackend.K3S,
            studio_enabled=True,
            tls_mode=TLSMode.MKCERT,
            oidc_google_enabled=True,
            oidc_google_client_id="test-client-id",
            oidc_google_client_secret="test-secret",
        )
        values = generate_studio_values(profile)

        assert values["studioApi"]["env"]["OIDC_GOOGLE_ENABLED"] == "true"
        assert values["studioApi"]["env"]["GOOGLE_CLIENT_ID"] == "test-client-id"
        assert values["studioApi"]["env"]["GOOGLE_OIDC_CALLBACK_URI"] == "https://test.local/cm-api/auth/oidc/google/cb"
        assert values["studioApi"]["secrets"]["GOOGLE_CLIENT_SECRET"] == "test-secret"

    def test_generate_studio_values_with_github_oidc(self):
        """GitHub OIDC enabled should include GitHub env vars."""
        profile = ProfileConfig(
            name="test",
            domain="test.local",
            backend=DeploymentBackend.K3S,
            studio_enabled=True,
            tls_mode=TLSMode.MKCERT,
            oidc_github_enabled=True,
            oidc_github_client_id="github-client-id",
            oidc_github_client_secret="github-secret",
        )
        values = generate_studio_values(profile)

        assert values["studioApi"]["env"]["OIDC_GITHUB_ENABLED"] == "true"
        assert values["studioApi"]["env"]["GITHUB_CLIENT_ID"] == "github-client-id"
        assert values["studioApi"]["env"]["GITHUB_OIDC_CALLBACK_URI"] == "https://test.local/cm-api/auth/oidc/github/cb"
        assert values["studioApi"]["secrets"]["GITHUB_CLIENT_SECRET"] == "github-secret"

    def test_generate_studio_values_with_native_oidc(self):
        """Native OIDC enabled should include native OIDC env vars."""
        profile = ProfileConfig(
            name="test",
            domain="test.local",
            backend=DeploymentBackend.K3S,
            studio_enabled=True,
            tls_mode=TLSMode.MKCERT,
            oidc_native_type="linagora",
            oidc_native_client_id="native-client-id",
            oidc_native_client_secret="native-secret",
            oidc_native_url="https://sso.linagora.com",
            oidc_native_scope="openid,email,profile",
        )
        values = generate_studio_values(profile)

        assert values["studioApi"]["env"]["OIDC_TYPE"] == "linagora"
        assert values["studioApi"]["env"]["OIDC_CLIENT_ID"] == "native-client-id"
        assert values["studioApi"]["env"]["OIDC_CALLBACK_URI"] == "https://test.local/cm-api/auth/oidc/cb"
        assert values["studioApi"]["env"]["OIDC_URL"] == "https://sso.linagora.com"
        assert values["studioApi"]["env"]["OIDC_SCOPE"] == "openid,email,profile"
        assert values["studioApi"]["secrets"]["OIDC_CLIENT_SECRET"] == "native-secret"

    def test_callback_uri_uses_http_when_tls_off(self):
        """Callback URIs should use http:// when TLS is off."""
        profile = ProfileConfig(
            name="test",
            domain="test.local",
            backend=DeploymentBackend.K3S,
            studio_enabled=True,
            tls_mode=TLSMode.OFF,
            oidc_google_enabled=True,
            oidc_google_client_id="test-client-id",
            oidc_google_client_secret="test-secret",
        )
        values = generate_studio_values(profile)

        assert values["studioApi"]["env"]["GOOGLE_OIDC_CALLBACK_URI"] == "http://test.local/cm-api/auth/oidc/google/cb"

    def test_callback_uri_uses_https_when_tls_mkcert(self):
        """Callback URIs should use https:// when TLS is mkcert."""
        profile = ProfileConfig(
            name="test",
            domain="test.local",
            backend=DeploymentBackend.K3S,
            studio_enabled=True,
            tls_mode=TLSMode.MKCERT,
            oidc_github_enabled=True,
            oidc_github_client_id="github-client-id",
            oidc_github_client_secret="github-secret",
        )
        values = generate_studio_values(profile)

        assert values["studioApi"]["env"]["GITHUB_OIDC_CALLBACK_URI"] == "https://test.local/cm-api/auth/oidc/github/cb"

    def test_callback_uri_uses_https_when_tls_acme(self):
        """Callback URIs should use https:// when TLS is acme."""
        profile = ProfileConfig(
            name="test",
            domain="test.local",
            backend=DeploymentBackend.K3S,
            studio_enabled=True,
            tls_mode=TLSMode.ACME,
            acme_email="admin@test.local",
            oidc_native_type="linagora",
            oidc_native_client_id="client-id",
            oidc_native_client_secret="secret",
            oidc_native_url="https://sso.linagora.com",
        )
        values = generate_studio_values(profile)

        assert values["studioApi"]["env"]["OIDC_CALLBACK_URI"] == "https://test.local/cm-api/auth/oidc/cb"


class TestSecretsNotInEnvSection:
    """Test that secrets are in 'secrets' section, not 'env' section."""

    def test_secrets_not_in_env_section(self):
        """Secrets should be in 'secrets' section, not 'env' section."""
        profile = ProfileConfig(
            name="test",
            domain="test.local",
            backend=DeploymentBackend.K3S,
            studio_enabled=True,
            tls_mode=TLSMode.MKCERT,
            smtp_enabled=True,
            smtp_host="smtp.test.com",
            smtp_auth="user@test.com",
            smtp_password="smtp-password",
            smtp_no_reply_email="noreply@test.com",
            oidc_google_enabled=True,
            oidc_google_client_id="google-id",
            oidc_google_client_secret="google-secret",
            oidc_github_enabled=True,
            oidc_github_client_id="github-id",
            oidc_github_client_secret="github-secret",
            oidc_native_type="linagora",
            oidc_native_client_id="native-id",
            oidc_native_client_secret="native-secret",
            oidc_native_url="https://sso.linagora.com",
        )
        values = generate_studio_values(profile)

        # These should NOT be in env
        assert "SMTP_PSWD" not in values["studioApi"]["env"]
        assert "GOOGLE_CLIENT_SECRET" not in values["studioApi"]["env"]
        assert "GITHUB_CLIENT_SECRET" not in values["studioApi"]["env"]
        assert "OIDC_CLIENT_SECRET" not in values["studioApi"]["env"]

        # These SHOULD be in secrets
        assert values["studioApi"]["secrets"]["SMTP_PSWD"] == "smtp-password"
        assert values["studioApi"]["secrets"]["GOOGLE_CLIENT_SECRET"] == "google-secret"
        assert values["studioApi"]["secrets"]["GITHUB_CLIENT_SECRET"] == "github-secret"
        assert values["studioApi"]["secrets"]["OIDC_CLIENT_SECRET"] == "native-secret"


class TestOIDCCallbackURIAutoGeneration:
    """Test callback URI auto-generation from domain."""

    def test_google_callback_uri_format(self):
        """Google callback URI should match expected format."""
        profile = ProfileConfig(
            name="test",
            domain="example.com",
            backend=DeploymentBackend.K3S,
            studio_enabled=True,
            tls_mode=TLSMode.MKCERT,
            oidc_google_enabled=True,
            oidc_google_client_id="client-id",
            oidc_google_client_secret="secret",
        )
        values = generate_studio_values(profile)

        assert (
            values["studioApi"]["env"]["GOOGLE_OIDC_CALLBACK_URI"] == "https://example.com/cm-api/auth/oidc/google/cb"
        )

    def test_github_callback_uri_format(self):
        """GitHub callback URI should match expected format."""
        profile = ProfileConfig(
            name="test",
            domain="example.com",
            backend=DeploymentBackend.K3S,
            studio_enabled=True,
            tls_mode=TLSMode.MKCERT,
            oidc_github_enabled=True,
            oidc_github_client_id="client-id",
            oidc_github_client_secret="secret",
        )
        values = generate_studio_values(profile)

        assert (
            values["studioApi"]["env"]["GITHUB_OIDC_CALLBACK_URI"] == "https://example.com/cm-api/auth/oidc/github/cb"
        )

    def test_native_callback_uri_format(self):
        """Native callback URI should match expected format."""
        profile = ProfileConfig(
            name="test",
            domain="example.com",
            backend=DeploymentBackend.K3S,
            studio_enabled=True,
            tls_mode=TLSMode.MKCERT,
            oidc_native_type="linagora",
            oidc_native_client_id="client-id",
            oidc_native_client_secret="secret",
            oidc_native_url="https://sso.linagora.com",
        )
        values = generate_studio_values(profile)

        assert values["studioApi"]["env"]["OIDC_CALLBACK_URI"] == "https://example.com/cm-api/auth/oidc/cb"


class TestMultipleSSOProvidersEnabled:
    """Test that multiple SSO providers can be enabled simultaneously."""

    def test_all_sso_providers_enabled(self):
        """All SSO providers can be enabled at the same time."""
        profile = ProfileConfig(
            name="test",
            domain="test.local",
            backend=DeploymentBackend.K3S,
            studio_enabled=True,
            tls_mode=TLSMode.MKCERT,
            oidc_google_enabled=True,
            oidc_google_client_id="google-id",
            oidc_google_client_secret="google-secret",
            oidc_github_enabled=True,
            oidc_github_client_id="github-id",
            oidc_github_client_secret="github-secret",
            oidc_native_type="linagora",
            oidc_native_client_id="native-id",
            oidc_native_client_secret="native-secret",
            oidc_native_url="https://sso.linagora.com",
        )
        values = generate_studio_values(profile)

        # All three providers should be present
        assert values["studioApi"]["env"]["OIDC_GOOGLE_ENABLED"] == "true"
        assert values["studioApi"]["env"]["OIDC_GITHUB_ENABLED"] == "true"
        assert values["studioApi"]["env"]["OIDC_TYPE"] == "linagora"

        # All three secrets should be present
        assert "GOOGLE_CLIENT_SECRET" in values["studioApi"]["secrets"]
        assert "GITHUB_CLIENT_SECRET" in values["studioApi"]["secrets"]
        assert "OIDC_CLIENT_SECRET" in values["studioApi"]["secrets"]


class TestSMTPDefaults:
    """Test SMTP default values."""

    def test_smtp_default_port(self):
        """SMTP default port should be 465."""
        profile = ProfileConfig(
            name="test",
            domain="test.local",
            backend=DeploymentBackend.K3S,
            studio_enabled=True,
            smtp_enabled=True,
            smtp_host="smtp.test.com",
            smtp_auth="user@test.com",
            smtp_no_reply_email="noreply@test.com",
        )
        assert profile.smtp_port == 465

    def test_smtp_default_secure(self):
        """SMTP default secure should be True."""
        profile = ProfileConfig(
            name="test",
            domain="test.local",
            backend=DeploymentBackend.K3S,
            studio_enabled=True,
            smtp_enabled=True,
            smtp_host="smtp.test.com",
            smtp_auth="user@test.com",
            smtp_no_reply_email="noreply@test.com",
        )
        assert profile.smtp_secure is True

    def test_smtp_default_require_tls(self):
        """SMTP default require_tls should be True."""
        profile = ProfileConfig(
            name="test",
            domain="test.local",
            backend=DeploymentBackend.K3S,
            studio_enabled=True,
            smtp_enabled=True,
            smtp_host="smtp.test.com",
            smtp_auth="user@test.com",
            smtp_no_reply_email="noreply@test.com",
        )
        assert profile.smtp_require_tls is True


class TestNativeOIDCNoReplyEmail:
    """Test Native OIDC uses NO_REPLY_EMAIL."""

    def test_native_oidc_uses_smtp_no_reply_email(self):
        """Native OIDC should use smtp_no_reply_email for NO_REPLY_EMAIL."""
        profile = ProfileConfig(
            name="test",
            domain="test.local",
            backend=DeploymentBackend.K3S,
            studio_enabled=True,
            tls_mode=TLSMode.MKCERT,
            smtp_no_reply_email="noreply@test.com",
            oidc_native_type="linagora",
            oidc_native_client_id="client-id",
            oidc_native_client_secret="secret",
            oidc_native_url="https://sso.linagora.com",
        )
        values = generate_studio_values(profile)

        assert values["studioApi"]["env"]["NO_REPLY_EMAIL"] == "noreply@test.com"
