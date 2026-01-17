"""Interactive wizard for LinTO deployment configuration."""

from linto.wizard.flow import run_wizard
from linto.wizard.prompts import (
    prompt_action,
    prompt_admin_credentials,
    prompt_domain,
    prompt_image_channel,
    prompt_profile_name,
    prompt_services,
)

__all__ = [
    "run_wizard",
    "prompt_profile_name",
    "prompt_domain",
    "prompt_services",
    "prompt_image_channel",
    "prompt_admin_credentials",
    "prompt_action",
]
