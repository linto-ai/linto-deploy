# LinTO Ansible Infrastructure

Ansible infrastructure for deploying a K3S cluster optimized for LinTO AI workloads (GPU transcription, NFS storage for models and media).

## Project Structure

```
ansible/                    # Reusable template (versioned)
  roles/                    # Common to all environments
  playbooks/                # Common to all environments
  inventory/                # Empty, see below

.linto/inventory/           # Environment-specific inventories (gitignored)
  production.yml
  staging.yml
  group_vars/

docs/ansible/
  inventory-example.yml     # Template to copy
```

## Quick Setup

```bash
# Create inventory from template
mkdir -p .linto/inventory
cp docs/ansible/inventory-example.yml .linto/inventory/production.yml

# Edit with your IPs
vim .linto/inventory/production.yml

# Deploy
ansible-playbook ansible/playbooks/site.yml -i .linto/inventory/production.yml
```

## Network Architecture

The cluster uses two addressing planes:

```
Internet
    |
    v
+-------------------+
|   ingress node    | <-- Public IP (DNS A record)
|   (fail2ban,      |     Ports 80, 443 open
|   rkhunter,       |     SSH protected by fail2ban
|   UFW strict)     |
+---------+---------+
          |
          | private network (192.168.1.0/24)
          |
    +-----+-----+-------------+
    |           |             |
    v           v             v
+-------+   +-------+   +----------+
| master|   |worker |   | gpu-node |
| + NFS |   |       |   |          |
+-------+   +-------+   +----------+
```

**Private network (`cluster_network`):**
- K3S inter-node communication (API 6443, Flannel 8472)
- NFS mounts between server and clients
- All machines have an IP on this network
- UFW allows all traffic from this network

**Public network (ingress only):**
- Public IP or IP on network exposed to Internet
- Only ports 80/443 open to the world
- SSH protected by fail2ban (ban after 5 failures)
- Daily monitoring by rkhunter and logwatch
- DNS A record points to this IP

## Prerequisites

### Control Machine (your workstation)

```bash
# Install Ansible via pip (recommended)
pip3 install ansible ansible-core

# Or via apt (Ubuntu/Debian)
sudo apt update && sudo apt install ansible

# Verify
ansible --version
```

### Target Machines

- Ubuntu Server 24.04 LTS
- SSH access with key (no password)
- User with passwordless sudo privileges
- Network connectivity between all nodes

### SSH Configuration

```bash
# Generate an SSH key if needed
ssh-keygen -t ed25519 -C "ansible@linto"

# Copy the key to each server
ssh-copy-id -i ~/.ssh/id_ed25519 ubuntu@192.168.1.10
ssh-copy-id -i ~/.ssh/id_ed25519 ubuntu@192.168.1.11
ssh-copy-id -i ~/.ssh/id_ed25519 ubuntu@203.0.113.50  # Ingress (public IP)

# Test the connection
ssh ubuntu@192.168.1.10 "hostname"
```

## Quick Start

### 1. Configure the Inventory

```bash
# Copy template and edit
cp docs/ansible/inventory-example.yml .linto/inventory/production.yml
vim .linto/inventory/production.yml
```

Example configuration with ingress:

```yaml
all:
  children:
    # Machine 1: K3S Master + NFS Server (private IP only)
    masters:
      hosts:
        linto-master-01:
          ansible_host: 192.168.1.10
          private_ip: 192.168.1.10

    nfs_server:
      hosts:
        linto-master-01:
          # nfs_disk: "auto"  # (default) detects first unformatted disk
          nfs_vg_name: vg_linto

    # Machine 2: GPU Worker (private IP only)
    gpu_nodes:
      hosts:
        linto-gpu-01:
          ansible_host: 192.168.1.11
          private_ip: 192.168.1.11
          nvidia_driver_version: "550"

    # Machine 3: Ingress node (public + private IP)
    ingress:
      hosts:
        linto-ingress-01:
          ansible_host: 203.0.113.50      # Public IP for initial SSH
          private_ip: 192.168.1.12        # Private IP for cluster
          public_ip: 203.0.113.50         # Public IP (DNS A points here)

    # Workers = GPU + Ingress (all non-masters)
    workers:
      hosts:
        linto-gpu-01:
        linto-ingress-01:

  vars:
    ansible_user: ubuntu
    ansible_ssh_private_key_file: ~/.ssh/id_ed25519
    cluster_network: "192.168.1.0/24"     # Private cluster network
```

