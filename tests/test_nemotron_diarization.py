"""Helm values for Nemotron diarization next to pyannote."""

from linto.backends.k3s import generate_stt_values
from linto.gpu import get_enabled_gpu_services
from linto.model.profile import ProfileConfig


def profile(**fields):
    base = {
        "name": "t",
        "domain": "t.local",
        "backend": "k3s",
        "stt_enabled": True,
        "super_admin_email": "a@t.local",
        "tls_mode": "off",
        "image_tag": "latest",
        "gpu_mode": "exclusive",
        "gpu_count": 1,
    }
    base.update(fields)
    return ProfileConfig(**base)


def test_disabled_by_default():
    values = generate_stt_values(profile(gpu_count=2))
    assert values["diarizationNemotron"]["enabled"] is False
    assert values["diarization"]["replicasPerGpu"] == [1, 1]


def test_two_gpus_nemotron_everywhere_pyannote_on_first():
    values = generate_stt_values(profile(gpu_count=2, nemotron_diarization_enabled=True))
    assert values["diarizationNemotron"]["enabled"] is True
    assert values["diarizationNemotron"]["replicasPerGpu"] == [1, 1]
    assert values["diarization"]["replicasPerGpu"] == [1, 0]
    assert values["diarizationNemotron"]["env"]["SERVICE_NAME"] == "stt-diarization-nemotron"
    assert values["diarizationNemotron"]["image"] == {"tag": "latest"}


def test_single_gpu():
    values = generate_stt_values(profile(nemotron_diarization_enabled=True))
    assert values["diarizationNemotron"]["enabled"] is True
    assert "replicasPerGpu" not in values["diarizationNemotron"]


def test_no_gpu_keeps_pyannote_only():
    values = generate_stt_values(profile(gpu_mode="none", nemotron_diarization_enabled=True))
    assert values["diarizationNemotron"]["enabled"] is False


def test_service_tag_from_manifest():
    values = generate_stt_values(profile(
        nemotron_diarization_enabled=True,
        service_tags={"linto-diarization-nemotron": "1.0.0"},
    ))
    assert values["diarizationNemotron"]["image"] == {"tag": "1.0.0"}


def test_gpu_requirement():
    names = [r.service_name for r in get_enabled_gpu_services(profile(nemotron_diarization_enabled=True))]
    assert "diarization-nemotron" in names
    names = [r.service_name for r in get_enabled_gpu_services(profile())]
    assert "diarization-nemotron" not in names
