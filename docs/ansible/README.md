# LinTO Ansible Infrastructure

Ansible infrastructure for deploying a K3S cluster optimized for LinTO AI workloads (GPU transcription, NFS storage for models and media).

## How to Use This Template

**IMPORTANT:** The `ansible/` folder is a reusable template. Do not duplicate it for each environment.

### Recommended Workflow

1. **One template, multiple inventories:**
   ```bash
   # Inventories are stored in .linto/inventory/ (gitignored)
   .linto/inventory/
     staging.yml      # Your staging inventory
     production.yml   # Your production inventory

   # The ansible template remains in the repo
   ansible/
     roles/           # Common to all environments
     playbooks/       # Common to all environments
   ```

2. **Create one inventory per environment:**
   ```bash
   # Create the inventory directory
   mkdir -p .linto/inventory

   # Copy the example template
   cp docs/ansible/inventory-example.yml .linto/inventory/production.yml

   # Edit with real production IPs
   vim .linto/inventory/production.yml
   ```

3. **Deploy by environment:**
   ```bash
   # Staging
   ansible-playbook ansible/playbooks/site.yml -i .linto/inventory/staging.yml

   # Production
   ansible-playbook ansible/playbooks/site.yml -i .linto/inventory/production.yml
   ```

### Inventory Storage

Environment-specific inventories are stored in `.linto/inventory/` which is gitignored, while the reusable roles and playbooks remain in version control.

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
# Create inventory directory
mkdir -p .linto/inventory

# Copy and edit the inventory
cp docs/ansible/inventory-example.yml .linto/inventory/production.yml
vim .linto/inventory/production.yml
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
ansible-playbook ansible/playbooks/site.yml -i .linto/inventory/production.yml

# Or step by step
ansible-playbook ansible/playbooks/base.yml -i .linto/inventory/production.yml       # Base configuration
ansible-playbook ansible/playbooks/storage.yml -i .linto/inventory/production.yml    # NFS storage
ansible-playbook ansible/playbooks/k3s-cluster.yml -i .linto/inventory/production.yml # K3S cluster
```

## Useful Commands

### Pre-deployment Check (dry-run)

```bash
# Check mode (simulation without modifications)
ansible-playbook ansible/playbooks/site.yml -i .linto/inventory/production.yml --check

# Check mode with diff (see changes)
ansible-playbook ansible/playbooks/site.yml -i .linto/inventory/production.yml --check --diff
```

### Selective Deployment

```bash
# Single node
ansible-playbook ansible/playbooks/base.yml -i .linto/inventory/production.yml --limit linto-master-01

# Group of nodes
ansible-playbook ansible/playbooks/k3s-cluster.yml -i .linto/inventory/production.yml --limit workers

# With specific tags
ansible-playbook ansible/playbooks/site.yml -i .linto/inventory/production.yml --tags base
ansible-playbook ansible/playbooks/site.yml -i .linto/inventory/production.yml --tags k3s,gpu
ansible-playbook ansible/playbooks/site.yml -i .linto/inventory/production.yml --tags ingress
ansible-playbook ansible/playbooks/site.yml -i .linto/inventory/production.yml --tags nfs
```

### Debug and Verbosity

```bash
# Verbose mode
ansible-playbook ansible/playbooks/site.yml -i .linto/inventory/production.yml -v

# Very verbose mode (debug)
ansible-playbook ansible/playbooks/site.yml -i .linto/inventory/production.yml -vvv

# Display host variables
ansible linto-master-01 -i .linto/inventory/production.yml -m debug -a "var=hostvars[inventory_hostname]"
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
