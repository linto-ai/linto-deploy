# LinTO Deploy - Command Reference

This document provides comprehensive documentation for all linto CLI commands with real-world usage scenarios.

## Quick Reference

| Command | Description |
|---------|-------------|
| `linto wizard` | Interactive profile creation wizard |
| `linto list` | List all deployment profiles |
| `linto show <profile>` | Display profile configuration details |
| `linto render <profile>` | Generate Helm values files without deploying |
| `linto deploy <profile>` | Generate values and deploy to Kubernetes cluster |
| `linto status <profile>` | Show deployment status with resource metrics |
| `linto logs <profile> <service>` | View service logs |
| `linto redeploy <profile>` | Force restart deployments |
| `linto destroy <profile>` | Remove deployment from cluster |
| `linto version` | Show version information |
| `linto profile set-kubeconfig <profile> <file>` | Set kubeconfig for a profile |
| `linto kubeconfig export <profile>` | Export kubeconfig for manual kubectl/helm |

## Cluster Access

Profiles are self-contained and include cluster connection settings. Use `linto kubeconfig export` if you need to run kubectl/helm commands manually:

```bash
# Export to file
linto kubeconfig export prod -o /tmp/prod.yaml
KUBECONFIG=/tmp/prod.yaml kubectl get pods -n linto

# Or merge into ~/.kube/config
linto kubeconfig export prod --merge
kubectl config use-context prod
```

---

## Installation & Setup

### Prerequisites

1. **kubectl** - Kubernetes command-line tool
   ```bash
   kubectl version --client
   ```

2. **helm** (v3.x) - Kubernetes package manager
   ```bash
   helm version
   ```

3. **Python 3.11+**
   ```bash
   python3 --version
   ```

4. **Kubernetes cluster access**
   ```bash
   kubectl cluster-info
   kubectl get nodes
   ```

### Installation

```bash
# Clone the repository
git clone https://github.com/linto-ai/linto-deploy.git
cd linto-deploy

# Install with uv (recommended)
uv sync
uv run linto --help

# Or install with pip
python -m venv .venv
source .venv/bin/activate
pip install -e .
linto --help
```

### Shell Completion

Enable tab completion for better productivity:

```bash
# Bash
linto --install-completion bash
source ~/.bashrc

# Zsh
linto --install-completion zsh

# Fish
linto --install-completion fish
```

---

## Scenarios

### Scenario 1: First Deployment (New User)

A step-by-step guide for deploying LinTO for the first time.

#### Step 1: Create a profile with the wizard

```bash
linto wizard
```

The wizard will guide you through:
- Profile name (e.g., `production`, `dev`, `staging`)
- Domain configuration (e.g., `linto.example.com`)
- Kubernetes namespace
- Storage configuration
- Service selection (Studio, STT, Live Session, LLM)
- GPU configuration
- TLS settings
- Admin account

#### Step 2: Review generated configuration

```bash
linto render production
```

This creates Helm values files in `.linto/render/k3s/production/values/`.

Review the generated files:
```bash
ls -la .linto/render/k3s/production/values/
# studio-values.yaml
# stt-values.yaml
# live-values.yaml  (if Live Session enabled)
# llm-values.yaml   (if LLM enabled)
```

#### Step 3: Deploy to cluster

```bash
linto deploy production
```

#### Step 4: Verify deployment

```bash
linto status production
```

Expected output:
```
Profile: production (k3s)
Domain: linto.example.com
Namespace: linto

                          Services
┏━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Service                   ┃ Status  ┃ CPU       ┃ URL                             ┃
┡━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ pod/studio-api-xxx        │ Running │ 50m/2     │ https://linto.example.com/cm-api│
│ pod/studio-frontend-xxx   │ Running │ 10m/500m  │ https://linto.example.com/      │
│ pod/studio-websocket-xxx  │ Running │ 5m/500m   │ https://linto.example.com/ws    │
└───────────────────────────┴─────────┴───────────┴─────────────────────────────────┘
```

---

### Scenario 2: Daily Operations

Commands for routine monitoring and maintenance.

#### Check deployment health

```bash
# Full status with resource metrics
linto status production

# Compact view (hide CPU/Memory/GPU columns)
linto status production --compact

# Continuous monitoring (refreshes every 5 seconds)
linto status production --follow

# Custom refresh interval (10 seconds)
linto status production --follow --interval 10
```

#### View service logs

