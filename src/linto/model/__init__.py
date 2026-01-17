"""Data models for LinTO deployment."""

from linto.model.profile import ProfileConfig
from linto.model.service import (
    HealthcheckConfig,
    ServiceDefinition,
    VolumeMount,
)

__all__ = [
    "ProfileConfig",
    "ServiceDefinition",
    "HealthcheckConfig",
    "VolumeMount",
]
