"""Service catalog for LinTO deployment."""

from linto.catalog.presets import PRESETS, get_preset
from linto.catalog.services import (
    SERVICES,
    get_infra_services,
    get_stt_services,
    get_studio_services,
)

__all__ = [
    "SERVICES",
    "PRESETS",
    "get_preset",
    "get_studio_services",
    "get_stt_services",
    "get_infra_services",
]