```bash
# View last 100 lines from studio-api
linto logs production studio-api

# Stream logs in real-time
linto logs production studio-api --follow

# View last 500 lines
linto logs production studio-api --tail 500
```

---

### Scenario 3: Updating a Deployment

When you need to modify configuration or update images.

#### Option A: Update configuration

1. Edit the profile JSON directly:
   ```bash
   # Profile location
   cat .linto/profiles/production.json
   ```

2. Or re-run the wizard (creates new profile):
   ```bash
   linto wizard
   ```

3. Regenerate Helm values:
   ```bash
   linto render production
   ```

4. Apply changes:
   ```bash
   linto deploy production
   ```

#### Option B: Force image update (for `latest-*` tags)

When using floating tags like `latest-unstable`:

```bash
# Restart all deployments to pull latest images
linto redeploy production

# Restart only a specific chart
linto redeploy production linto-studio
```

---

### Scenario 4: Managing Multiple Environments

Best practices for dev, staging, and production environments.

#### List all profiles

```bash
linto list
```

Output:
```
                    Profiles
┏━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━┓
┃ Name        ┃ Backend ┃ Domain                ┃ Services            ┃
┡━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━┩
│ dev         │ k3s     │ localhost             │ studio, stt         │
│ staging     │ k3s     │ staging.linto.ai      │ studio, stt, live   │
│ production  │ k3s     │ linto.example.com     │ studio, stt, live   │
└─────────────┴─────────┴───────────────────────┴─────────────────────┘
```

#### View profile details

```bash
linto show staging
```

Output:
```
                 Profile: staging
┏━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┓
┃ Setting        ┃ Value                            ┃
┡━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┩
│ Name           │ staging                          │
│ Backend        │ k3s                              │
│ Domain         │ staging.linto.ai                 │
│ Image Tag      │ latest-unstable                  │
│ TLS Mode       │ acme                             │
│ GPU Mode       │ exclusive                        │
│ GPU Count      │ 2                                │
│ Studio         │ enabled                          │
│ STT            │ enabled                          │
│ Live Session   │ enabled                          │
│ LLM            │ disabled                         │
│ Admin Email    │ admin@linto.ai                   │
│ Namespace      │ linto-staging                    │
│ Storage Class  │ local-path                       │
└────────────────┴──────────────────────────────────┘
```

#### Recommended profile naming

- `dev` - Local development
- `staging` - Pre-production testing
- `production` or `prod` - Production environment
- `demo` - Demonstration environment

---

### Scenario 5: Troubleshooting

Diagnosing and fixing common issues.

#### Check pod states

```bash
linto status production
```

Look for:
- `Pending` - Pod waiting for resources or scheduling
- `Error` - Pod crashed or failed to start
- `CrashLoopBackOff` - Pod repeatedly crashing

#### View detailed logs

```bash
# Check for errors in studio-api
linto logs production studio-api --tail 500

# Follow logs to see real-time errors
linto logs production studio-api --follow
```

#### Common issues

**Pods stuck in Pending:**
```bash
# Check node resources
kubectl describe nodes

# Check pod events
kubectl describe pod <pod-name> -n <namespace>
```

**Image pull errors:**
```bash
# Force restart to pull fresh images
linto redeploy production

# Check image pull status
kubectl describe pod <pod-name> -n <namespace> | grep -A5 "Events"
```

**Certificate issues (ACME):**
```bash
# Check cert-manager logs
kubectl logs -n cert-manager deployment/cert-manager

# Check certificate status
kubectl get certificates -n <namespace>
```

---

### Scenario 6: Cleanup & Removal

Removing deployments safely.

#### Remove deployment (keep data)

```bash
linto destroy production
```

This will:
1. Backup TLS certificates (if ACME)
2. Uninstall all Helm releases
3. Keep PVCs (persistent data)

#### Remove deployment with all data

```bash
# WARNING: This deletes all databases and cached models!
linto destroy production --volumes
```

#### Skip confirmation prompts

```bash
linto destroy production --force
linto destroy production --force --volumes
```

#### Remove generated files

```bash
linto destroy production --remove-files
```

---

## Command Reference (Detailed)

### linto wizard

Interactive profile creation wizard.

**Usage:**
```bash
linto wizard
```

**Description:**

Launches an interactive wizard that guides you through creating a deployment profile.

**Wizard Flow:**

