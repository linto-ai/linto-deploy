"""Wizard flow logic."""

from rich.console import Console
from rich.prompt import Confirm

from linto.backends import get_backend
from linto.model.profile import (
    GPUMode,
    ProfileConfig,
    StreamingSTTVariant,
    TLSMode,
)
from linto.model.validation import save_profile
from linto.utils.secrets import generate_secrets
from linto.wizard.prompts import (
    prompt_acme_email,
    prompt_action,
    prompt_admin_credentials,
    prompt_backend,
    prompt_custom_certs,
    prompt_domain,
    prompt_gpu_count,
    prompt_gpu_mode,
    prompt_image_channel,
    prompt_k3s_database_node_role,
    prompt_k3s_host_paths,
    prompt_k3s_install_cert_manager,
    prompt_k3s_namespace,
    prompt_k3s_storage_class,
    prompt_kubeconfig_source,
    prompt_kyutai_architecture,
    prompt_live_session,
    prompt_llm,
    prompt_monitoring,
    prompt_profile_name,
    prompt_services,
    prompt_session_transcriber_replicas,
    prompt_smtp,
    prompt_sso,
    prompt_streaming_stt_variants,
    prompt_tls_mode,
    prompt_vllm,
    show_summary,
)

console = Console()


def run_wizard() -> None:
    """Run the interactive deployment wizard."""
    console.print("\n[bold blue]LinTO Deployment Wizard[/bold blue]")
    console.print("[dim]Configure your LinTO deployment interactively[/dim]\n")

    # Step 1: Profile name
    profile_name = prompt_profile_name()

    # Step 2: Kubeconfig source
    kubeconfig_source, kubeconfig_data = prompt_kubeconfig_source()

    # Step 3: Domain
    domain = prompt_domain()

    # Step 4: Deployment mode
    backend = prompt_backend()

    # Step 3b: K3S-specific settings
    k3s_namespace = prompt_k3s_namespace()
    k3s_database_host_path, k3s_files_host_path = prompt_k3s_host_paths()
    using_host_paths = bool(k3s_database_host_path or k3s_files_host_path)
    k3s_storage_class = prompt_k3s_storage_class(using_host_paths=using_host_paths)
    k3s_database_node_role = prompt_k3s_database_node_role()

    # Step 4: Service selection
    studio_enabled, stt_enabled = prompt_services()

    # Step 5: Live Session
    live_session_enabled = prompt_live_session()

    # Step 6: Streaming STT variants (if Live Session enabled)
    streaming_stt_variants: list[StreamingSTTVariant] = []
    kyutai_gpu_architecture = None
    session_transcriber_replicas = 2

    if live_session_enabled:
        streaming_stt_variants = prompt_streaming_stt_variants()

        # If Kyutai selected, ask for GPU architecture
        if StreamingSTTVariant.KYUTAI in streaming_stt_variants:
            kyutai_gpu_architecture = prompt_kyutai_architecture()

        # Ask for transcriber replicas
        session_transcriber_replicas = prompt_session_transcriber_replicas()

    # Step 7: LLM
    llm_enabled = prompt_llm()

    # Step 8: vLLM option (if LLM enabled)
    vllm_enabled = False

    if llm_enabled:
        vllm_enabled = prompt_vllm()

    # Step 9: GPU configuration (only if STT, Live, or LLM enabled)
    gpu_mode = GPUMode.NONE
    gpu_count = 1

    if stt_enabled or live_session_enabled or llm_enabled:
        gpu_mode = prompt_gpu_mode()
        if gpu_mode != GPUMode.NONE:
            gpu_count = prompt_gpu_count()

    # Step 10: TLS mode
    tls_mode = prompt_tls_mode()

    # Step 11: ACME email (if ACME)
    acme_email = None
    k3s_install_cert_manager = False
    if tls_mode == TLSMode.ACME:
        acme_email = prompt_acme_email()
        k3s_install_cert_manager = prompt_k3s_install_cert_manager(tls_mode)

    # Step 12: Custom certs (if custom)
    custom_cert_path = None
    custom_key_path = None
    if tls_mode == TLSMode.CUSTOM:
        custom_cert_path, custom_key_path = prompt_custom_certs()

    # Step 13: Image channel
    image_tag = prompt_image_channel()

    # Step 14: Admin credentials
    admin_email, admin_password = prompt_admin_credentials()

    # Step 15: SMTP Configuration
    smtp_config = prompt_smtp()

    # Step 16: SSO Configuration
    sso_config = prompt_sso()

    # Step 17: Monitoring
    monitoring_enabled = prompt_monitoring()

    # Create profile
    profile = ProfileConfig(
        name=profile_name,
        domain=domain,
        kubeconfig=kubeconfig_data,
        image_tag=image_tag,
        tls_mode=tls_mode,
        backend=backend,
        # K3S settings
        k3s_namespace=k3s_namespace,
        k3s_storage_class=k3s_storage_class,
        k3s_database_host_path=k3s_database_host_path,
        k3s_files_host_path=k3s_files_host_path,
        k3s_database_node_role=k3s_database_node_role,
        k3s_install_cert_manager=k3s_install_cert_manager,
        # GPU settings
        gpu_mode=gpu_mode,
        gpu_count=gpu_count,
        # Monitoring
        monitoring_enabled=monitoring_enabled,
        # Service flags
        studio_enabled=studio_enabled,
        stt_enabled=stt_enabled,
        live_session_enabled=live_session_enabled,
        streaming_stt_variants=streaming_stt_variants,
        kyutai_gpu_architecture=kyutai_gpu_architecture,
        session_transcriber_replicas=session_transcriber_replicas,
        llm_enabled=llm_enabled,
        vllm_enabled=vllm_enabled,
        acme_email=acme_email,
        custom_cert_path=custom_cert_path,
        custom_key_path=custom_key_path,
        super_admin_email=admin_email,
        super_admin_password=admin_password,
        # SMTP settings
        smtp_enabled=smtp_config.get("enabled", False),
        smtp_host=smtp_config.get("host"),
        smtp_port=smtp_config.get("port", 465),
        smtp_secure=smtp_config.get("secure", True),
        smtp_require_tls=smtp_config.get("require_tls", True),
        smtp_auth=smtp_config.get("auth"),
        smtp_password=smtp_config.get("password"),
        smtp_no_reply_email=smtp_config.get("no_reply_email"),
        # OIDC settings
        oidc_google_enabled=sso_config.get("google", {}).get("enabled", False),
        oidc_google_client_id=sso_config.get("google", {}).get("client_id"),
        oidc_google_client_secret=sso_config.get("google", {}).get("client_secret"),
        oidc_github_enabled=sso_config.get("github", {}).get("enabled", False),
        oidc_github_client_id=sso_config.get("github", {}).get("client_id"),
        oidc_github_client_secret=sso_config.get("github", {}).get("client_secret"),
        oidc_native_type=sso_config.get("native", {}).get("type"),
        oidc_native_client_id=sso_config.get("native", {}).get("client_id"),
        oidc_native_client_secret=sso_config.get("native", {}).get("client_secret"),
        oidc_native_url=sso_config.get("native", {}).get("url"),
        oidc_native_scope=sso_config.get("native", {}).get("scope", "openid,email,profile"),
    )

    # Generate secrets
    profile = generate_secrets(profile)

    # Show summary
    show_summary(
        profile_name=profile.name,
        domain=profile.domain,
        backend=profile.backend,
        studio_enabled=profile.studio_enabled,
        stt_enabled=profile.stt_enabled,
        live_session_enabled=profile.live_session_enabled,
        llm_enabled=profile.llm_enabled,
        tls_mode=profile.tls_mode,
        image_tag=profile.image_tag,
        admin_email=profile.super_admin_email,
        streaming_stt_variants=profile.streaming_stt_variants,
        vllm_enabled=profile.vllm_enabled,
        k3s_namespace=profile.k3s_namespace,
        k3s_storage_class=profile.k3s_storage_class,
        k3s_database_host_path=profile.k3s_database_host_path,
        k3s_files_host_path=profile.k3s_files_host_path,
        k3s_database_node_role=profile.k3s_database_node_role,
        k3s_install_cert_manager=profile.k3s_install_cert_manager,
        gpu_mode=profile.gpu_mode,
        gpu_count=profile.gpu_count,
        monitoring_enabled=profile.monitoring_enabled,
        smtp_enabled=profile.smtp_enabled,
        smtp_host=profile.smtp_host,
        oidc_google_enabled=profile.oidc_google_enabled,
        oidc_github_enabled=profile.oidc_github_enabled,
        oidc_native_type=profile.oidc_native_type,
    )

    # Confirm
    if not Confirm.ask("\n[cyan]Proceed with this configuration?[/cyan]", default=True):
        console.print("[yellow]Wizard cancelled.[/yellow]")
        return

    # Step 15: Action selection
    action = prompt_action()

    # Save profile first
    profile_path = save_profile(profile)
    console.print(f"[green]Profile saved to {profile_path}[/green]")

    # Get appropriate backend
    backend_module = get_backend(profile.backend)

    # Execute action
    if action == "plan":
        backend_module.generate(profile.name)
        console.print("\n[green]Plan generated successfully![/green]")
        console.print(f"[dim]Review files in .linto/render/k3s/{profile.name}/[/dim]")
    elif action == "apply":
        backend_module.generate(profile.name)
        backend_module.apply(profile.name)
    else:  # save
        console.print("\n[green]Profile saved. Run 'linto deploy <profile>' to deploy.[/green]")
