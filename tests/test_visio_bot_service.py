"""Native Visio bot (studio-plugins-visio-botservice): profile, live values and chart."""

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from linto.backends.k3s import generate_live_values
from linto.model.profile import ProfileConfig

ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / "charts" / "linto-live"
needs_helm = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")


def profile(**fields):
    base = {
        "name": "t",
        "domain": "t.local",
        "backend": "k3s",
        "super_admin_email": "a@t.local",
        "tls_mode": "off",
        "live_session_enabled": True,
        "image_tag": "1.8.6",
    }
    base.update(fields)
    return ProfileConfig(**base)


def test_disabled_by_default():
    values = generate_live_values(profile())["visioBotService"]
    assert values["enabled"] is False
    assert values["livekitAllowedHosts"] == []


def test_enabled_values():
    values = generate_live_values(
        profile(
            visio_bot_service_enabled=True,
            visio_bot_service_replicas=2,
            visio_bot_livekit_allowed_hosts=["livekit.example.com"],
            service_tags={"studio-plugins-visio-botservice": "1.6.0"},
        )
    )["visioBotService"]
    assert values["enabled"] is True
    assert values["replicas"] == 2
    assert values["livekitAllowedHosts"] == ["livekit.example.com"]
    assert values["image"] == {"tag": "1.6.0"}


def helm_template(*sets, show_only=None):
    args = [
        "helm",
        "template",
        "t",
        str(CHART),
        "--set",
        "postgres.password=x",
        "--set",
        "sessionApi.env.SECURITY_CRYPT_KEY=y",
    ]
    for s in sets:
        args += ["--set", s]
    if show_only:
        args += ["--show-only", show_only]
    result = subprocess.run(args, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    return result.stdout


def docs_of(stdout):
    return [d for d in yaml.safe_load_all(stdout) if d]


def find(docs, kind, name):
    return next((d for d in docs if d["kind"] == kind and d["metadata"]["name"] == name), None)


def checksums(docs):
    return {
        d["metadata"]["name"]: d["spec"]["template"]["metadata"].get("annotations", {}).get("checksum/config")
        for d in docs
        if d["kind"] == "Deployment"
    }


@needs_helm
def test_chart_off_by_default():
    docs = docs_of(helm_template())
    assert not [d for d in docs if "visio" in d["metadata"]["name"]]
    scheduler = find(docs, "ConfigMap", "t-linto-live-session-scheduler-config")["data"]
    assert "BOT_PROVIDER_FALLBACK_VISIO" not in scheduler


@needs_helm
def test_chart_off_leaves_the_other_pods_alone():
    plain = checksums(docs_of(helm_template()))
    tuned = checksums(
        docs_of(
            helm_template(
                "visioBotService.env.BOT_PERSTREAM=true", "visioBotService.livekitAllowedHosts={livekit.example.com}"
            )
        )
    )
    assert plain == tuned
    assert "---\n---" not in helm_template(show_only="templates/configmap.yaml")


@needs_helm
def test_chart_on():
    docs = docs_of(
        helm_template(
            "visioBotService.enabled=true",
            "visioBotService.image.tag=1.6.0",
            "visioBotService.livekitAllowedHosts={livekit.example.com,dev-livekit.example.com}",
        )
    )
    config = find(docs, "ConfigMap", "t-linto-live-visio-bot-service-config")["data"]
    assert config == {
        "BROKER_HOST": "t-broker",
        "BROKER_PORT": "1883",
        "VISIOBOT_COMPONENTS": "BrokerClient,Healthcheck",
        "VISIOBOT_HEALTHCHECK_HTTP": "8081",
        "BOT_CAPABILITIES": "visio-native",
        "LIVEKIT_TOKEN_FROM_PAYLOAD": "true",
        "VISIOBOT_LIVEKIT_ALLOWED_HOSTS": "livekit.example.com,dev-livekit.example.com",
        "BOT_PERSTREAM": "false",
    }
    scheduler = find(docs, "ConfigMap", "t-linto-live-session-scheduler-config")["data"]
    assert scheduler["BOT_PROVIDER_FALLBACK_VISIO"] == "visio-native,visio"

    deployment = find(docs, "Deployment", "t-linto-live-visio-bot-service")
    container = deployment["spec"]["template"]["spec"]["containers"][0]
    assert container["image"] == "lintoai/studio-plugins-visio-botservice:1.6.0"
    assert container["envFrom"] == [{"configMapRef": {"name": "t-linto-live-visio-bot-service-config"}}]
    assert container["ports"] == [{"name": "health", "containerPort": 8081, "protocol": "TCP"}]
    assert container["readinessProbe"]["httpGet"] == {"path": "/healthcheck", "port": "health"}
    assert container["livenessProbe"]["httpGet"] == {"path": "/healthcheck", "port": "health"}
    assert "volumes" not in deployment["spec"]["template"]["spec"]


@needs_helm
def test_chart_env_overrides_a_default_once():
    stdout = helm_template("visioBotService.enabled=true", "visioBotService.env.BOT_PERSTREAM=true")
    config = find(docs_of(stdout), "ConfigMap", "t-linto-live-visio-bot-service-config")["data"]
    assert config["BOT_PERSTREAM"] == "true"
    assert "VISIOBOT_LIVEKIT_ALLOWED_HOSTS" not in config
    assert stdout.count("BOT_PERSTREAM:") == 1