### 2. Test Connectivity

```bash
# Ping all servers
ansible all -m ping -i .linto/inventory/production.yml

# Verify facts
ansible all -m setup -a "filter=ansible_distribution*" -i .linto/inventory/production.yml
```

### 3. Deploy the Cluster

```bash
# Full deployment
ansible-playbook playbooks/site.yml -i .linto/inventory/production.yml

# Or step by step
ansible-playbook playbooks/base.yml -i .linto/inventory/production.yml       # Base configuration
ansible-playbook playbooks/storage.yml -i .linto/inventory/production.yml    # NFS storage
ansible-playbook playbooks/k3s-cluster.yml -i .linto/inventory/production.yml # K3S cluster
```

## Useful Commands

### Pre-deployment Check (dry-run)

```bash
# Check mode (simulation without modifications)
ansible-playbook playbooks/site.yml -i .linto/inventory/production.yml --check

# Check mode with diff (see changes)
ansible-playbook playbooks/site.yml -i .linto/inventory/production.yml --check --diff
```

### Selective Deployment

```bash
# Single node
ansible-playbook playbooks/base.yml -i .linto/inventory/production.yml --limit linto-master-01

# Group of nodes
ansible-playbook playbooks/k3s-cluster.yml -i .linto/inventory/production.yml --limit workers

# With specific tags
ansible-playbook playbooks/site.yml -i .linto/inventory/production.yml --tags base
ansible-playbook playbooks/site.yml -i .linto/inventory/production.yml --tags k3s,gpu
ansible-playbook playbooks/site.yml -i .linto/inventory/production.yml --tags ingress
ansible-playbook playbooks/site.yml -i .linto/inventory/production.yml --tags nfs
```

### Debug and Verbosity

```bash
# Verbose mode
ansible-playbook playbooks/site.yml -i .linto/inventory/production.yml -v

# Very verbose mode (debug)
ansible-playbook playbooks/site.yml -i .linto/inventory/production.yml -vvv

# Display host variables
ansible linto-master-01 -i .linto/inventory/production.yml -m debug -a "var=hostvars[inventory_hostname]"
```

## Deployment Scenarios

### Scenario 1: Minimal (1 master + 1 GPU worker)

```yaml
# .linto/inventory/minimal.yml
all:
  children:
    masters:
      hosts:
        linto-master:
          ansible_host: 192.168.1.10
    nfs_server:
      hosts:
        linto-master:
          # nfs_disk: "auto"  # auto-detects
    gpu_nodes:
      hosts:
        linto-gpu:
          ansible_host: 192.168.1.11
    workers:
      hosts:
        linto-gpu:
  vars:
    ansible_user: ubuntu
    cluster_network: "192.168.1.0/24"
```

### Scenario 2: Standard with ingress (1 master/NFS + 1 GPU + 1 ingress)

```yaml
all:
  children:
    masters:
      hosts:
        linto-master-01:
          ansible_host: 192.168.1.10
          private_ip: 192.168.1.10
    nfs_server:
      hosts:
        linto-master-01:
          # nfs_disk: "auto"  # auto-detects
    gpu_nodes:
      hosts:
        linto-gpu-01:
          ansible_host: 192.168.1.11
          private_ip: 192.168.1.11
          nvidia_driver_version: "550"
    ingress:
      hosts:
        linto-ingress-01:
          ansible_host: 203.0.113.50
          private_ip: 192.168.1.12
          public_ip: 203.0.113.50
    workers:
      hosts:
        linto-gpu-01:
        linto-ingress-01:
  vars:
    ansible_user: ubuntu
    cluster_network: "192.168.1.0/24"
```

### Scenario 3: High Availability (3 masters + N workers + ingress)

