"""Command execution utilities with logging."""

import subprocess
from typing import Any

from rich.console import Console

console = Console(stderr=True)

# Global flag to control command display
_show_commands = True


def set_show_commands(show: bool) -> None:
    """Enable or disable command display."""
    global _show_commands
    _show_commands = show


def get_show_commands() -> bool:
    """Get current show_commands setting."""
    return _show_commands


def quote_arg(arg: str) -> str:
    """Quote argument if it contains spaces or special characters."""
    if " " in arg or any(c in arg for c in "'\"$\\"):
        # Use single quotes, escape any single quotes in the string
        return "'" + arg.replace("'", "'\\''") + "'"
    return arg


def run_cmd(
    cmd: list[str],
    *,
    check: bool = True,
    capture_output: bool = True,
    text: bool = True,
    timeout: int | None = None,
    show: bool | None = None,
    **kwargs: Any,
) -> subprocess.CompletedProcess[str]:
    """Run a command with optional display.

    Args:
        cmd: Command and arguments as list
        check: Raise on non-zero exit code
        capture_output: Capture stdout/stderr
        text: Return text instead of bytes
        timeout: Timeout in seconds
        show: Override global show_commands setting
        **kwargs: Additional subprocess.run arguments

    Returns:
        CompletedProcess result
    """
    should_show = show if show is not None else _show_commands

    if should_show:
        # Format command for display
        cmd_str = " ".join(quote_arg(arg) for arg in cmd)
        console.print(f"[dim]$ {cmd_str}[/dim]")

    return subprocess.run(
        cmd,
        check=check,
        capture_output=capture_output,
        text=text,
        timeout=timeout,
        **kwargs,
    )


