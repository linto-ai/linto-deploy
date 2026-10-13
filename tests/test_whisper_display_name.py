"""Name of the Whisper service shown in Studio."""

import json

from linto.backends.k3s import generate_stt_values
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


def test_default_name():
    values = generate_stt_values(profile())
    assert json.loads(values["whisper"]["env"]["GATEWAY_DESCRIPTION"]) == {
        "en": "Whisper Large V3",
        "fr": "Whisper Large V3",
    }


def test_profile_name():
    name = {"fr": "Transcription LinTO", "en": "LinTO Transcription"}
    values = generate_stt_values(profile(whisper_display_name=name))
    assert json.loads(values["whisper"]["env"]["GATEWAY_DESCRIPTION"]) == name
