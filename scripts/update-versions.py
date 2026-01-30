#!/usr/bin/env python3
"""Update versions.yaml from DockerHub or GitHub events.

This script is triggered by:
1. repository_dispatch from service repos (with service, tag, commit_sha)
2. Manual workflow_dispatch (with optional service and tag)
3. Scheduled sync (no inputs - syncs all from DockerHub)

Environment variables:
- SERVICE: Service name to update (optional)
- TAG: Tag to set (optional, defaults to 'latest')
- COMMIT_SHA: Git commit SHA (optional, for tracking)
- REPO: Source repository (optional, for tracking)
- VERSIONS_FILE: Which file to update ('versions.yaml' or 'versions-unstable.yaml')
"""

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
import yaml


def _get_github_headers() -> dict:
    """Get headers for GitHub API requests."""
    headers = {"Accept": "application/vnd.github.v3+json"}
    github_token = os.environ.get("GITHUB_TOKEN")
    if github_token:
        headers["Authorization"] = f"token {github_token}"
    return headers


def _parse_github_repo(repo_url: str) -> str | None:
    """Parse GitHub repo path from URL."""
    if not repo_url or "github.com" not in repo_url:
        return None

    parsed = urlparse(repo_url)
    path = parsed.path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    return path


def get_github_commit_for_tag(repo_url: str, tag: str) -> tuple[str | None, str | None]:
    """Get the commit SHA for a tag from GitHub."""
    path = _parse_github_repo(repo_url)
    if not path:
        return None, "no-repo"

    tags_to_try = [tag, f"v{tag}"] if not tag.startswith("v") else [tag, tag[1:]]
    headers = _get_github_headers()

    for try_tag in tags_to_try:
        url = f"https://api.github.com/repos/{path}/git/ref/tags/{try_tag}"
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                obj = data.get("object", {})
                if obj.get("type") == "commit":
                    return obj.get("sha"), None
                elif obj.get("type") == "tag":
                    tag_url = obj.get("url")
                    if tag_url:
                        tag_response = requests.get(tag_url, headers=headers, timeout=10)
                        if tag_response.status_code == 200:
                            tag_data = tag_response.json()
                            return tag_data.get("object", {}).get("sha"), None
                        elif tag_response.status_code == 403:
                            return None, "rate-limited"
            elif response.status_code == 403:
                return None, "rate-limited"
            elif response.status_code == 404:
                continue
        except requests.RequestException:
            return None, "error"

    return None, "no-tag"


def get_github_commit_by_date(repo_url: str, until_date: str) -> tuple[str | None, str | None]:
    """Get the most recent commit SHA before a given date."""
    path = _parse_github_repo(repo_url)
    if not path:
        return None, "no-repo"

    headers = _get_github_headers()
    url = f"https://api.github.com/repos/{path}/commits"
    params = {"until": until_date, "per_page": 1}

    try:
        response = requests.get(url, headers=headers, params=params, timeout=10)
        if response.status_code == 200:
            commits = response.json()
            if commits and len(commits) > 0:
                return commits[0].get("sha"), None
            return None, "no-commits"
        elif response.status_code == 403:
            return None, "rate-limited"
    except requests.RequestException:
        return None, "error"

    return None, "not-found"


def get_dockerhub_tag_info(image: str, tag: str) -> dict | None:
    """Get tag info including digest from DockerHub.

    Args:
        image: Full image name (e.g., 'lintoai/studio-api')
        tag: Tag name (e.g., 'latest')

    Returns:
        Dict with tag info or None if not found
    """
    namespace, name = image.split("/") if "/" in image else ("library", image)
    url = f"https://hub.docker.com/v2/repositories/{namespace}/{name}/tags/{tag}"

    try:
        response = requests.get(url, timeout=30)
        if response.status_code == 200:
            data = response.json()
            images = data.get("images", [])
            digest = images[0].get("digest") if images else None
            return {
                "tag": tag,
                "digest": digest,
                "last_pushed": data.get("tag_last_pushed"),
            }
    except requests.RequestException as e:
        print(f"  Warning: Could not fetch tag info for {image}:{tag}: {e}", file=sys.stderr)

    return None


