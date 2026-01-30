"""Rich prompts for the interactive wizard."""

from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.table import Table

from linto.model.profile import (
    DeploymentBackend,
    GPUArchitecture,
    GPUMode,
    StreamingSTTVariant,
    TLSMode,
)

console = Console()


def prompt_profile_name(default: str = "dev") -> str:
    """Prompt for profile name."""
    return Prompt.ask(
        "[cyan]Profile name[/cyan]",
        default=default,
    )


def prompt_domain(default: str = "localhost") -> str:
    """Prompt for domain."""
    return Prompt.ask(
        "[cyan]Domain[/cyan]",
        default=default,
    )


def prompt_backend() -> DeploymentBackend:
    """Return k3s backend (only supported option).

    Note: Docker Compose and Swarm support is planned for future releases.
    """
    console.print("\n[bold]Deployment backend:[/bold] Kubernetes (k3s)")
    console.print("[dim]Docker Compose and Swarm support coming in future releases.[/dim]")
    return DeploymentBackend.K3S


def prompt_k3s_namespace(default: str = "linto") -> str:
    """Prompt for Kubernetes namespace."""
    return Prompt.ask(
        "[cyan]Kubernetes namespace[/cyan]",
        default=default,
    )


def prompt_k3s_host_paths() -> tuple[str | None, str | None]:
    """Prompt for host path configuration."""
    console.print("\n[bold]Persistent Storage:[/bold]")
    console.print(
        "[dim]LinTO stores data in two locations:\n"
        "  • Databases (MongoDB, PostgreSQL, Redis) → local disk on one node\n"
        "  • Files (models, audio, exports) → shared storage (NFS recommended)[/dim]\n"
    )

    db_path = Prompt.ask(
        "[cyan]Database path on host[/cyan]",
        default="/home/ubuntu/linto/databases",
    )

    files_path = Prompt.ask(
        "[cyan]Shared files path (NFS mount)[/cyan]",
        default="/data/linto",
    )

    return (
        db_path if db_path else None,
        files_path if files_path else None,
    )


def prompt_k3s_storage_class(using_host_paths: bool = True) -> str | None:
    """Prompt for Kubernetes storage class (only if not using hostPath)."""
    if using_host_paths:
        # hostPath is used, storage class is irrelevant
        return None

    console.print("\n[bold]Kubernetes Storage Class:[/bold]")
    console.print(
        "[dim]For PVC-based storage. Common options:\n"
        "  • local-path (K3S default)\n"
        "  • longhorn, rook-ceph (distributed storage)\n"
        "  • Leave empty for cluster default[/dim]\n"
    )

    storage_class = Prompt.ask(
        "[cyan]Storage class[/cyan]",
        default="",
    )
    return storage_class if storage_class else None


def prompt_k3s_database_node_role() -> str | None:
    """Prompt for database node role (for node affinity)."""
    console.print("\n[bold]Node Affinity:[/bold]")
    console.print("[dim]Label to select nodes for database pods (leave empty for no affinity)[/dim]")

    node_role = Prompt.ask(
        "[cyan]Database node role[/cyan]",
        default="database",
    )
    return node_role if node_role else None


def prompt_k3s_install_cert_manager(tls_mode: TLSMode) -> bool:
    """Prompt for cert-manager installation."""
    if tls_mode != TLSMode.ACME:
        return False

    console.print("\n[bold]Certificate Management:[/bold]")
    console.print("[dim]cert-manager automates Let's Encrypt certificate renewal[/dim]")

    return Confirm.ask(
        "[cyan]Install cert-manager?[/cyan]",
        default=True,
    )


