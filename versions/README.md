# LinTO Platform Versions

This directory contains version configuration files for the LinTO platform.

## Files

| File | Description | Usage |
|------|-------------|-------|
| `latest.yaml` | Release Candidate | Stable testing with `latest` tags |
| `latest-unstable.yaml` | Development | Bleeding edge with `latest-unstable` tags |
| `platform.YYYY.MM.yaml` | Stable Release | Frozen versions for production |

## Usage

```bash
# Development (latest-unstable)
linto profile edit <profile> --versions-file versions/latest-unstable.yaml

# Release Candidate (latest)
linto profile edit <profile> --versions-file versions/latest.yaml

# Stable release
linto profile edit <profile> --versions-file versions/platform.2026.01.yaml
```

## Version Lifecycle

```
latest-unstable  →  latest  →  platform.YYYY.MM
(development)      (RC)        (stable)
```

1. **Development** (`latest-unstable`): Built from every commit to main/master
2. **Release Candidate** (`latest`): Built from tagged releases, ready for testing
3. **Stable** (`platform.YYYY.MM`): Frozen versions validated for production

## Creating a Stable Release

```bash
# Via GitHub Actions (recommended)
# Go to Actions > Create Platform Release > Run workflow

# Or manually
python scripts/create-release.py platform.2026.01
```

This creates `versions/platform.2026.01.yaml` with all current versions frozen.