```yaml
all:
  children:
    masters:
      hosts:
        linto-master-01:
          ansible_host: 192.168.1.10
        linto-master-02:
          ansible_host: 192.168.1.11
        linto-master-03:
          ansible_host: 192.168.1.12
    nfs_server:
      hosts:
        linto-storage-01:
          ansible_host: 192.168.1.20
          # nfs_disk: "auto"  # or /dev/sdb if specific
    gpu_nodes:
      hosts:
        linto-gpu-01:
          ansible_host: 192.168.1.30
        linto-gpu-02:
          ansible_host: 192.168.1.31
    ingress:
      hosts:
        linto-ingress-01:
          ansible_host: 203.0.113.50
          private_ip: 192.168.1.40
          public_ip: 203.0.113.50
    workers:
      hosts:
        linto-gpu-01:
        linto-gpu-02:
        linto-ingress-01:
  vars:
    ansible_user: ubuntu
    k3s_api_san: "k3s.mydomain.local"
    cluster_network: "192.168.1.0/24"
```

## Variable Configuration

### Global Variables (group_vars/all.yml)

```yaml
# Timezone
base_timezone: "Europe/Paris"

# K3S version (empty = latest stable)
k3s_version: ""

# Private cluster network
cluster_network: "192.168.1.0/24"

# NFS configuration
nfs_allowed_network: "192.168.1.0/24"
nfs_export_dirs:
  - models
  - audios
  - media
```

### Per-Host Variables

```yaml
# In your inventory file
linto-gpu-01:
  ansible_host: 192.168.1.11
  private_ip: 192.168.1.11
  nvidia_driver_version: "550"  # Specific driver version

linto-master-01:
  ansible_host: 192.168.1.10
  # nfs_disk: "auto"            # (default) detects first unformatted disk
  # nfs_disk: /dev/nvme1n1      # or specify explicitly

linto-ingress-01:
  ansible_host: 203.0.113.50    # Public IP for SSH
  private_ip: 192.168.1.12      # Private IP for cluster
  public_ip: 203.0.113.50       # IP for DNS A record
```

### Command-Line Variable Override

```bash
# Change timezone
ansible-playbook playbooks/base.yml -e "base_timezone=UTC"

# Change NVIDIA driver version
ansible-playbook playbooks/site.yml -e "nvidia_driver_version=545"

# Multiple variables
ansible-playbook playbooks/site.yml \
  -e "base_timezone=Europe/Paris" \
  -e "k3s_disable_traefik=false"
```

## Role Structure

### base Role

Prepares Ubuntu servers for K3S:
- `/etc/hosts` configuration with all nodes
- Timezone and locale
- Common package installation
- Swap disable
- sysctl configuration for Kubernetes
- Kernel module loading
- UFW firewall configuration

### ingress Role

Secures publicly exposed machines (DNS A entry point):
- **fail2ban**: SSH brute force protection (ban after 5 failures, 1h)
- **rkhunter**: Rootkit detection (daily scan with email alerts)
- **Strict UFW**: Only ports 22, 80, 443 open publicly, rest from private network
- **unattended-upgrades**: Automatic security updates
- **logwatch**: Daily security reports via email
- **Traefik hostPort**: K3S configuration for ports 80/443 on this node

### web Role (K3S)

Installs K3S in server (masters) or agent (workers) mode:
- K3S installation with cluster-init (first master)
- Additional masters join
- Workers join
- Helm installation
- kubeconfig configuration
- Node labeling (GPU, ingress)

### gpu Role

Installs NVIDIA drivers with production stability:
- DKMS and kernel headers installation
- NVIDIA driver installation
- Automatic update blocking (apt hold)
- unattended-upgrades configuration
- NVIDIA Container Toolkit installation
- containerd configuration for NVIDIA runtime

### nfs_server Role

Configures NFS storage with LVM:
- **Automatic disk detection**: by default, detects first unformatted disk (`lsblk`)
- LVM volume group creation
- Logical volume creation (100% of space by default)
- XFS formatting
- NFS exports configuration
- Kubernetes PV/PVC manifest generation