def prompt_gpu_mode() -> GPUMode:
    """Ask for GPU mode configuration."""
    console.print("\n[bold]GPU Configuration:[/bold]")
    console.print("  [dim]1.[/dim] none        - CPU only (no GPU)")
    console.print("  [dim]2.[/dim] exclusive   - One GPU per pod (recommended for production)")
    console.print("  [dim]3.[/dim] time-slicing - Share GPUs across pods (dev/testing)")

    choice = Prompt.ask(
        "\n[cyan]Select GPU mode[/cyan]",
        choices=["1", "2", "3"],
        default="1",
    )

    return {
        "1": GPUMode.NONE,
        "2": GPUMode.EXCLUSIVE,
        "3": GPUMode.TIME_SLICING,
    }[choice]


def prompt_gpu_count() -> int:
    """Ask for number of GPUs available."""
    count = Prompt.ask(
        "[cyan]Number of GPUs available[/cyan]",
        default="1",
    )
    try:
        return max(1, int(count))
    except ValueError:
        return 1


def prompt_services() -> tuple[bool, bool]:
    """Prompt for service selection using checkboxes.

    Returns:
        Tuple of (studio_enabled, stt_enabled)
    """
    console.print("\n[bold]Select services to deploy:[/bold]")
    console.print("  Use [cyan]y/n[/cyan] to toggle each service\n")

    studio_enabled = Confirm.ask(
        "  [cyan]LinTO Studio[/cyan] (Web interface, API, WebSocket)",
        default=True,
    )

    stt_enabled = Confirm.ask(
        "  [cyan]STT Services[/cyan] (Whisper transcription, diarization)",
        default=True,
    )

    return studio_enabled, stt_enabled


def prompt_live_session() -> bool:
    """Ask if Live Session should be enabled."""
    return Confirm.ask(
        "  [cyan]Live Session[/cyan] (Real-time streaming transcription)",
        default=False,
    )


def prompt_streaming_stt_variants() -> list[StreamingSTTVariant]:
    """Multi-select for streaming STT variants."""
    console.print("\n[bold]Select streaming STT models:[/bold]")
    console.print("  Use [cyan]y/n[/cyan] to toggle each model\n")

    variants: list[StreamingSTTVariant] = []

    if Confirm.ask("  [cyan]Whisper[/cyan] (GPU recommended, multilingual)", default=True):
        variants.append(StreamingSTTVariant.WHISPER)

    if Confirm.ask("  [cyan]Kaldi French[/cyan] (CPU only, French)", default=False):
        variants.append(StreamingSTTVariant.KALDI_FRENCH)

    if Confirm.ask("  [cyan]NeMo French[/cyan] (GPU required, French)", default=False):
        variants.append(StreamingSTTVariant.NEMO_FRENCH)

    if Confirm.ask("  [cyan]NeMo English[/cyan] (GPU required, English)", default=False):
        variants.append(StreamingSTTVariant.NEMO_ENGLISH)

    if Confirm.ask("  [cyan]Kyutai[/cyan] (GPU required, multilingual)", default=False):
        variants.append(StreamingSTTVariant.KYUTAI)

    return variants


def prompt_kyutai_architecture() -> GPUArchitecture:
    """Ask for Kyutai GPU architecture."""
    console.print("\n[bold]Select GPU architecture for Kyutai:[/bold]")
    console.print("  [dim]1.[/dim] hopper - NVIDIA H100")
    console.print("  [dim]2.[/dim] ada    - NVIDIA RTX 40xx series")
    console.print("  [dim]3.[/dim] ampere - NVIDIA RTX 30xx series, A100")

    choice = Prompt.ask(
        "\n[cyan]Select GPU architecture[/cyan]",
        choices=["1", "2", "3"],
        default="3",
    )

    return {
        "1": GPUArchitecture.HOPPER,
        "2": GPUArchitecture.ADA,
        "3": GPUArchitecture.AMPERE,
    }[choice]


def prompt_session_transcriber_replicas() -> int:
    """Ask for session transcriber replicas."""
    replicas = Prompt.ask(
        "[cyan]Number of transcriber replicas[/cyan]",
        default="2",
    )
    try:
        return max(1, int(replicas))
    except ValueError:
        return 2


def prompt_llm() -> bool:
    """Ask if LLM should be enabled."""
    return Confirm.ask(
        "  [cyan]LLM Services[/cyan] (Summarization, document processing)",
        default=False,
    )