def get_dockerhub_latest_tag(image: str) -> str | None:
    """Get the latest tag from DockerHub for an image.

    Args:
        image: Full image name (e.g., 'lintoai/studio-api')

    Returns:
        Latest tag or None if not found
    """
    namespace, name = image.split("/") if "/" in image else ("library", image)
    url = f"https://hub.docker.com/v2/repositories/{namespace}/{name}/tags"

    try:
        response = requests.get(url, params={"page_size": 100}, timeout=30)
        response.raise_for_status()
        data = response.json()

        tags = [t["name"] for t in data.get("results", [])]

        # Prefer 'latest' if available
        if "latest" in tags:
            return "latest"

        # Otherwise return the most recent tag
        return tags[0] if tags else None

    except requests.RequestException as e:
        print(f"Warning: Could not fetch tags for {image}: {e}", file=sys.stderr)
        return None


def update_service_version(versions: dict, service: str, tag: str, digest: str | None = None, commit: str | None = None) -> bool:
    """Update a specific service version in the versions dict.

    Args:
        versions: The versions dictionary
        service: Service name (e.g., 'studio-api')
        tag: New tag to set
        digest: Docker image digest (optional)
        commit: Git commit SHA (optional)

    Returns:
        True if updated, False if service not found
    """
    # Find service in any section
    for section in ["linto", "databases", "llm"]:
        if service in versions.get(section, {}):
            config = versions[section][service]
            old_tag = config.get("tag")
            config["tag"] = tag

            if digest:
                config["digest"] = digest
            if commit:
                config["commit"] = commit

            digest_str = f", digest: {digest[:19]}..." if digest else ""
            print(f"Updated {service}: {old_tag} -> {tag}{digest_str}")
            return True

    print(f"Warning: Service '{service}' not found in versions.yaml", file=sys.stderr)
    return False


def sync_all_from_dockerhub(versions: dict, target_tag: str = "latest") -> int:
    """Sync all service versions from DockerHub including databases and LLM.

    Args:
        versions: The versions dictionary
        target_tag: Tag to fetch for linto services (e.g., 'latest' or 'latest-unstable')

    Returns:
        Number of services updated
    """
    updated = 0

    # Sync LinTO services
    print("  LinTO services:")
    for service, config in versions.get("linto", {}).items():
        image = config.get("image")
        if not image:
            continue

        print(f"    {service}...", end=" ")

        # Get tag info including digest
        tag_info = get_dockerhub_tag_info(image, target_tag)

        if tag_info:
            config["tag"] = tag_info["tag"]
            if tag_info.get("digest"):
                config["digest"] = tag_info["digest"]

            # Try to get commit from GitHub
            repo_url = config.get("repo", "")
            commit_sha = None
            commit_source = None

            if repo_url and tag_info.get("last_pushed"):
                # Try by date first (most reliable for 'latest' tag)
                commit_sha, err = get_github_commit_by_date(repo_url, tag_info["last_pushed"])
                if commit_sha:
                    commit_source = "date"
                elif err == "rate-limited":
                    config["commit"] = "<rate-limited>"

            if commit_sha:
                config["commit"] = commit_sha

            digest_str = tag_info["digest"][:19] + "..." if tag_info.get("digest") else "-"
            commit_str = commit_sha[:7] if commit_sha else ("-" if "commit" not in config else config["commit"])
            print(f"{target_tag} (digest: {digest_str}, commit: {commit_str})")
            updated += 1
        else:
            print(f"not found, keeping {config.get('tag', 'latest')}")

    # Sync databases (use their own tags, just fetch digest)
    print("  Databases:")
    for service, config in versions.get("databases", {}).items():
        image = config.get("image")
        tag = config.get("tag", "latest")
        if not image:
            continue

        print(f"    {service}...", end=" ")

        tag_info = get_dockerhub_tag_info(image, tag)

        if tag_info and tag_info.get("digest"):
            config["digest"] = tag_info["digest"]
            digest_str = tag_info["digest"][:19] + "..."
            print(f"{tag} (digest: {digest_str})")
            updated += 1
        else:
            print(f"{tag} (digest: not found)")

    # Sync LLM services (use their own tags, just fetch digest)
    print("  LLM services:")
    for service, config in versions.get("llm", {}).items():
        image = config.get("image")
        tag = config.get("tag", "latest")
        if not image:
            continue

        print(f"    {service}...", end=" ")

        tag_info = get_dockerhub_tag_info(image, tag)

        if tag_info and tag_info.get("digest"):
            config["digest"] = tag_info["digest"]
            digest_str = tag_info["digest"][:19] + "..."
            print(f"{tag} (digest: {digest_str})")
            updated += 1
        else:
            print(f"{tag} (digest: not found)")

    return updated


