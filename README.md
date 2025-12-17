# MCC/MOSK Virtual Deployment

Enterprise-ready deployment automation for Mirantis Container Cloud (MCC) and Mirantis OpenStack for Kubernetes (MOSK).

**Compatible with MOSK 25.2+**

## Features

- **Fully automated deployment** - No manual approval steps required
- **Pre-flight validation** - Comprehensive checks before deployment starts
- **Resume capability** - Continue from where you left off after failures
- **Configurable topology** - Adjust compute and storage node counts
- **Storage mode selection** - Hyperconverged or dedicated Ceph storage
- **Idempotent operations** - Safe to re-run without side effects
- **Structured logging** - JSON logs with timestamps for debugging
- **State management** - Tracks deployment progress and resources
- **Auto-detection** - Automatically detects network interface and versions
- **Secret management** - Environment variable support for sensitive data
- **MiraCeph support** - Uses the new MiraCeph API for Ceph (MOSK 25.2+)

## Requirements

### Hardware

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| RAM | 256 GB | 384 GB |
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

### Step 3: Configure Deployment

Edit `config.yaml` to customize your deployment:

```bash
vi config.yaml
```

Key settings:

```yaml
# MCC version to deploy
mcc_version: "2.30.0"

# Version requirements
versions:
  mcc_minimum: "2.30.0"
  mosk_minimum: "25.2"
  openstack: "antelope"

# Storage mode: hyperconverged or dedicated
topology:
  storage_mode: hyperconverged  # or "dedicated"

  mosk_compute:
    count: 3  # Minimum 3 for Ceph quorum in hyperconverged mode

  # Only used when storage_mode is "dedicated"
  mosk_storage:
    count: 3
    resources:
      ram_mb: 16384
      vcpus: 4
      ceph_disk_count: 3

# Kubernetes settings
kubernetes:
  mosk:
    dedicated_control_plane: false  # true to separate control plane
```

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
- Ceph disk configuration consistency

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
8. MiraCeph deployment (Ceph storage)
9. OpenStack deployment

**Estimated time:** 2-4 hours depending on hardware

### Step 7: Monitor Progress

In another terminal, monitor the deployment:

```bash
# Watch deployment log
tail -f deployments/<deployment-id>/deployment.log

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

## Storage Modes

### Hyperconverged Mode (Default)

In hyperconverged mode, Ceph OSDs run on compute nodes alongside OpenStack compute services.

```yaml
topology:
  storage_mode: hyperconverged
  mosk_compute:
    count: 3  # These nodes run both compute and Ceph
    resources:
      ceph_disk_count: 3  # Number of OSD disks per node
```

**Benefits:**
- Fewer total VMs required
- Lower resource overhead
- Simpler management

### Dedicated Storage Mode

In dedicated mode, Ceph OSDs run on separate storage nodes.

```yaml
topology:
  storage_mode: dedicated
  mosk_compute:
    count: 3  # Pure compute nodes
  mosk_storage:
    count: 3  # Dedicated Ceph storage nodes
    resources:
      ram_mb: 16384
      vcpus: 4
      ceph_disk_count: 3
```

**Benefits:**
- Resource isolation between compute and storage
- Independent scaling of compute and storage
- Better performance for storage-intensive workloads

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

### Complete Reset

To completely reset and start fresh:

```bash
# Full cleanup
python3 deploy.py cleanup --full

# Remove state files
rm -rf deployments/

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

# Storage mode: hyperconverged or dedicated
topology:
  storage_mode: hyperconverged

  # MCC management cluster (fixed at 3)
  mcc:
    count: 3
    resources:
      ram_mb: 32768
      vcpus: 8

  # MOSK control plane (fixed at 3)
  mosk_control:
    count: 3
    resources:
      ram_mb: 32768
      vcpus: 8

  # MOSK compute nodes (configurable)
  mosk_compute:
    count: 3
    resources:
      ram_mb: 49152
      vcpus: 12
      ceph_disk_count: 3  # Used in hyperconverged mode

  # MOSK storage nodes (only in dedicated mode)
  mosk_storage:
    count: 3
    resources:
      ram_mb: 16384
      vcpus: 4
      ceph_disk_count: 3

# Kubernetes settings
kubernetes:
  mosk:
    dedicated_control_plane: false
    pod_cidr: "10.245.0.0/16"
    service_cidr: "10.97.0.0/16"

# Ceph storage configuration
storage:
  ceph:
    osd_devices:
      - vdb
      - vdc
      - vdd
    pool_replication_size: 2
    rgw_instances: 3
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

#### Hyperconverged Mode

| Type | Count | RAM | vCPUs | Disks | Role |
|------|-------|-----|-------|-------|------|
| MCC | 3 (fixed) | 32GB | 8 | 2 | Management cluster |
| MOSK Control | 3 (fixed) | 32GB | 8 | 2 | OpenStack control plane |
| MOSK Compute | 3+ (configurable) | 48GB | 12 | 4 | Compute + Ceph OSDs |

#### Dedicated Storage Mode

| Type | Count | RAM | vCPUs | Disks | Role |
|------|-------|-----|-------|-------|------|
| MCC | 3 (fixed) | 32GB | 8 | 2 | Management cluster |
| MOSK Control | 3 (fixed) | 32GB | 8 | 2 | OpenStack control plane + Ceph Mon/Mgr |
| MOSK Compute | 3+ (configurable) | 48GB | 12 | 1 | Compute only |
| MOSK Storage | 3+ (configurable) | 16GB | 4 | 4 | Ceph OSDs |