1. **Profile name** - Identifier for this deployment (alphanumeric, hyphens allowed)
2. **Domain** - Hostname for accessing the deployment
3. **Backend** - Currently only k3s is supported
4. **Namespace** - Kubernetes namespace for deployment
5. **Storage configuration** - StorageClass and host paths
6. **Service selection** - Choose which services to enable:
   - Studio (Web UI, API, WebSocket)
   - STT (Speech-to-text with Whisper)
   - Live Session (Real-time streaming)
   - LLM (Language model integration)
7. **GPU configuration** - None, exclusive, or time-slicing
8. **TLS configuration** - Off, mkcert, ACME (Let's Encrypt), or custom
9. **Admin account** - Super admin configuration
10. **Action** - Save, render (generate files), or deploy

**Example session:**
```
LinTO Deployment Wizard
Configure your LinTO deployment interactively

Profile name [dev]: production
Domain [localhost]: linto.example.com

Deployment backend: Kubernetes (k3s)

Kubernetes namespace [linto]: linto-prod

Persistent Storage:
LinTO stores data in two locations:
  • Databases (MongoDB, PostgreSQL, Redis) → local disk on one node
  • Files (models, audio, exports) → shared storage (NFS recommended)

Database path on host [/home/ubuntu/linto/databases]:
Shared files path (NFS mount) [/data/linto]:
...
```

---

### linto list

List all deployment profiles.

**Usage:**
```bash
linto list
```

**Description:**

Displays a table of all profiles stored in `.linto/profiles/`. Shows profile name, backend type, domain, and enabled services.

**Output:**
```
                    Profiles
┏━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━━━━━━━━━┓
┃ Name        ┃ Backend ┃ Domain            ┃ Services        ┃
┡━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━━━━━━━━━┩
│ dev         │ k3s     │ localhost         │ studio, stt     │
│ production  │ k3s     │ linto.example.com │ studio, stt     │
└─────────────┴─────────┴───────────────────┴─────────────────┘
```

---

### linto profile set-kubeconfig \<profile\> \<file\>

Set or update kubeconfig for an existing profile.

**Usage:**
```bash
linto profile set-kubeconfig <profile> <kubeconfig-file>
```

**Arguments:**
| Argument | Description |
|----------|-------------|
| `profile` | Name of the profile |
| `kubeconfig-file` | Path to kubeconfig file (e.g., k3s.yaml) |

**Example:**
```bash
# Copy kubeconfig from server
scp ubuntu@k3s-server:/etc/rancher/k3s/k3s.yaml ~/Downloads/

# Set it in profile
linto profile set-kubeconfig prod ~/Downloads/k3s.yaml
```

---

### linto kubeconfig export \<profile\>

Export kubeconfig from a profile for manual kubectl/helm usage.

**Usage:**
```bash
linto kubeconfig export <profile> [OPTIONS]
```

**Arguments:**
| Argument | Description |
|----------|-------------|
| `profile` | Name of the profile |

**Options:**
| Option | Short | Description |
|--------|-------|-------------|
| `--output` | `-o` | Write to file instead of stdout |
| `--merge` | | Merge into ~/.kube/config |

**Examples:**
```bash
# Output to stdout
linto kubeconfig export prod

# Write to file
linto kubeconfig export prod -o ~/.kube/linto-prod.yaml

# Merge into existing kubeconfig
linto kubeconfig export prod --merge

# Then use manually
kubectl config use-context prod
kubectl get pods -n linto
```

---

### linto show \<profile\>

Display detailed profile configuration.

**Usage:**
```bash
linto show <profile>
```

**Arguments:**
| Argument | Description |
|----------|-------------|
| `profile` | Name of the profile to display |

**Example:**
```bash
linto show production
```

---

### linto render \<profile\>

Generate Helm values files without deploying.

**Usage:**
```bash
linto render <profile> [--output DIR]
```

**Arguments:**
| Argument | Description |
|----------|-------------|
| `profile` | Name of the profile |

**Options:**
| Option | Short | Description |
|--------|-------|-------------|
| `--output` | `-o` | Custom output directory |

**What it does:**
1. Loads the profile configuration
2. Creates Helm values files for enabled services

**Output location:**
```
.linto/render/k3s/<profile>/values/
├── studio-values.yaml
├── stt-values.yaml
├── live-values.yaml    (if Live Session enabled)
└── llm-values.yaml     (if LLM enabled)
```

**Example:**
```bash
linto render production
# Output: .linto/render/k3s/production/values/
```

---

### linto deploy \<profile\>

Deploy services to the Kubernetes cluster.

**Usage:**
```bash
linto deploy <profile> [--force]
```

**Arguments:**
| Argument | Description |
|----------|-------------|
| `profile` | Name of the profile to deploy |

**Options:**
| Option | Description |
|--------|-------------|
| `--force` | Skip GPU capacity warnings |

**What it does:**
1. Validates prerequisites (kubectl, helm, cluster access)
2. Ensures namespace exists (creates if needed)
3. Installs cert-manager (if ACME TLS mode)
4. Restores TLS certificates from backup (if available)
5. Generates values files (if not present)
6. Runs `helm upgrade --install` for each enabled chart

**Example:**
```bash
linto deploy production

# Sample output:
Installing/upgrading linto-studio...
linto-studio deployed successfully
Installing/upgrading linto-stt...
linto-stt deployed successfully
Deployment complete!
Access at: https://linto.example.com
```

---

### linto status \<profile\>

Show deployment status with resource metrics.

**Usage:**
```bash
linto status <profile> [OPTIONS]
```

**Arguments:**
| Argument | Description |
|----------|-------------|
| `profile` | Name of the profile |

**Options:**
| Option | Short | Description |
|--------|-------|-------------|
| `--compact` | `-c` | Hide resource metrics (CPU, Memory, GPU) |
| `--follow` | `-f` | Continuously refresh status |
| `--interval` | `-i` | Refresh interval in seconds (default: 5) |

**Output columns:**
- Service name
- Status (Running, Pending, Error)
- CPU usage (current/limit)
- Memory usage (current/limit)
- GPU count (if applicable)
- Endpoint URL

**Examples:**
```bash
# Full status
linto status production

# Compact view
linto status production --compact

# Continuous monitoring
linto status production --follow

# Custom refresh interval
linto status production --follow --interval 10
```

---

### linto logs \<profile\> \<service\>

View logs from a specific service.

**Usage:**
```bash
linto logs <profile> <service> [OPTIONS]
```

**Arguments:**
| Argument | Description |
|----------|-------------|
| `profile` | Name of the profile |
| `service` | Service/deployment name (tab-completion supported) |

**Options:**
| Option | Short | Description |
|--------|-------|-------------|
| `--follow` | `-f` | Stream logs in real-time |
| `--tail` | `-n` | Number of lines to show (default: 100) |

**Service names:**
- `studio-api`, `studio-frontend`, `studio-websocket`
- `stt-all-whisper-v3-turbo`, `stt-whisper-workers`, `diarization-pyannote`
- `session-api`, `session-scheduler`, `session-transcriber`
- `llm-gateway-api`, `llm-celery-worker`, `llm-gateway-frontend`

**Examples:**
```bash
# View recent logs
linto logs production studio-api

# Follow logs
linto logs production studio-api --follow

# View last 500 lines
linto logs production studio-api --tail 500
```

---

### linto redeploy \<profile\> [chart]

Force restart deployments (useful for `latest-*` image tags).

**Usage:**
```bash
linto redeploy <profile> [chart] [OPTIONS]
```

**Arguments:**
| Argument | Description |
|----------|-------------|
| `profile` | Name of the profile |
| `chart` | Specific chart to redeploy (optional) |

**Charts:**
- `linto-studio`
- `linto-stt`
- `linto-live`
- `linto-llm`

**What it does:**
1. Runs `kubectl rollout restart` for deployments
2. Kubernetes pulls fresh images (with imagePullPolicy: Always) and recreates pods

**Examples:**
```bash
# Restart all deployments
linto redeploy production

# Restart only Studio services
linto redeploy production linto-studio
```

---

### linto destroy \<profile\>

Remove deployment from cluster.

**Usage:**
```bash
linto destroy <profile> [OPTIONS]
```

**Arguments:**
| Argument | Description |
|----------|-------------|
| `profile` | Name of the profile to destroy |

**Options:**
| Option | Short | Description |
|--------|-------|-------------|
| `--force` | | Skip confirmation prompt |
| `--volumes` | `-v` | Also remove PVCs (persistent data) |
| `--remove-files` | `-r` | Remove generated files |

**What it does:**
1. Backs up TLS certificates (if ACME mode)
2. Runs `helm uninstall` for each chart
3. Optionally removes PVCs
4. Optionally removes generated files

**Warning:** `--volumes` will permanently delete:
- Database contents
- Model caches
- Audio files

**Examples:**
```bash
# Remove deployment, keep data
linto destroy production

# Remove deployment and all data
linto destroy production --volumes

# Skip confirmation
linto destroy production --force

# Remove everything including generated files
linto destroy production --force --volumes --remove-files
```

---

### linto version

Show version information.

**Usage:**
```bash
linto version
```

**Example output:**
```
linto-deploy version 0.1.0
```

---

## Configuration Reference

### Profile Fields

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `name` | string | `dev` | Profile identifier (alphanumeric, hyphens) |
| `domain` | string | `localhost` | Deployment domain |
| `backend` | enum | `k3s` | Deployment backend (only k3s supported) |
| `image_tag` | string | `latest-unstable` | Docker image tag |
| `tls_mode` | enum | `mkcert` | TLS mode: off, mkcert, acme, custom |
| `gpu_mode` | enum | `none` | GPU mode: none, exclusive, time-slicing |
| `gpu_count` | int | `1` | Number of GPUs available |
| `studio_enabled` | bool | `true` | Enable Studio services |
| `stt_enabled` | bool | `true` | Enable STT services |
| `live_session_enabled` | bool | `false` | Enable Live Session |
| `llm_enabled` | bool | `false` | Enable LLM services |
| `k3s_namespace` | string | `linto` | Kubernetes namespace |
| `k3s_storage_class` | string | null | StorageClass for PVCs |
| `super_admin_email` | string | `admin@linto.local` | Admin email address |

### TLS Modes

| Mode | Description |
|------|-------------|
| `off` | No TLS (HTTP only, not recommended) |
| `mkcert` | Local development certificates |
| `acme` | Let's Encrypt certificates (production) |
| `custom` | User-provided certificates |

### GPU Modes

| Mode | Description |
|------|-------------|
| `none` | CPU only, no GPU |
| `exclusive` | One GPU per pod (recommended for production) |
| `time-slicing` | Share GPU across pods (development/testing) |

---

## Troubleshooting Guide

### Common Issues

#### Pods stuck in Pending

**Symptoms:** Pods remain in `Pending` state.

**Diagnosis:**
```bash
# Check pod events
kubectl describe pod <pod-name> -n <namespace>

# Check node resources
kubectl describe nodes

# Check PVC status
kubectl get pvc -n <namespace>
```

**Common causes:**
- Insufficient CPU/memory on nodes
- PVC cannot be provisioned (wrong StorageClass)
- Node selector doesn't match any nodes
- GPU requested but not available

---

#### Certificate not issued (ACME)

**Symptoms:** HTTPS not working, certificate errors in browser.

**Diagnosis:**
```bash
# Check certificate status
kubectl get certificates -n <namespace>

# Check cert-manager logs
kubectl logs -n cert-manager deployment/cert-manager

# Check certificate request
kubectl describe certificaterequest -n <namespace>
```

**Common causes:**
- Domain DNS not pointing to cluster
- Port 80 not accessible (HTTP-01 challenge)
- Rate limit exceeded

---

#### Image pull errors

**Symptoms:** Pods in `ImagePullBackOff` state.

**Diagnosis:**
```bash
kubectl describe pod <pod-name> -n <namespace>
```

**Solutions:**
```bash
# Force restart to pull fresh images
linto redeploy <profile>

# Check image name and tag
kubectl get pod <pod-name> -n <namespace> -o yaml | grep image
```

---

#### Database connection errors

**Symptoms:** Services failing to connect to MongoDB/PostgreSQL.

**Diagnosis:**
```bash
# Check database pod status
linto status <profile>

# View database logs
linto logs <profile> studio-mongodb
linto logs <profile> session-postgres
```

**Common causes:**
- Database pod not ready yet
- Incorrect password in configuration
- PVC issues

---

#### Services not accessible

**Symptoms:** Cannot access the web interface or API.

**Diagnosis:**
```bash
# Check ingress
kubectl get ingress -n <namespace>

# Check traefik logs (ingress controller)
kubectl logs -n kube-system -l app.kubernetes.io/name=traefik

# Verify DNS resolution
nslookup <domain>
```

**Common causes:**
- DNS not configured
- Firewall blocking ports 80/443
- TLS certificate issues
- Ingress misconfiguration