def update_versions_file(versions_file: Path, service: str, tag: str, commit_sha: str, repo: str) -> None:
    """Update a single versions file.

    Args:
        versions_file: Path to the versions file
        service: Service name to update (empty for sync all)
        tag: Tag to set
        commit_sha: Git commit SHA (for tracking)
        repo: Source repository (for tracking)
    """
    if not versions_file.exists():
        print(f"Warning: {versions_file} not found, skipping", file=sys.stderr)
        return

    print(f"\nUpdating {versions_file.name}...")

    # Load versions
    with open(versions_file) as f:
        versions = yaml.safe_load(f)

    # Update based on inputs
    if service:
        # Update specific service - fetch digest for the tag
        for section in ["linto", "databases", "llm"]:
            if service in versions.get(section, {}):
                image = versions[section][service].get("image")
                if image:
                    tag_info = get_dockerhub_tag_info(image, tag)
                    digest = tag_info.get("digest") if tag_info else None
                    update_service_version(versions, service, tag, digest, commit_sha)
                break
        else:
            update_service_version(versions, service, tag, None, commit_sha)
    else:
        # Sync all from DockerHub
        updated = sync_all_from_dockerhub(versions, tag)
        print(f"Updated {updated} services in {versions_file.name}")

    # Update metadata
    versions["_updated"] = datetime.now(timezone.utc).isoformat()

    # Determine header based on file
    is_unstable = "unstable" in versions_file.name
    platform_type = "Development (latest-unstable)" if is_unstable else "Release Candidate (latest)"

    # Write back
    with open(versions_file, "w") as f:
        f.write("# LinTO Platform - Software Versions\n")
        f.write(f"# Type: {platform_type}\n")
        f.write("#\n")
        f.write("# Available version files in versions/ directory:\n")
        f.write("#   - rc.yaml             : Release Candidate (versioned tags + digest + commit)\n")
        f.write("#   - latest.yaml          : Latest stable (latest tags + digest)\n")
        f.write("#   - latest-unstable.yaml : Development (latest-unstable tags + digest)\n")
        f.write("#   - platform.YYYY.MM.yaml: Stable releases\n")
        f.write("#\n")
        f.write("# DO NOT EDIT MANUALLY - This file is auto-generated\n")
        f.write(f"# Last updated: {versions['_updated']}\n\n")

        # Remove internal metadata before dumping
        versions_to_write = {k: v for k, v in versions.items() if not k.startswith("_")}
        yaml.dump(versions_to_write, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    print(f"Saved {versions_file}")


def main():
    """Main entry point."""
    # Load environment variables
    service = os.environ.get("SERVICE", "").strip()
    tag = os.environ.get("TAG", "").strip() or "latest"
    commit_sha = os.environ.get("COMMIT_SHA", "").strip()
    repo = os.environ.get("REPO", "").strip()
    versions_file_env = os.environ.get("VERSIONS_FILE", "").strip()

    script_dir = Path(__file__).parent
    base_dir = script_dir.parent
    versions_dir = base_dir / "versions"

    # Determine which files to update
    if versions_file_env:
        # Update specific file
        versions_files = [versions_dir / versions_file_env]
    else:
        # Update both files
        versions_files = [
            versions_dir / "latest.yaml",
            versions_dir / "latest-unstable.yaml",
        ]

    print(f"Service: {service or '(all)'}")
    print(f"Tag: {tag}")
    if commit_sha:
        print(f"Commit: {commit_sha}")
    if repo:
        print(f"Repo: {repo}")

    # Update each file
    for versions_file in versions_files:
        # Adjust tag for unstable file
        file_tag = tag
        if "unstable" in versions_file.name and tag == "latest":
            file_tag = "latest-unstable"

        update_versions_file(versions_file, service, file_tag, commit_sha, repo)

    print("\nDone!")


if __name__ == "__main__":
    main()
