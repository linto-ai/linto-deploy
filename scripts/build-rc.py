#!/usr/bin/env python3
"""Build RC (Release Candidate) version file from DockerHub.

This script generates an RC version file by:
1. Querying DockerHub for the digest of each service's 'latest' tag
2. Finding the semver tag that matches the same digest
3. Querying GitHub for the commit SHA associated with that tag
4. Using version tag + commit info in rc.yaml

This ensures RC uses actual released versions with full traceability.

Environment variables:
- DRY_RUN: Set to 'true' to print without writing file
- GITHUB_TOKEN: Optional GitHub token for higher API rate limits
"""

import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests
import yaml


def _get_github_headers() -> dict:
    """Get GitHub API headers with optional auth token."""
    headers = {"Accept": "application/vnd.github.v3+json"}
    github_token = os.environ.get("GITHUB_TOKEN")
    if github_token:
        headers["Authorization"] = f"token {github_token}"
    return headers


def _parse_github_repo(repo_url: str) -> str | None:
    """Parse GitHub repo path from URL.

    Args:
        repo_url: GitHub repository URL (e.g., 'https://github.com/linto-ai/linto-studio')

    Returns:
        Repo path (e.g., 'linto-ai/linto-studio') or None
    """
    if not repo_url or "github.com" not in repo_url:
        return None

    parsed = urlparse(repo_url)
    path = parsed.path.strip("/")
    if path.endswith(".git"):
        path = path[:-4]
    return path


def get_github_commit_for_tag(repo_url: str, tag: str) -> tuple[str | None, str | None]:
    """Get the commit SHA for a tag from GitHub.

    Args:
        repo_url: GitHub repository URL (e.g., 'https://github.com/linto-ai/linto-studio')
        tag: Tag name (e.g., '1.6.0' or 'v1.6.0')

    Returns:
        Tuple of (commit_sha, error_reason) - one will be None
    """
    path = _parse_github_repo(repo_url)
    if not path:
        return None, "no-repo"

    # Try with and without 'v' prefix
    tags_to_try = [tag, f"v{tag}"] if not tag.startswith("v") else [tag, tag[1:]]
    headers = _get_github_headers()

    for try_tag in tags_to_try:
        url = f"https://api.github.com/repos/{path}/git/ref/tags/{try_tag}"
        try:
            response = requests.get(url, headers=headers, timeout=10)
            if response.status_code == 200:
                data = response.json()
                # Could be a direct commit or an annotated tag
                obj = data.get("object", {})
                if obj.get("type") == "commit":
                    return obj.get("sha"), None
                elif obj.get("type") == "tag":
                    # Need to dereference the tag to get the commit
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
                continue  # Try next tag format
        except requests.RequestException:
            return None, "error"

    return None, "no-tag"


def get_github_commit_by_date(repo_url: str, until_date: str) -> tuple[str | None, str | None]:
    """Get the most recent commit SHA before a given date.

    Args:
        repo_url: GitHub repository URL
        until_date: ISO 8601 date string (e.g., '2025-11-20T16:28:51Z')

    Returns:
        Tuple of (commit_sha, error_reason) - one will be None
    """
    path = _parse_github_repo(repo_url)
    if not path:
        return None, "no-repo"

    headers = _get_github_headers()

    # Get commits up to the given date
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


def get_github_default_branch_commit(repo_url: str) -> tuple[str | None, str | None]:
    """Get the latest commit SHA from the default branch.

    Args:
        repo_url: GitHub repository URL

    Returns:
        Tuple of (commit_sha, error_reason) - one will be None
    """
    path = _parse_github_repo(repo_url)
    if not path:
        return None, "no-repo"

    headers = _get_github_headers()

    # First get the default branch
    url = f"https://api.github.com/repos/{path}"
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code == 200:
            repo_data = response.json()
            default_branch = repo_data.get("default_branch", "main")

            # Get the latest commit on that branch
            branch_url = f"https://api.github.com/repos/{path}/branches/{default_branch}"
            branch_response = requests.get(branch_url, headers=headers, timeout=10)
            if branch_response.status_code == 200:
                branch_data = branch_response.json()
                return branch_data.get("commit", {}).get("sha"), None
            elif branch_response.status_code == 403:
                return None, "rate-limited"
        elif response.status_code == 403:
            return None, "rate-limited"
    except requests.RequestException:
        return None, "error"

    return None, "not-found"


def get_dockerhub_tag_digest(image: str, tag: str) -> str | None:
    """Get the digest for a specific tag from DockerHub.

    Args:
        image: Full image name (e.g., 'mongo' or 'lintoai/studio-api')
        tag: Tag name (e.g., 'latest' or '6.0.2')

    Returns:
        Digest string or None if not found
    """
    namespace, name = image.split("/") if "/" in image else ("library", image)
    url = f"https://hub.docker.com/v2/repositories/{namespace}/{name}/tags/{tag}"

    try:
        response = requests.get(url, timeout=30)
        if response.status_code == 200:
            data = response.json()
            images = data.get("images", [])
            if images:
                return images[0].get("digest")
    except requests.RequestException:
        pass

    return None


