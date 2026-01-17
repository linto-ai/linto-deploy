# LinTO Deploy

A CLI tool for deploying and managing LinTO AI services on Kubernetes (k3s). It provides an interactive wizard for configuration and Helm-based deployments.

## Quick Install

```bash
git clone https://github.com/linto-ai/linto-deploy.git
cd linto-deploy
uv sync
uv run linto wizard
```

## Quick Start

```bash
# Create a deployment profile
linto wizard

# Deploy to your cluster
linto deploy <profile>

# Check status
linto status <profile>

# View logs
linto logs <profile> <service>
```

## Project Structure

```
.linto/              # User configuration (gitignored)
  profiles/          # Deployment profiles
  render/            # Generated Helm values
charts/              # Helm charts for LinTO services
ansible/             # Cluster provisioning playbooks
```

Profiles are self-contained and portable across machines.

## Documentation

- **[Command Reference](docs/COMMANDS.md)** - Complete CLI documentation with scenarios and troubleshooting
- **[Ansible Infrastructure](docs/ansible/README.md)** - K3S cluster provisioning with Ansible

## Prerequisites

- Python 3.11+
- kubectl
- helm (v3.x)
- Access to a Kubernetes (k3s) cluster

## License

[AGPL-3.0-or-later](LICENSE)
