# MCC/MOSK Virtual Deployment

Enterprise-ready deployment automation for Mirantis Container Cloud (MCC) and Mirantis OpenStack for Kubernetes (MOSK).

## Features

- **Fully automated deployment** - No manual approval steps required
- **Pre-flight validation** - Comprehensive checks before deployment starts
- **Resume capability** - Continue from where you left off after failures
- **Configurable topology** - Adjust compute node count as needed
- **Idempotent operations** - Safe to re-run without side effects
- **Structured logging** - JSON logs with timestamps for debugging
- **State management** - Tracks deployment progress and resources
- **Auto-detection** - Automatically detects network interface and versions
- **Secret management** - Environment variable support for sensitive data

## Requirements

### Hardware

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| RAM | 256 GB | 342 GB |
| CPU | 32 cores | 48+ cores |
| Storage | 1 TB | 1.5 TB |

### Software

- Ubuntu 20.04, 22.04, or 24.04
- Python 3.8+
- Root/sudo access
- Internet connectivity

### License

- Valid `mirantis.lic` file from Mirantis

---

## Step-by-Step Usage Guide

### Step 1: Clone Repository

```bash
git clone https://github.com/reddydodda/mcc-virtual.git
cd mcc-virtual/
```

### Step 2: Place License File

Copy your Mirantis license file to the repository root:

```bash
cp /path/to/mirantis.lic .
```

### Step 3: Configure Deployment (Optional)

Edit `config.yaml` to customize your deployment:

```bash
vi config.yaml
```

Key settings:
- `mcc_version` - MCC version to deploy (e.g., "2.30.0")
- `topology.mosk_compute.count` - Number of compute nodes (minimum 3)
- `primary_interface` - Network interface (auto-detected if not set)

### Step 4: Set Credentials (Optional)

Set environment variables for custom passwords:

```bash
export MCC_BMC_PASSWORD="your-bmc-password"
export MCC_ROOT_PASSWORD="your-root-password"
export MCC_SERVICE_PASSWORD="your-service-password"
```

Default values are used if not set (see Environment Variables section).

### Step 5: Validate Environment

Run pre-flight checks to ensure your system meets requirements:

```bash
python3 deploy.py validate
```

This checks:
- Hardware resources (RAM, CPU, disk)
- Required software packages
- Network configuration
- License file presence

### Step 6: Run Deployment

Start the full deployment:

```bash
python3 deploy.py deploy
```

The deployment runs through these phases:
1. Pre-flight validation
2. Infrastructure setup (bridges, vBMC, storage pools)
3. VM creation (9+ VMs)
4. MCC bootstrap (Kind cluster)
5. MCC deployment (management cluster)
6. Bootstrap pivot
7. MOSK deployment (child cluster)
8. Ceph deployment (storage)
9. OpenStack deployment

**Estimated time:** 2-4 hours depending on hardware

### Step 7: Monitor Progress

In another terminal, monitor the deployment:

```bash
# Watch deployment log
tail -f deployment.log

# Check deployment status
python3 deploy.py status
```

### Step 8: Resume After Failure (If Needed)

If deployment fails, check the error and resume:

```bash
# Check current state
python3 deploy.py status

# Resume from last checkpoint
python3 deploy.py deploy --resume
```

---

## Command Reference

### Deployment Commands

| Command | Description |
|---------|-------------|
| `python3 deploy.py deploy` | Full deployment from scratch |
| `python3 deploy.py deploy --resume` | Resume from last successful phase |
| `python3 deploy.py deploy --skip-validation` | Skip pre-flight checks |

### Status Commands

| Command | Description |
|---------|-------------|
| `python3 deploy.py status` | Show current deployment status |
| `python3 deploy.py config` | Show current configuration |
| `python3 deploy.py validate` | Run pre-flight validation only |

### Individual Phase Commands

| Command | Description |
|---------|-------------|
| `python3 deploy.py setup-infra` | Setup infrastructure only |
| `python3 deploy.py create-vms` | Create VMs only |

---

## Cleanup Guide

### Quick Cleanup (VMs Only)

Remove VMs while keeping infrastructure (bridges, vBMC):

```bash
python3 deploy.py cleanup
```

This removes:
- All deployment VMs (mcc-*, mosk-*)
- vBMC registrations for VMs
- VM disk images

This keeps:
- Network bridges (br-pxe, br-lcm, br-others, br-fip)
- vBMC service and virtual environment
- Storage pools
- Kind cluster (if running)

### Full Cleanup

Remove everything including infrastructure:

```bash
python3 deploy.py cleanup --full
```