def prompt_openai_credentials() -> tuple[str, str]:
    """Ask for OpenAI API base and token."""
    console.print("\n[bold]OpenAI API Configuration:[/bold]")

    api_base = Prompt.ask(
        "[cyan]OpenAI API Base URL[/cyan]",
        default="https://api.openai.com/v1",
    )

    api_token = Prompt.ask(
        "[cyan]OpenAI API Token[/cyan]",
        password=True,
    )

    return api_base, api_token


def prompt_vllm() -> bool:
    """Ask if local vLLM should be enabled."""
    return Confirm.ask(
        "[cyan]Enable local vLLM[/cyan] (GPU required, runs Llama 3)",
        default=False,
    )


def prompt_tls_mode() -> TLSMode:
    """Extended TLS mode selection."""
    console.print("\n[bold]TLS Mode:[/bold]")
    console.print("  [dim]1.[/dim] mkcert - Local development certificates")
    console.print("  [dim]2.[/dim] acme   - Let's Encrypt (production)")
    console.print("  [dim]3.[/dim] custom - Your own certificates")
    console.print("  [dim]4.[/dim] off    - No TLS (not recommended)")

    choice = Prompt.ask(
        "\n[cyan]Select TLS mode[/cyan]",
        choices=["1", "2", "3", "4"],
        default="1",
    )

    return {
        "1": TLSMode.MKCERT,
        "2": TLSMode.ACME,
        "3": TLSMode.CUSTOM,
        "4": TLSMode.OFF,
    }[choice]


def prompt_acme_email() -> str:
    """Ask for ACME email."""
    return Prompt.ask(
        "[cyan]Email for Let's Encrypt[/cyan]",
    )


def prompt_custom_certs() -> tuple[str, str]:
    """Ask for custom cert paths."""
    console.print("\n[bold]Custom TLS Certificates:[/bold]")

    cert_path = Prompt.ask(
        "[cyan]Path to certificate file (PEM)[/cyan]",
    )

    key_path = Prompt.ask(
        "[cyan]Path to private key file (PEM)[/cyan]",
    )

    return cert_path, key_path


def prompt_versions_file() -> tuple[str, dict[str, str]]:
    """Prompt for versions file selection.

    The versions files contain individual tags for each service.
    Both the default image_tag and service-specific tags are extracted.

    Returns:
        Tuple of (image_tag, service_tags)
        - image_tag: The platform_version (default tag)
        - service_tags: Dict of service_name -> tag for each service
    """
    from pathlib import Path

    import yaml

    # Find versions directory
    versions_dir = _find_versions_dir()

    if not versions_dir or not versions_dir.exists():
        console.print("\n[yellow]Versions directory not found, using default[/yellow]")
        return "latest-unstable", {}

    # List available version files
    version_files = sorted(versions_dir.glob("*.yaml"))

    if not version_files:
        console.print("\n[yellow]No version files found, using default[/yellow]")
        return "latest-unstable", {}

    console.print("\n[bold]Select image version:[/bold]")

    # Build options list with platform_version and full data from each file
    options = []
    file_data_list = []
    for vf in version_files:
        try:
            with open(vf) as f:
                data = yaml.safe_load(f)
                platform_version = data.get("platform_version", vf.stem)
                file_data_list.append(data)
        except Exception:
            platform_version = vf.stem
            file_data_list.append({})

        name = vf.stem
        if name == "latest":
            desc = "Release Candidate"
        elif name == "latest-unstable":
            desc = "Development"
        elif name.startswith("platform."):
            desc = "Stable Release"
        else:
            desc = ""

        options.append((platform_version, desc))

    # Display options
    for i, (tag, desc) in enumerate(options, 1):
        desc_str = f" - {desc}" if desc else ""
        console.print(f"  [dim]{i}.[/dim] {tag}{desc_str}")

    # Get choice (default to latest-unstable which should be index 2)
    choices = [str(i) for i in range(1, len(options) + 1)]

    # Find default (latest-unstable)
    default_idx = 1
    for i, (tag, _) in enumerate(options, 1):
        if tag == "latest-unstable":
            default_idx = i
            break

    choice = Prompt.ask(
        "\n[cyan]Select version[/cyan]",
        choices=choices,
        default=str(default_idx),
    )

    idx = int(choice) - 1
    selected_tag = options[idx][0]
    selected_data = file_data_list[idx]
    console.print(f"[green]Selected: {selected_tag}[/green]")

    # Extract service tags from the selected file
    service_tags = _extract_service_tags(selected_data)

    return selected_tag, service_tags