def get_dockerhub_tags(image: str, page_size: int = 100) -> list[dict]:
    """Get all tags from DockerHub for an image.

    Args:
        image: Full image name (e.g., 'lintoai/studio-api')
        page_size: Number of tags per page

    Returns:
        List of tag info dicts with 'name' and 'digest' keys
    """
    namespace, name = image.split("/") if "/" in image else ("library", image)
    url = f"https://hub.docker.com/v2/repositories/{namespace}/{name}/tags"

    tags = []
    try:
        response = requests.get(url, params={"page_size": page_size}, timeout=30)
        response.raise_for_status()
        data = response.json()

        for tag in data.get("results", []):
            tag_name = tag.get("name")
            # Get digest from images array (first one, usually amd64)
            images = tag.get("images", [])
            digest = images[0].get("digest") if images else None

            if tag_name and digest:
                tags.append({
                    "name": tag_name,
                    "digest": digest,
                    "last_pushed": tag.get("tag_last_pushed"),
                })

    except requests.RequestException as e:
        print(f"  Warning: Could not fetch tags for {image}: {e}", file=sys.stderr)

    return tags


def find_version_tag_for_latest(image: str) -> dict | None:
    """Find the semver tag that matches the 'latest' digest.

    Args:
        image: Full image name (e.g., 'lintoai/studio-api')

    Returns:
        Dict with version info or None if not found
    """
    tags = get_dockerhub_tags(image)
    if not tags:
        return None

    # Find the 'latest' tag and its digest
    latest_digest = None
    latest_pushed = None
    for tag in tags:
        if tag["name"] == "latest":
            latest_digest = tag["digest"]
            latest_pushed = tag["last_pushed"]
            break

    if not latest_digest:
        print(f"  Warning: No 'latest' tag found for {image}", file=sys.stderr)
        return None

    # Find semver tags with the same digest
    # Semver pattern: X.Y.Z or vX.Y.Z (with optional pre-release)
    semver_pattern = re.compile(r"^v?(\d+\.\d+\.\d+)(-\w+)?$")

    matching_versions = []
    for tag in tags:
        if tag["digest"] == latest_digest and tag["name"] != "latest":
            match = semver_pattern.match(tag["name"])
            if match:
                matching_versions.append(tag["name"])

    if not matching_versions:
        # No semver match, return latest info anyway
        return {
            "tag": "latest",
            "digest": latest_digest,
            "version": None,
            "last_pushed": latest_pushed,
            "commit": None,
        }

    # Sort versions and pick the highest (most recent)
    # Simple sort works for most cases, could use packaging.version for robustness
    matching_versions.sort(reverse=True)
    version_tag = matching_versions[0]

    return {
        "tag": version_tag,
        "digest": latest_digest,
        "version": version_tag.lstrip("v"),
        "last_pushed": latest_pushed,
        "commit": None,  # Will be filled in later with GitHub data
    }