This removes:
- All deployment VMs
- All vBMC registrations
- Network bridges
- Storage pools
- Kind cluster
- Bootstrap directory (kaas-bootstrap)

### Manual Cleanup Steps

If automated cleanup fails or you need granular control:

#### 1. Remove VMs

```bash
# List all VMs
virsh list --all

# Destroy and undefine each VM
for vm in $(virsh list --all --name | grep -E "^(mcc|mosk)-"); do
    virsh destroy $vm 2>/dev/null
    virsh undefine $vm --remove-all-storage
done
```

#### 2. Remove vBMC Registrations

```bash
# List vBMC entries
/opt/vbmc/bin/vbmc list

# Delete each entry
for vm in $(virsh list --all --name | grep -E "^(mcc|mosk)-"); do
    /opt/vbmc/bin/vbmc delete $vm 2>/dev/null
done

# Stop vBMC service (optional)
systemctl stop vbmcd
```

#### 3. Remove Network Bridges

```bash
# List networks
virsh net-list --all

# Remove deployment networks
for net in br-pxe br-lcm br-others br-fip; do
    virsh net-destroy $net 2>/dev/null
    virsh net-undefine $net 2>/dev/null
done
```

#### 4. Remove Storage Pools

```bash
# List storage pools
virsh pool-list --all

# Remove deployment pools
for pool in mcc-images mosk-images; do
    virsh pool-destroy $pool 2>/dev/null
    virsh pool-undefine $pool 2>/dev/null
done

# Remove disk images
rm -rf /var/lib/libvirt/images/mcc-*
rm -rf /var/lib/libvirt/images/mosk-*
```

#### 5. Remove Kind Cluster

```bash
kind delete cluster --name clusterapi
rm -f ~/.kube/kind-config-clusterapi
```

#### 6. Remove Bootstrap Directory

```bash
rm -rf kaas-bootstrap/
```

#### 7. Reset State

```bash
rm -f deployment_state.json
rm -f deployment.log
```

### Complete Reset

To completely reset and start fresh:

```bash
# Full cleanup
python3 deploy.py cleanup --full

# Remove state files
rm -f deployment_state.json deployment.log

# Remove generated configs
rm -f kubeconfig-kaas-mgmt mosk.kubeconfig keycloak.yaml

# Start fresh deployment
python3 deploy.py deploy
```

---

## Configuration

### config.yaml

```yaml
# MCC version to deploy (auto-detected if not specified)
mcc_version: "2.30.0"

# Version requirements
versions:
  mcc_minimum: "2.30.0"
  mosk_minimum: "25.2"
  openstack: "antelope"

# VM topology (MCC and MOSK control are fixed at 3)
topology:
  mosk_compute:
    count: 3  # Configurable: minimum 3 for Ceph quorum
    resources:
      ram_mb: 49152
      vcpus: 12
```

### Environment Variables

| Variable | Description | Default |
|----------|-------------|---------|
| `MCC_BMC_USERNAME` | BMC username | root |
| `MCC_BMC_PASSWORD` | BMC password | admin123 |
| `MCC_ROOT_PASSWORD` | VM root password | r00tme |
| `MCC_SERVICE_PASSWORD` | Service user password | Mirantis@123 |
| `MCC_LICENSE_PATH` | License file path | mirantis.lic |

---

## Architecture

### VM Topology

| Type | Count | RAM | vCPUs | Disks | Role |
|------|-------|-----|-------|-------|------|
| MCC | 3 (fixed) | 32GB | 8 | 2 | Management cluster |
| MOSK Control | 3 (fixed) | 32GB | 8 | 2 | OpenStack control plane |
| MOSK Compute | 3+ (configurable) | 48GB | 12 | 4 | Compute + Ceph storage |

### Network Bridges

| Bridge | CIDR | Purpose |
|--------|------|---------|
| br-pxe | 192.168.122.0/24 | PXE boot, provisioning |
| br-lcm | 192.168.123.0/24 | Kubernetes management |
| br-others | 192.168.124.0/24 | Tenant networks |
| br-fip | 192.168.125.0/24 | Floating IPs |

### Deployment Flow

```
1. Pre-flight Validation
   ↓
2. Infrastructure Setup (bridges, vBMC, storage)
   ↓
3. VM Creation (9+ VMs)
   ↓
4. MCC Bootstrap (Kind cluster + container-cloud bootstrap)
   ↓
5. MCC Deployment (management cluster with automatic provisioning)
   ↓
6. Bootstrap Pivot (move to management cluster)
   ↓
7. MOSK Deployment (child cluster)
   ↓
8. Ceph Deployment (storage)
   ↓
9. OpenStack Deployment
```