def _extract_service_tags(data: dict) -> dict[str, str]:
    """Extract service tags from versions file data.

    Args:
        data: Parsed YAML data from versions file

    Returns:
        Dict mapping service names to their tags
    """
    service_tags = {}

    # Extract LinTO service tags
    linto_services = data.get("linto", {})
    for service_name, service_config in linto_services.items():
        if isinstance(service_config, dict) and "tag" in service_config:
            service_tags[service_name] = service_config["tag"]

    # Extract database tags
    databases = data.get("databases", {})
    for db_name, db_config in databases.items():
        if isinstance(db_config, dict) and "tag" in db_config:
            service_tags[f"db-{db_name}"] = db_config["tag"]

    # Extract LLM service tags
    llm_services = data.get("llm", {})
    for llm_name, llm_config in llm_services.items():
        if isinstance(llm_config, dict) and "tag" in llm_config:
            service_tags[f"llm-{llm_name}"] = llm_config["tag"]

    return service_tags


def _find_versions_dir():
    """Find the versions directory."""
    from pathlib import Path

    # Try relative to this file (installed package)
    pkg_versions = Path(__file__).parent.parent.parent.parent / "versions"
    if pkg_versions.exists():
        return pkg_versions

    # Try current working directory
    cwd_versions = Path.cwd() / "versions"
    if cwd_versions.exists():
        return cwd_versions

    return None


def prompt_image_channel() -> str:
    """Prompt for image channel (stable/unstable).

    DEPRECATED: Use prompt_versions_file() instead.
    """
    console.print("\n[bold]Image channel:[/bold]")
    console.print("  [dim]1.[/dim] stable (latest)")
    console.print("  [dim]2.[/dim] unstable (latest-unstable)")

    choice = Prompt.ask(
        "\n[cyan]Select channel[/cyan]",
        choices=["1", "2"],
        default="2",
    )

    return "latest" if choice == "1" else "latest-unstable"


def prompt_admin_credentials(
    default_email: str = "admin@linto.local",
) -> tuple[str, str | None]:
    """Prompt for admin credentials.

    Returns:
        Tuple of (email, password or None for auto-generation)
    """
    console.print("\n[bold]Admin credentials:[/bold]")

    email = Prompt.ask(
        "[cyan]Admin email[/cyan]",
        default=default_email,
    )

    auto_password = Confirm.ask(
        "[cyan]Auto-generate password?[/cyan]",
        default=True,
    )

    password = None
    if not auto_password:
        while True:
            password = Prompt.ask(
                "[cyan]Admin password[/cyan]",
                password=True,
            )
            if len(password) >= 8:
                break
            console.print("[red]Password must be at least 8 characters[/red]")

    return email, password


def prompt_action() -> str:
    """Prompt for action after configuration.

    Returns:
        One of: "plan", "apply", "save"
    """
    console.print("\n[bold]What would you like to do?[/bold]")
    console.print("  [dim]1.[/dim] plan  - Generate files only")
    console.print("  [dim]2.[/dim] apply - Generate and deploy")
    console.print("  [dim]3.[/dim] save  - Save profile only")

    choice = Prompt.ask(
        "\n[cyan]Select action[/cyan]",
        choices=["1", "2", "3"],
        default="1",
    )

    return {"1": "plan", "2": "apply", "3": "save"}[choice]


