"""GPU requirements and validation for services."""

from dataclasses import dataclass

from linto.model.profile import GPUMode, ProfileConfig, StreamingSTTVariant

# Services that require GPU
GPU_REQUIRED_SERVICES: dict[str, dict[str, int | bool]] = {
    "vllm-service": {"required": True, "slots": 1},
    "stt-nemo-french-streaming": {"required": True, "slots": 1},
    "stt-nemo-english-streaming": {"required": True, "slots": 1},
    "stt-kyutai-streaming": {"required": True, "slots": 1},
}

# Services where GPU is optional but recommended
GPU_OPTIONAL_SERVICES: dict[str, dict[str, int]] = {
    "stt-whisper-streaming": {"slots": 1},
    "stt-whisper-workers": {"slots": 1},
    "diarization-pyannote": {"slots": 1},
}


@dataclass
class GPURequirement:
    """GPU requirement for a service."""

    service_name: str
    slots_required: int
    optional: bool


def get_enabled_gpu_services(profile: ProfileConfig) -> list[GPURequirement]:
    """Return list of enabled services that use GPU.

    Args:
        profile: Profile configuration

    Returns:
        List of GPURequirement for enabled services
    """
    requirements: list[GPURequirement] = []

    # Check vLLM
    if profile.llm_enabled and profile.vllm_enabled:
        requirements.append(
            GPURequirement(
                service_name="vllm-service",
                slots_required=1,
                optional=False,
            )
        )

    # Check streaming STT variants
    if profile.live_session_enabled:
        for variant in profile.streaming_stt_variants:
            if variant == StreamingSTTVariant.NEMO_FRENCH:
                requirements.append(
                    GPURequirement(
                        service_name="stt-nemo-french-streaming",
                        slots_required=1,
                        optional=False,
                    )
                )
            elif variant == StreamingSTTVariant.NEMO_ENGLISH:
                requirements.append(
                    GPURequirement(
                        service_name="stt-nemo-english-streaming",
                        slots_required=1,
                        optional=False,
                    )
                )
            elif variant == StreamingSTTVariant.KYUTAI:
                requirements.append(
                    GPURequirement(
                        service_name="stt-kyutai-streaming",
                        slots_required=1,
                        optional=False,
                    )
                )
            elif variant == StreamingSTTVariant.WHISPER:
                # Whisper streaming is optional GPU
                requirements.append(
                    GPURequirement(
                        service_name="stt-whisper-streaming",
                        slots_required=1,
                        optional=True,
                    )
                )

    # Check file-based STT services (optional GPU)
    if profile.stt_enabled:
        requirements.append(
            GPURequirement(
                service_name="stt-whisper-workers",
                slots_required=1,
                optional=True,
            )
        )
        requirements.append(
            GPURequirement(
                service_name="diarization-pyannote",
                slots_required=1,
                optional=True,
            )
        )

    return requirements


def calculate_total_gpu_slots(profile: ProfileConfig) -> int:
    """Calculate total GPU slots available based on mode and count.

    Args:
        profile: Profile configuration

    Returns:
        Number of available GPU slots
    """
    if profile.gpu_mode == GPUMode.NONE:
        return 0
    elif profile.gpu_mode == GPUMode.EXCLUSIVE:
        return profile.gpu_count
    elif profile.gpu_mode == GPUMode.TIMESLICING:
        return profile.gpu_count * profile.gpu_slices_per_gpu
    else:
        raise NotImplementedError("MIG mode not supported")


def validate_gpu_capacity(profile: ProfileConfig) -> list[str]:
    """Return warning messages if GPU capacity is insufficient.

    Args:
        profile: Profile configuration

    Returns:
        List of warning messages (empty if no issues)
    """
    warnings: list[str] = []

    requirements = get_enabled_gpu_services(profile)
    if not requirements:
        return warnings

    available_slots = calculate_total_gpu_slots(profile)

    # Calculate required slots (only mandatory services)
    required_slots = sum(req.slots_required for req in requirements if not req.optional)

    # Calculate total slots including optional
    total_slots = sum(req.slots_required for req in requirements)

    if required_slots > 0 and available_slots == 0:
        service_list = ", ".join(req.service_name for req in requirements if not req.optional)
        warnings.append(f"GPU required but not configured. Services requiring GPU: {service_list}")
    elif required_slots > available_slots:
        service_breakdown = ", ".join(
            f"{req.service_name}: {req.slots_required}" for req in requirements if not req.optional
        )
        slot_info = (
            f"{profile.gpu_count} GPU x {profile.gpu_slices_per_gpu} slices"
            if profile.gpu_mode == GPUMode.TIMESLICING
            else f"{profile.gpu_count} GPU"
        )
        warnings.append(
            f"GPU Capacity Warning:\n"
            f"  Required: {required_slots} GPU slots ({service_breakdown})\n"
            f"  Available: {available_slots} slots ({slot_info})"
        )
    elif total_slots > available_slots and available_slots > 0:
        # Warn about optional services
        optional_services = [req for req in requirements if req.optional]
        if optional_services:
            service_list = ", ".join(req.service_name for req in optional_services)
            warnings.append(f"Note: Some optional GPU services may run on CPU: {service_list}")

    return warnings


def has_gpu_services(profile: ProfileConfig) -> bool:
    """Check if profile has any GPU-requiring services enabled.

    Args:
        profile: Profile configuration

    Returns:
        True if GPU services are enabled
    """
    requirements = get_enabled_gpu_services(profile)
    return any(not req.optional for req in requirements)
