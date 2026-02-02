#!/usr/bin/env python3
"""Update a single service in rc.yaml.

Called by GitHub Actions when Jenkins notifies that a service image was built.

Environment variables:
- SERVICE: Service name to update (required)
- TAG: Docker tag (default: 'latest')
- COMMIT_SHA: Git commit SHA (optional, will be fetched if not provided)
- GITHUB_TOKEN: GitHub token for API requests (optional, increases rate limit)
"""

import os
import sys
from pathlib import Path
from urllib.parse import urlparse

import requests
import yaml


def get_dockerhub_tag_info(image: str, tag: str) -> dict | None:
    """Get tag info including digest from DockerHub."""
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
        print(f"Warning: Could not fetch tag info: {e}", file=sys.stderr)

    return None


def main():
    service = os.environ.get("SERVICE")
    tag = os.environ.get("TAG", "latest")
    commit_sha = os.environ.get("COMMIT_SHA")

    if not service:
        print("Error: SERVICE environment variable is required", file=sys.stderr)
        sys.exit(1)

    # Find rc.yaml
    script_dir = Path(__file__).parent
    rc_file = script_dir.parent / "versions" / "rc.yaml"

    if not rc_file.exists():
        print(f"Error: {rc_file} not found", file=sys.stderr)
        sys.exit(1)

    # Load rc.yaml
    with open(rc_file) as f:
        versions = yaml.safe_load(f)

    # Find service in linto section
    if service not in versions.get("linto", {}):
        print(f"Error: Service '{service}' not found in rc.yaml", file=sys.stderr)
        sys.exit(1)

    config = versions["linto"][service]
    image = config.get("image")

    if not image:
        print(f"Error: No image defined for service '{service}'", file=sys.stderr)
        sys.exit(1)

    print(f"Updating {service}...")
    print(f"  Image: {image}")
    print(f"  Tag: {tag}")

    # Fetch digest from DockerHub
    tag_info = get_dockerhub_tag_info(image, tag)

    if tag_info:
        config["tag"] = tag
        if tag_info.get("digest"):
            config["digest"] = tag_info["digest"]
            print(f"  Digest: {tag_info['digest'][:19]}...")
    else:
        print("  Warning: Could not fetch digest from DockerHub", file=sys.stderr)
        config["tag"] = tag

    # Set commit if provided
    if commit_sha:
        config["commit"] = commit_sha
        print(f"  Commit: {commit_sha[:7]}")

    # Save rc.yaml
    with open(rc_file, "w") as f:
        yaml.dump(versions, f, default_flow_style=False, sort_keys=False, allow_unicode=True)

    print(f"\nUpdated {rc_file}")


if __name__ == "__main__":
    main()