def prompt_smtp() -> dict:
    """Prompt for SMTP configuration.

    Returns:
        Dict with SMTP config (enabled, host, port, secure, requireTls, auth, password, noReplyEmail)
    """
    console.print("\n[bold]Email Configuration (SMTP):[/bold]")
    console.print("[dim]Configure SMTP to enable email sending from the platform[/dim]\n")

    enabled = Confirm.ask(
        "[cyan]Enable email sending (SMTP)?[/cyan]",
        default=False,
    )

    if not enabled:
        return {"enabled": False}

    console.print("\n[bold]SMTP Server Settings:[/bold]")

    host = Prompt.ask(
        "[cyan]SMTP host[/cyan]",
        default="smtp.example.com",
    )

    port = Prompt.ask(
        "[cyan]SMTP port[/cyan]",
        default="465",
    )
    try:
        port = int(port)
    except ValueError:
        port = 465

    secure = Confirm.ask(
        "[cyan]Use SSL/TLS (secure)?[/cyan]",
        default=True,
    )

    require_tls = Confirm.ask(
        "[cyan]Require TLS?[/cyan]",
        default=True,
    )

    auth = Prompt.ask(
        "[cyan]SMTP auth username[/cyan]",
        default="",
    )

    password = Prompt.ask(
        "[cyan]SMTP password[/cyan]",
        password=True,
    )

    no_reply_email = Prompt.ask(
        "[cyan]No-reply email address[/cyan]",
        default=auth if auth else "noreply@example.com",
    )

    return {
        "enabled": True,
        "host": host,
        "port": port,
        "secure": secure,
        "require_tls": require_tls,
        "auth": auth,
        "password": password,
        "no_reply_email": no_reply_email,
    }


def prompt_google_oidc() -> tuple[bool, str | None, str | None]:
    """Prompt for Google OIDC configuration.

    Returns:
        Tuple of (enabled, client_id, client_secret)
    """
    enabled = Confirm.ask(
        "  [cyan]Enable Google Sign-In?[/cyan]",
        default=False,
    )

    if not enabled:
        return False, None, None

    client_id = Prompt.ask(
        "    [cyan]Google Client ID[/cyan]",
    )

    client_secret = Prompt.ask(
        "    [cyan]Google Client Secret[/cyan]",
        password=True,
    )

    return True, client_id, client_secret


def prompt_github_oidc() -> tuple[bool, str | None, str | None]:
    """Prompt for GitHub OIDC configuration.

    Returns:
        Tuple of (enabled, client_id, client_secret)
    """
    enabled = Confirm.ask(
        "  [cyan]Enable GitHub Sign-In?[/cyan]",
        default=False,
    )

    if not enabled:
        return False, None, None

    client_id = Prompt.ask(
        "    [cyan]GitHub Client ID[/cyan]",
    )

    client_secret = Prompt.ask(
        "    [cyan]GitHub Client Secret[/cyan]",
        password=True,
    )

    return True, client_id, client_secret


def prompt_native_oidc() -> tuple[str | None, str | None, str | None, str | None, str]:
    """Prompt for Native OIDC (Linagora) configuration.

    Returns:
        Tuple of (type, client_id, client_secret, url, scope)
    """
    console.print("\n  [bold]Native OIDC (Linagora):[/bold]")
    console.print("    [dim]1.[/dim] linagora - Linagora SSO")
    console.print("    [dim]2.[/dim] eu       - EU provider")
    console.print("    [dim]3.[/dim] none     - Disable Native OIDC")

    choice = Prompt.ask(
        "\n  [cyan]Select Native OIDC type[/cyan]",
        choices=["1", "2", "3"],
        default="3",
    )

    if choice == "3":
        return None, None, None, None, "openid,email,profile"

    oidc_type = "linagora" if choice == "1" else "eu"

    client_id = Prompt.ask(
        "    [cyan]OIDC Client ID[/cyan]",
    )

    client_secret = Prompt.ask(
        "    [cyan]OIDC Client Secret[/cyan]",
        password=True,
    )

    url = Prompt.ask(
        "    [cyan]OIDC Provider URL[/cyan]",
        default="https://sso.linagora.com" if oidc_type == "linagora" else "https://sso.example.eu",
    )

    scope = Prompt.ask(
        "    [cyan]OIDC Scope[/cyan]",
        default="openid,email,profile",
    )

    return oidc_type, client_id, client_secret, url, scope


