#!/usr/bin/env python3
"""Create a stable platform release from the RC (Release Candidate).

This script:
1. Reads the current rc.yaml (with validated versions, commits, and digests)
2. Creates a new stable versions file (e.g., platform.2026.01.yaml)
3. Creates release notes with full traceability

Usage:
    python create-release.py platform.2026.01
    python create-release.py platform.2026.01 --dry-run
"""

import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml


def create_release(version: str, dry_run: bool = False) -> None:
    """Create a stable platform release from the RC.

    Args:
        version: Platform version (e.g., 'platform.2026.01')
        dry_run: If True, only print what would be done
    """
    script_dir = Path(__file__).parent
    base_dir = script_dir.parent
    versions_dir = base_dir / "versions"

    # Source is rc.yaml (the validated Release Candidate)
    source_file = versions_dir / "rc.yaml"

    if not source_file.exists():
        print(f"Error: {source_file} not found", file=sys.stderr)
        print("Run 'Build RC Version' workflow first to generate rc.yaml", file=sys.stderr)
        sys.exit(1)

    # Load RC versions
    with open(source_file) as f:
        versions = yaml.safe_load(f)

    print(f"Creating release: {version}")
    print(f"Source: {source_file}")
    print(f"Dry run: {dry_run}")
    print()

    # Get RC version info
    rc_version = versions.get("platform_version", "unknown")
    print(f"RC Version: {rc_version}")
    print(f"Release Version: {version}")
    print()

    # Update platform version
    versions["platform_version"] = version

    # List all services
    print("Services in this release:")
    print("-" * 70)

    for service, config in versions.get("linto", {}).items():
        tag = config.get("tag", "latest")
        commit = config.get("commit", "-")[:7] if config.get("commit") else "-"
        digest = config.get("digest", "-")[:19] + "..." if config.get("digest") else "-"
        print(f"  {service}: {tag} (commit: {commit}, digest: {digest})")

    print()
    print("Databases:")
    print("-" * 70)

    for db, config in versions.get("databases", {}).items():
        tag = config.get("tag", "latest")
        print(f"  {db}: {tag}")

    print()

    if dry_run:
        print("[DRY RUN] No changes made")
        return

    # Update metadata
    now = datetime.now(timezone.utc)
    versions["_release_date"] = now.isoformat()
    versions["_release_version"] = version
    versions["_source_rc"] = rc_version

    # Create release versions file
    release_file = versions_dir / f"{version}.yaml"
    with open(release_file, "w") as f:
        f.write("# LinTO Platform - Stable Release\n")
        f.write("#\n")
        f.write(f"# Release: {version}\n")
        f.write(f"# Date: {now.strftime('%Y-%m-%d %H:%M:%S UTC')}\n")
        f.write(f"# Source RC: {rc_version}\n")
        f.write("#\n")
        f.write("# This is a STABLE RELEASE with full version traceability.\n")
        f.write("# Each service includes: tag, digest (sha256), and commit (when available).\n")
        f.write("#\n")
        f.write("# To use this release:\n")
        f.write(f"#   linto profile edit <profile> --versions-file versions/{version}.yaml\n")
        f.write("#   linto deploy <profile>\n\n")

        # Remove internal metadata before dumping
        versions_to_write = {k: v for k, v in versions.items() if not k.startswith("_")}
        yaml.dump(versions_to_write, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    print(f"Created: {release_file}")

    # Create release notes
    docs_dir = base_dir / "docs" / "releases"
    docs_dir.mkdir(parents=True, exist_ok=True)
    release_notes = docs_dir / f"{version}.md"

    with open(release_notes, "w") as f:
        f.write(f"# LinTO Platform {version}\n\n")
        f.write(f"**Release date:** {now.strftime('%Y-%m-%d')}\n\n")
        f.write(f"**Source RC:** {rc_version}\n\n")
        f.write("## LinTO Services\n\n")
        f.write("| Service | Tag | Commit | Digest |\n")
        f.write("|---------|-----|--------|--------|\n")

        for service, config in versions.get("linto", {}).items():
            tag = config.get("tag", "latest")
            commit = config.get("commit", "-")
            digest = config.get("digest", "-")

            # Format commit as link if available
            repo = config.get("repo", "")
            if commit != "-" and repo:
                commit_short = commit[:7]
                commit_link = f"[{commit_short}]({repo}/commit/{commit})"
            else:
                commit_link = "-"

            # Shorten digest for display
            digest_short = digest[:19] + "..." if digest != "-" else "-"

            f.write(f"| {service} | `{tag}` | {commit_link} | `{digest_short}` |\n")

        f.write("\n## Databases\n\n")
        f.write("| Database | Image | Tag |\n")
        f.write("|----------|-------|-----|\n")

        for db, config in versions.get("databases", {}).items():
            tag = config.get("tag", "latest")
            image = config.get("image", db)
            f.write(f"| {db} | `{image}` | `{tag}` |\n")

        f.write("\n## Installation\n\n")
        f.write("```bash\n")
        f.write("# Update to this release\n")
        f.write(f"git fetch && git checkout {version}\n")
        f.write("\n")
        f.write("# Or use the versions file directly\n")
        f.write(f"linto profile edit <profile> --versions-file versions/{version}.yaml\n")
        f.write("linto deploy <profile>\n")
        f.write("```\n")

    print(f"Created: {release_notes}")
    print()
    print(f"Release {version} created successfully!")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Create a stable platform release from the RC",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python create-release.py platform.2026.01
    python create-release.py platform.2026.01 --dry-run
        """,
    )
    parser.add_argument("version", help="Platform version (e.g., platform.2026.01)")
    parser.add_argument("--dry-run", action="store_true", help="Only print what would be done")

    args = parser.parse_args()

    # Validate version format
    if not args.version.startswith("platform."):
        print("Warning: Version should start with 'platform.' (e.g., platform.2026.01)", file=sys.stderr)

    create_release(args.version, args.dry_run)


if __name__ == "__main__":
    main()
