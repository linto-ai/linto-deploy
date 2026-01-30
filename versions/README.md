# LinTO Platform Versions

This directory contains version configuration files for the LinTO platform.

## Files

| File | Description | Usage |
|------|-------------|-------|
| `rc.yaml` | Release Candidate | Auto-generated, includes tag/digest/commit |
| `latest.yaml` | Latest stable | Uses `latest` Docker tags |
| `latest-unstable.yaml` | Development | Uses `latest-unstable` Docker tags |
| `platform.YYYY.MM.yaml` | Stable Release | Frozen versions for production |

## Workflow

```
1. Service publishes new "latest" image on DockerHub
                    ↓
2. WE manually trigger "Build RC Version" workflow
   → Detects new versions, adds tag/digest/commit to rc.yaml
                    ↓
3. WE test the RC in our environment
                    ↓
4. WE decide it's ready → trigger "Create Release" workflow
   → Creates versions/platform.YYYY.MM.yaml
```

## Usage

```bash
# Release Candidate (for testing)
linto profile edit <profile> --versions-file versions/rc.yaml

# Stable release (for production)
linto profile edit <profile> --versions-file versions/platform.2026.01.yaml

# Latest (always uses 'latest' Docker tags)
linto profile edit <profile> --versions-file versions/latest.yaml
```

## RC (Release Candidate)

The RC file contains full traceability for each service:

```yaml
linto:
  studio-api:
    image: lintoai/studio-api
    tag: 1.6.0                    # Exact version
    repo: https://github.com/...
    digest: sha256:aee909fb...    # Docker image digest
    commit: abc123def456...       # Git commit (when available)
```

### Building RC

**Via GitHub Actions (recommended):**
1. Go to Actions > "Build RC Version"
2. Click "Run workflow"
3. Review the generated `rc.yaml`

**Locally:**
```bash
GITHUB_TOKEN=ghp_xxx python scripts/build-rc.py
```

### How commits are retrieved

1. **From GitHub tag** - If repo has a tag matching the version (e.g., `v1.6.0`)
2. **By date** - Finds commit closest to Docker image push date
3. **HEAD** (fallback) - Latest commit on default branch

## Creating a Stable Release

When the RC is tested and ready:

**Via GitHub Actions (recommended):**
1. Go to Actions > "Create Release"
2. Enter version (e.g., `platform.2026.01`) or leave empty for auto
3. Click "Run workflow"

This creates:
- `versions/platform.2026.01.yaml` - Frozen version file
- `docs/releases/platform.2026.01.md` - Release notes
- Git tag `platform.2026.01`
- GitHub Release

**Locally:**
```bash
python scripts/create-release.py platform.2026.01
```

## Version Lifecycle

```
DockerHub "latest"  →  rc.yaml  →  platform.YYYY.MM.yaml
     (source)           (RC)           (stable)
         ↑                ↑                 ↑
   Services push    We trigger        We trigger
   new images       Build RC          Create Release
```