def prompt_monitoring() -> bool:
    """Ask if monitoring (Prometheus + Grafana) should be enabled."""
    console.print("\n[bold]Monitoring:[/bold]")
    console.print("[dim]Deploy Prometheus + Grafana for cluster monitoring[/dim]\n")

    return Confirm.ask(
        "[cyan]Enable monitoring?[/cyan]",
        default=False,
    )


def prompt_sso() -> dict:
    """Prompt for SSO/OIDC configuration.

    Returns:
        Dict with google, github, native OIDC configs
    """
    console.print("\n[bold]Single Sign-On (SSO) Configuration:[/bold]")
    console.print("[dim]Configure authentication providers for user sign-in[/dim]\n")

    configure_sso = Confirm.ask(
        "[cyan]Configure Single Sign-On (SSO)?[/cyan]",
        default=False,
    )

    if not configure_sso:
        return {
            "google": {"enabled": False},
            "github": {"enabled": False},
            "native": {"type": None},
        }

    console.print("\n[bold]SSO Providers:[/bold]")

    # Google OIDC
    google_enabled, google_client_id, google_client_secret = prompt_google_oidc()

    # GitHub OIDC
    github_enabled, github_client_id, github_client_secret = prompt_github_oidc()

    # Native OIDC
    native_type, native_client_id, native_client_secret, native_url, native_scope = prompt_native_oidc()

    return {
        "google": {
            "enabled": google_enabled,
            "client_id": google_client_id,
            "client_secret": google_client_secret,
        },
        "github": {
            "enabled": github_enabled,
            "client_id": github_client_id,
            "client_secret": github_client_secret,
        },
        "native": {
            "type": native_type,
            "client_id": native_client_id,
            "client_secret": native_client_secret,
            "url": native_url,
            "scope": native_scope,
        },
    }


def prompt_kubeconfig_source() -> tuple[str, dict | None]:
    """Prompt for kubeconfig source.

    Returns:
        Tuple of (source_type, kubeconfig_dict)
        source_type: "file", "context", or "skip"
    """
    from linto.utils.kubeconfig import extract_current_context, get_server_url

    console.print("\n[bold]Kubeconfig source:[/bold]")
    console.print("  [dim]1.[/dim] Import from file (e.g., k3s.yaml copied from server)")
    console.print("  [dim]2.[/dim] Import from current kubectl context")
    console.print("  [dim]3.[/dim] Skip (configure later with: linto profile set-kubeconfig <profile> <file>)")

    choice = Prompt.ask(
        "\n[cyan]Select kubeconfig source[/cyan]",
        choices=["1", "2", "3"],
        default="3",
    )

    if choice == "1":
        kubeconfig = prompt_kubeconfig_file()
        if kubeconfig:
            server_url = get_server_url(kubeconfig)
            console.print(f"[green]Imported: {server_url}[/green]")
            return "file", kubeconfig
        return "skip", None

    elif choice == "2":
        kubeconfig = extract_current_context()
        if kubeconfig:
            server_url = get_server_url(kubeconfig)
            console.print(f"[green]Imported from current context: {server_url}[/green]")
            return "context", kubeconfig
        else:
            console.print("[yellow]No kubectl context found. Skipping kubeconfig import.[/yellow]")
            return "skip", None

    else:
        return "skip", None