### Network Bridges

| Bridge | CIDR | Purpose |
|--------|------|---------|
| br-pxe | 192.168.122.0/24 | PXE boot, provisioning |
| br-lcm | 192.168.123.0/24 | Kubernetes management |
| br-others | 192.168.124.0/24 | Tenant networks |
| br-fip | 192.168.125.0/24 | Floating IPs, Ceph |

### Deployment Flow

```
1. Pre-flight Validation
   ↓
2. Infrastructure Setup (bridges, vBMC, storage)
   ↓
3. VM Creation (9+ VMs, varies by storage mode)
   ↓
4. MCC Bootstrap (Kind cluster + container-cloud bootstrap)
   ↓
5. MCC Deployment (management cluster with automatic provisioning)
   ↓
6. Bootstrap Pivot (move to management cluster)
   ↓
7. MOSK Deployment (child cluster)
   ↓
8. MiraCeph Deployment (Ceph storage via lcm.mirantis.com/v1alpha1)
   ↓
9. OpenStack Deployment
```

---

## MOSK 25.2 Changes

### MiraCeph (Replaces KaaSCephCluster)

Starting from MOSK 25.2, Ceph is deployed using **MiraCeph** instead of the deprecated KaaSCephCluster.

**Key differences:**
- API: `lcm.mirantis.com/v1alpha1` (was `kaas.mirantis.com/v1alpha1`)
- Kind: `MiraCeph` (was `KaaSCephCluster`)
- Namespace: `ceph-lcm-mirantis` (was cluster namespace)
- Device paths use `fullPath: /dev/<device>` format

### Machine Distribution Field

All Machine resources now require a `distribution` field:
```yaml
spec:
  providerSpec:
    value:
      distribution: ubuntu/jammy
```

### OpenStack SSL Configuration

SSL certificates are stored in a Kubernetes Secret and referenced from OpenStackDeployment:
```yaml
ssl:
  public_endpoints:
    ca_cert:
      value_from:
        secret_key_ref:
          name: openstack-ssl-secret
          key: ca_cert
```

---

## Monitoring Progress

### State File

Deployment state is saved to `deployments/<id>/deployment_state.json`:
- Current phase
- Completed steps
- Detected versions
- Kubeconfig paths

### Log File

```bash
# Follow deployment log
tail -f deployments/<id>/deployment.log

# Search for errors
grep -i error deployments/<id>/deployment.log
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
kubectl get miraceph -n ceph-lcm-mirantis -o wide

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
| Ceph disk mismatch | Ensure `ceph_disk_count` matches `osd_devices` list |

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

# Check MiraCeph status
kubectl -n ceph-lcm-mirantis get miraceph -o yaml

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
├── deployments/           # Deployment state and logs
│   └── <deployment-id>/
│       ├── deployment_state.json
│       └── deployment.log
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
│   ├── jinja_engine.py    # Jinja2 template engine
│   ├── certs.py           # TLS certificate generation
│   └── deployer.py        # Main orchestrator
├── templates/             # Jinja2 templates
│   ├── mcc/               # MCC cluster templates
│   │   ├── cluster.yaml.j2
│   │   ├── machines.yaml.j2
│   │   ├── baremetalhosts.yaml.j2
│   │   ├── baremetalhostprofiles.yaml.j2
│   │   ├── metallbconfig.yaml.j2
│   │   ├── ipam-objects.yaml.j2
│   │   ├── bootstrapregion.yaml.j2
│   │   └── serviceusers.yaml.j2
│   └── mosk/              # MOSK cluster templates
│       ├── namespace.yaml.j2
│       ├── cluster.yaml.j2
│       ├── bmh-control.yaml.j2
│       ├── bmh-compute.yaml.j2
│       ├── bmh-storage.yaml.j2      # Dedicated mode only
│       ├── bmhp-ctl.yaml.j2
│       ├── bmhp-cmp.yaml.j2
│       ├── bmhp-storage.yaml.j2     # Dedicated mode only
│       ├── machines-control.yaml.j2
│       ├── machines-compute.yaml.j2
│       ├── machines-storage.yaml.j2 # Dedicated mode only
│       ├── l2template.yaml.j2
│       ├── subnet.yaml.j2
│       ├── metallbconfig.yaml.j2
│       ├── miraceph.yaml.j2         # MiraCeph (MOSK 25.2+)
│       ├── osdpl-secret.yaml.j2     # OpenStack SSL secret
│       └── osdpl.yaml.j2            # OpenStackDeployment
└── certs/                 # Generated TLS certificates
```

---

## References

- [Mirantis Container Cloud Documentation](https://docs.mirantis.com/container-cloud/latest/)
- [Mirantis OpenStack for Kubernetes Documentation](https://docs.mirantis.com/mosk/25.2/)
- [MOSK Deployment Guide](https://docs.mirantis.com/mosk/25.2/deploy.html)
- [MiraCeph Configuration](https://docs.mirantis.com/mosk/25.2/deploy/deploy-managed/add-ceph.html)
- [OpenStackDeployment Reference](https://docs.mirantis.com/mosk/25.2/api/os-api.html)

## Support

For issues, please open a GitHub issue or contact Mirantis support.