**NFS disk configuration:**
```yaml
# In inventory - 3 options:

nfs_server:
  hosts:
    linto-master-01:
      # Option 1 (default): automatic detection of first unformatted disk
      # nfs_disk: "auto"

      # Option 2: explicitly specify the disk
      # nfs_disk: /dev/sdb

      # Option 3: NVMe disk
      # nfs_disk: /dev/nvme1n1

      # Logical volume size (default: 100%FREE = all space)
      # nfs_lv_size: "500G"
```

## Troubleshooting

### SSH Connection Issues

```bash
# Verify SSH key
ssh -v ubuntu@192.168.1.10

# Verify permissions
chmod 600 ~/.ssh/id_ed25519
chmod 700 ~/.ssh

# Test with Ansible
ansible all -m ping -i .linto/inventory/production.yml -vvv
```

### K3S Installation Failure

```bash
# Check K3S logs on master
sudo journalctl -u k3s -f

# Verify token
sudo cat /var/lib/rancher/k3s/server/node-token

# Verify port 6443 connectivity
nc -zv 192.168.1.10 6443
```

### NVIDIA Driver Issues

```bash
# Check if driver is loaded
nvidia-smi

# Check DKMS
dkms status

# Rebuild DKMS module
sudo dkms autoinstall

# Check logs
dmesg | grep -i nvidia
```

### NFS Issues

```bash
# Verify exports on server side
showmount -e localhost

# Verify mounts on client side
mount | grep nfs

# Test manual mount
sudo mount -t nfs 192.168.1.10:/srv/nfs/linto/models /mnt/test
```

### NFS Disk Detection Issues

```bash
# See available disks and their state
lsblk -dpno NAME,TYPE,FSTYPE

# The role looks for a disk without filesystem (empty FSTYPE)
# Example output:
# /dev/sda disk ext4      <- system, ignored
# /dev/sdb disk           <- available, will be used

# If no unformatted disk is found, specify explicitly:
# nfs_disk: /dev/sdb

# Verify existing VG/LV
sudo vgs
sudo lvs
```

### fail2ban Issues (ingress)

```bash
# Check fail2ban status
sudo fail2ban-client status

# See active jails
sudo fail2ban-client status sshd

# Unban an IP
sudo fail2ban-client set sshd unbanip 1.2.3.4

# Check logs
sudo tail -f /var/log/fail2ban.log
```

### Ansible Logs

```bash
# Enable logs
export ANSIBLE_LOG_PATH=./ansible.log

# View logs
tail -f ansible.log
```

## Important Log Files

| Service | Path |
|---------|------|
| K3S Server | `/var/log/syslog` or `journalctl -u k3s` |
| K3S Agent | `/var/log/syslog` or `journalctl -u k3s-agent` |
| K3S Audit | `/var/log/k3s-audit.log` |
| NVIDIA Driver | `dmesg \| grep nvidia` |
| NFS Server | `journalctl -u nfs-kernel-server` |
| UFW | `/var/log/ufw.log` |
| fail2ban | `/var/log/fail2ban.log` |
| rkhunter | `/var/log/rkhunter.log` |

## Adding a New Role

1. Create the role structure:

```bash
mkdir -p roles/my_role/{tasks,handlers,templates,defaults}
```

2. Create `defaults/main.yml` with default variables

3. Create `tasks/main.yml` with tasks

4. Create `handlers/main.yml` for handlers

5. Add the role to the desired playbook

## Security

- No passwords in playbooks
- SSH key authentication only
- UFW firewall enabled by default
- Minimal ports open
- NVIDIA drivers and kernel blocked from automatic updates
- Ingress nodes: fail2ban, rkhunter, strict UFW, automatic security updates

## Resources

- [Ansible Documentation](https://docs.ansible.com/)
- [K3S Documentation](https://docs.k3s.io/)
- [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/)
- [NFS Linux Guide](https://wiki.archlinux.org/title/NFS)
- [fail2ban Documentation](https://www.fail2ban.org/wiki/index.php/Main_Page)
- [rkhunter Manual](https://rkhunter.sourceforge.net/)