def prompt_kubeconfig_file() -> dict | None:
    """Prompt for kubeconfig file path and load it.

    Returns:
        Kubeconfig dict or None if loading fails
    """
    from pathlib import Path

    from linto.utils.kubeconfig import load_kubeconfig

    file_path = Prompt.ask(
        "[cyan]Path to kubeconfig file[/cyan]",
        default="~/Downloads/k3s.yaml",
    )

    path = Path(file_path).expanduser()

    try:
        return load_kubeconfig(path)
    except FileNotFoundError:
        console.print(f"[red]Error: File not found: {path}[/red]")
        return None
    except ValueError as e:
        console.print(f"[red]Error: Invalid kubeconfig: {e}[/red]")
        return None


def show_summary(
    profile_name: str,
    domain: str,
    backend: DeploymentBackend,
    studio_enabled: bool,
    stt_enabled: bool,
    live_session_enabled: bool,
    llm_enabled: bool,
    tls_mode: TLSMode,
    image_tag: str,
    admin_email: str,
    streaming_stt_variants: list[StreamingSTTVariant] | None = None,
    vllm_enabled: bool = False,
    k3s_namespace: str = "linto",
    k3s_storage_class: str | None = None,
    k3s_database_host_path: str | None = None,
    k3s_files_host_path: str | None = None,
    k3s_database_node_role: str | None = None,
    k3s_install_cert_manager: bool = False,
    gpu_mode: GPUMode = GPUMode.NONE,
    gpu_count: int = 1,
    monitoring_enabled: bool = False,
    smtp_enabled: bool = False,
    smtp_host: str | None = None,
    oidc_google_enabled: bool = False,
    oidc_github_enabled: bool = False,
    oidc_native_type: str | None = None,
) -> None:
    """Display configuration summary."""
    table = Table(title="Configuration Summary")
    table.add_column("Setting", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("Profile Name", profile_name)
    table.add_row("Domain", domain)
    table.add_row("Backend", backend.value)

    # K3S-specific settings
    if backend == DeploymentBackend.K3S:
        table.add_row("Namespace", k3s_namespace)
        table.add_row("Storage Class", k3s_storage_class or "(default)")
        table.add_row("DB Host Path", k3s_database_host_path or "(none)")
        table.add_row("Files Host Path", k3s_files_host_path or "(none)")
        if k3s_database_node_role:
            table.add_row("DB Node Role", k3s_database_node_role)
        if k3s_install_cert_manager:
            table.add_row("cert-manager", "Install")

    table.add_row("TLS Mode", tls_mode.value)

    # GPU settings (if relevant)
    if gpu_mode != GPUMode.NONE:
        table.add_row("GPU Mode", gpu_mode.value)
        table.add_row("GPU Count", str(gpu_count))

    # Monitoring
    table.add_row("Monitoring", "Enabled" if monitoring_enabled else "Disabled")

    table.add_row("Studio", "Enabled" if studio_enabled else "Disabled")
    table.add_row("STT Services", "Enabled" if stt_enabled else "Disabled")
    table.add_row("Live Session", "Enabled" if live_session_enabled else "Disabled")

    if live_session_enabled and streaming_stt_variants:
        variants_str = ", ".join(v.value for v in streaming_stt_variants)
        table.add_row("Streaming STT", variants_str)

    table.add_row("LLM Services", "Enabled" if llm_enabled else "Disabled")
    if llm_enabled:
        table.add_row("Local vLLM", "Enabled" if vllm_enabled else "Disabled")

    table.add_row("Image Tag", image_tag)
    table.add_row("Admin Email", admin_email)

    # SMTP settings
    if smtp_enabled:
        table.add_row("SMTP", f"Enabled ({smtp_host})")
    else:
        table.add_row("SMTP", "Disabled")

    # SSO settings
    sso_providers = []
    if oidc_google_enabled:
        sso_providers.append("Google")
    if oidc_github_enabled:
        sso_providers.append("GitHub")
    if oidc_native_type:
        sso_providers.append(f"Native ({oidc_native_type})")
    if sso_providers:
        table.add_row("SSO", ", ".join(sso_providers))
    else:
        table.add_row("SSO", "Disabled")

    console.print()
    console.print(table)
