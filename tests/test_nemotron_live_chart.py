"""helm template of the linto-stt chart with and without live diarization (skipped without helm)."""

import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

CHART = Path(__file__).resolve().parents[1] / "charts" / "linto-stt"
pytestmark = pytest.mark.skipif(shutil.which("helm") is None, reason="helm not installed")


def render(*sets, check=True):
    args = ["helm", "template", "t", str(CHART), "--set", "diarizationNemotron.enabled=true"]
    for s in sets:
        args += ["--set", s]
    result = subprocess.run(args, capture_output=True, text=True)
    if check:
        assert result.returncode == 0, result.stderr
        return [d for d in yaml.safe_load_all(result.stdout) if d]
    return result


def find(docs, kind, name):
    return next((d for d in docs if d["kind"] == kind and d["metadata"]["name"] == name), None)


def nemotron_container(docs):
    dep = find(docs, "Deployment", "t-linto-stt-diarization-nemotron-gpu-0")
    return dep["spec"]["template"]["spec"]["containers"][0]


def test_off_by_default():
    docs = render()
    assert find(docs, "Service", "t-linto-stt-diarization-nemotron-live") is None
    container = nemotron_container(docs)
    assert "readinessProbe" not in container and "ports" not in container
    assert "NEMOTRON_LIVE_PORT" not in find(docs, "ConfigMap", "t-linto-stt-diarization-nemotron-config")["data"]
    assert "nemotron-live-token" not in find(docs, "Secret", "t-linto-stt-secrets")["stringData"]


def test_on():
    docs = render("diarizationNemotron.live.enabled=true", "diarizationNemotron.live.token=s3cret",
                  "diarizationNemotron.live.maxSessions=24")
    service = find(docs, "Service", "t-linto-stt-diarization-nemotron-live")
    assert service["spec"]["ports"][0] == {"port": 8080, "targetPort": "live", "protocol": "TCP", "name": "live"}
    assert service["spec"]["selector"]["app.kubernetes.io/component"] == "diarization-nemotron"
    container = nemotron_container(docs)
    assert container["ports"] == [{"name": "live", "containerPort": 8080, "protocol": "TCP"}]
    assert container["readinessProbe"]["httpGet"] == {"path": "/ready", "port": "live"}
    token = next(e for e in container["env"] if e["name"] == "NEMOTRON_LIVE_TOKEN")
    assert token["valueFrom"]["secretKeyRef"] == {"name": "t-linto-stt-secrets", "key": "nemotron-live-token"}
    config = find(docs, "ConfigMap", "t-linto-stt-diarization-nemotron-config")["data"]
    assert config["NEMOTRON_LIVE_PORT"] == "8080" and config["NEMOTRON_MAX_LIVE_SESSIONS"] == "24"
    assert find(docs, "Secret", "t-linto-stt-secrets")["stringData"]["nemotron-live-token"] == "s3cret"
    # pyannote workers are not touched
    pyannote = find(docs, "Deployment", "t-linto-stt-diarization-gpu-0")["spec"]["template"]["spec"]["containers"][0]
    assert "ports" not in pyannote and "readinessProbe" not in pyannote


def test_token_required():
    result = render("diarizationNemotron.live.enabled=true", check=False)
    assert result.returncode != 0 and "diarizationNemotron.live.token is required" in result.stderr