def create_rc_file(versions_dir: Path, dry_run: bool = False) -> Path | None:
    """Create the RC version file by querying DockerHub.

    Args:
        versions_dir: Path to versions directory
        dry_run: If True, print without writing

    Returns:
        Path to created file or None if dry run
    """
    # Load latest.yaml as base template
    latest_file = versions_dir / "latest.yaml"
    if not latest_file.exists():
        print(f"Error: {latest_file} not found", file=sys.stderr)
        sys.exit(1)

    with open(latest_file) as f:
        versions = yaml.safe_load(f)

    print("Querying DockerHub for service versions...")
    print()

    # Track versions for RC naming
    service_versions = {}
    all_have_versions = True

    # Update all linto service tags
    for service, config in versions.get("linto", {}).items():
        image = config.get("image")
        if not image:
            continue

        print(f"  {service} ({image})...")
        version_info = find_version_tag_for_latest(image)

        if version_info:
            old_tag = config.get("tag", "latest")
            new_tag = version_info["tag"]
            config["tag"] = new_tag

            # Add digest
            if version_info.get("digest"):
                config["digest"] = version_info["digest"]

            # Get commit SHA from GitHub
            repo_url = config.get("repo", "")
            commit_sha = None
            commit_source = None
            commit_error = None

            if repo_url:
                # Strategy 1: Try to get commit from version tag
                if version_info["version"]:
                    commit_sha, commit_error = get_github_commit_for_tag(repo_url, version_info["tag"])
                    if commit_sha:
                        commit_source = "tag"

                # Strategy 2: Try to get commit by Docker push date
                if not commit_sha and commit_error != "rate-limited" and version_info.get("last_pushed"):
                    commit_sha, commit_error = get_github_commit_by_date(repo_url, version_info["last_pushed"])
                    if commit_sha:
                        commit_source = "date"

                # Strategy 3: Fallback to latest commit on default branch
                if not commit_sha and commit_error != "rate-limited":
                    commit_sha, commit_error = get_github_default_branch_commit(repo_url)
                    if commit_sha:
                        commit_source = "head"

                # Store commit or placeholder
                if commit_sha:
                    version_info["commit"] = commit_sha
                    version_info["commit_source"] = commit_source
                    config["commit"] = commit_sha
                elif commit_error:
                    # Store placeholder with error reason
                    placeholder = f"<{commit_error}>"
                    version_info["commit"] = placeholder
                    version_info["commit_source"] = commit_error
                    config["commit"] = placeholder

            service_versions[service] = version_info

            digest_short = version_info["digest"][:19] + "..." if version_info.get("digest") else ""
            if version_info.get("commit"):
                if version_info["commit"].startswith("<"):
                    commit_str = version_info["commit"]
                else:
                    commit_str = f"{version_info['commit'][:7]} ({commit_source})"
            else:
                commit_str = "-"

            if version_info["version"]:
                print(f"    {old_tag} -> {new_tag} (commit: {commit_str})")
            else:
                print(f"    {old_tag} -> latest (no semver, commit: {commit_str})")
                all_have_versions = False
        else:
            print(f"    Could not determine version, keeping {config.get('tag', 'latest')}")
            all_have_versions = False

    # Fetch digests for databases (no commit needed)
    print()
    print("Fetching database digests...")
    for service, config in versions.get("databases", {}).items():
        image = config.get("image")
        tag = config.get("tag", "latest")
        if not image:
            continue

        print(f"  {service} ({image}:{tag})...", end=" ")
        digest = get_dockerhub_tag_digest(image, tag)

        if digest:
            config["digest"] = digest
            print(f"digest: {digest[:19]}...")
        else:
            print("digest not found")

    # Fetch digests for LLM services (no commit needed)
    print()
    print("Fetching LLM digests...")
    for service, config in versions.get("llm", {}).items():
        image = config.get("image")
        tag = config.get("tag", "latest")
        if not image:
            continue

        print(f"  {service} ({image}:{tag})...", end=" ")
        digest = get_dockerhub_tag_digest(image, tag)

        if digest:
            config["digest"] = digest
            print(f"digest: {digest[:19]}...")
        else:
            print("digest not found")

    # Generate RC version name
    now = datetime.now(timezone.utc)
    date_str = now.strftime("%Y.%m.%d")

    # Find a representative commit (from the main service like studio-api)
    main_commit = None
    main_version = None
    for service_name in ["studio-api", "studio-frontend"]:
        if service_name in service_versions:
            info = service_versions[service_name]
            # Only use commit if it's a real SHA (not a placeholder)
            if info.get("commit") and not info["commit"].startswith("<"):
                main_commit = info["commit"][:7]
            if info.get("version"):
                main_version = info["version"]
            break

    # Build RC version string: RC-{date}-{version}-{commit}
    if main_version and main_commit:
        rc_version = f"RC-{date_str}-v{main_version}-{main_commit}"
    elif main_version:
        rc_version = f"RC-{date_str}-v{main_version}"
    elif main_commit:
        rc_version = f"RC-{date_str}-{main_commit}"
    else:
        rc_version = f"RC-{date_str}"

    versions["platform_version"] = rc_version

    print()
    print(f"RC Version: {rc_version}")

    if dry_run:
        print("\n[DRY RUN] Would write to versions/rc.yaml")
        return None

    # Write RC file
    rc_file = versions_dir / "rc.yaml"
    with open(rc_file, "w") as f:
        f.write("# LinTO Platform - Release Candidate Version\n")
        f.write("#\n")
        f.write("# This file is automatically generated by querying DockerHub.\n")
        f.write("# Each service tag matches the 'latest' image digest to its semver version.\n")
        f.write("#\n")
        f.write(f"# RC Version: {rc_version}\n")
        f.write(f"# Generated: {now.isoformat()}\n")
        f.write("#\n")
        f.write("# DO NOT EDIT MANUALLY - This file is auto-generated\n\n")

        # Write YAML content (excluding internal metadata)
        versions_to_write = {k: v for k, v in versions.items() if not k.startswith("_")}
        yaml.dump(versions_to_write, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    return rc_file


def main():
    """Main entry point."""
    dry_run = os.environ.get("DRY_RUN", "").lower() == "true"

    # Find versions directory
    script_dir = Path(__file__).parent
    base_dir = script_dir.parent
    versions_dir = base_dir / "versions"

    print("Building RC version from DockerHub...")
    print()

    rc_file = create_rc_file(versions_dir, dry_run)

    if rc_file:
        print(f"\nCreated: {rc_file}")

    print("\nDone!")


if __name__ == "__main__":
    main()