---

## Monitoring Progress

### State File

Deployment state is saved to `deployment_state.json`:
- Current phase
- Completed steps
- Detected versions
- Kubeconfig paths

### Log File

```bash
# Follow deployment log
tail -f deployment.log

# Search for errors
grep -i error deployment.log
```

### Kubernetes Resources

```bash
# During Kind bootstrap
export KUBECONFIG=~/.kube/kind-config-clusterapi
kubectl get bmh -o wide
kubectl get lcmmachines -o wide

# After pivot to MCC management
export KUBECONFIG=kubeconfig-kaas-mgmt
kubectl get bmh -o wide
kubectl get lcmmachines -o wide
kubectl get cluster -o wide

# MOSK cluster resources
kubectl get bmh -n mosk -o wide
kubectl get kcc -n mosk -o wide

# OpenStack resources
export KUBECONFIG=mosk.kubeconfig
kubectl -n openstack get osdplst -o wide
```

---

## Troubleshooting

### Common Issues

| Issue | Solution |
|-------|----------|
| Disk space error | Ensure 1+ TB available on /var/lib/libvirt |
| Memory error | Ensure 256+ GB RAM available |
| License not found | Place `mirantis.lic` in repo root |
| Network interface not found | Set `primary_interface` in config.yaml |
| VM fails to boot | Check vBMC logs: `journalctl -u vbmcd` |
| Deployment stuck | Check `python3 deploy.py status` and logs |

### Manual Debugging

```bash
# Check VMs
virsh list --all

# Check vBMC
/opt/vbmc/bin/vbmc list

# Check bridges
virsh net-list --all

# Check Kind cluster
kind get clusters
kubectl --kubeconfig ~/.kube/kind-config-clusterapi get nodes

# Check LCM agent status
kubectl get lcmmachines -o wide
kubectl get machine -o json | jq '.items[].status.providerStatus.conditions'

# Check pod logs
kubectl logs -n kaas deployment/lcm-controller -f
```

---

## Post-Deployment

### Access MCC Dashboard

1. Get Keycloak credentials:
   ```bash
   cat keycloak.yaml
   ```

2. Get dashboard URL:
   ```bash
   export KUBECONFIG=kubeconfig-kaas-mgmt
   kubectl get svc -A | grep ui
   ```

### Access OpenStack

1. Set kubeconfig:
   ```bash
   export KUBECONFIG=mosk.kubeconfig
   ```

2. Get Keystone endpoint:
   ```bash
   kubectl -n openstack get svc keystone-api
   ```

3. Get admin credentials:
   ```bash
   kubectl -n openstack get secret keystone-keystone-admin -o jsonpath='{.data.OS_PASSWORD}' | base64 -d
   ```

4. Configure OpenStack CLI:
   ```bash
   export OS_AUTH_URL=http://<keystone-ip>:5000/v3
   export OS_USERNAME=admin
   export OS_PASSWORD=<password-from-above>
   export OS_PROJECT_NAME=admin
   export OS_USER_DOMAIN_NAME=Default
   export OS_PROJECT_DOMAIN_NAME=Default
   openstack server list
   ```

---

## File Structure

```
mcc-virtual/
├── deploy.py              # Main entry point
├── config.yaml            # Configuration file
├── mirantis.lic           # License file (you provide)
├── deployment_state.json  # State file (generated)
├── deployment.log         # Log file (generated)
├── lib/                   # Python modules
│   ├── __init__.py
│   ├── config.py          # Configuration management
│   ├── state.py           # State management
│   ├── logger.py          # Logging
│   ├── utils.py           # Utilities
│   ├── validation.py      # Pre-flight validation
│   ├── infrastructure.py  # Infrastructure setup
│   ├── vm_manager.py      # VM management
│   ├── templates.py       # Template generation
│   └── deployer.py        # Main orchestrator
├── templates/             # Jinja2 templates
│   ├── mcc/
│   └── mosk/
├── mcc/                   # MCC manifest templates
├── mosk/                  # MOSK manifest templates
└── legacy/                # Deprecated shell scripts
```

---

## References

- [Mirantis Container Cloud Documentation](https://docs.mirantis.com/container-cloud/latest/)
- [Mirantis OpenStack for Kubernetes Documentation](https://docs.mirantis.com/mosk/25.2/)
- [MOSK Deployment Guide](https://docs.mirantis.com/mosk/latest/deploy/provision-bm/deploy-mgmt-v2/bootstrapv2-setup.html)

## Support

For issues, please open a GitHub issue or contact Mirantis support.
