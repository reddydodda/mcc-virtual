"""
Configuration Management Module

Handles loading, validation, and access to deployment configuration.
Supports environment variable overrides for sensitive data.
"""

import os
import yaml
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any
from pathlib import Path


@dataclass
class NetworkBridge:
    """Network bridge configuration."""
    name: str
    cidr: str
    gateway: str
    dhcp_range: Optional[Dict[str, str]] = None


@dataclass
class VMResources:
    """Virtual machine resource configuration."""
    ram_mb: int
    vcpus: int
    disk_root_gb: int
    disk_local_gb: int
    disk_ceph_gb: int = 0
    ceph_disk_count: int = 0


@dataclass
class VMTopology:
    """VM topology configuration."""
    count: int
    resources: VMResources
    mac_prefix: str
    vbmc_port_start: int


@dataclass
class CephPool:
    """Ceph pool configuration."""
    name: str
    role: str
    size: int
    default: bool = False


class Config:
    """
    Configuration manager for MCC/MOSK deployment.

    Loads configuration from YAML file with support for
    environment variable overrides.
    """

    # Environment variable mappings for sensitive data
    ENV_MAPPINGS = {
        "MCC_BMC_USERNAME": "bmc.username",
        "MCC_BMC_PASSWORD": "bmc.password",
        "MCC_ROOT_PASSWORD": "vm.root_password",
        "MCC_SERVICE_PASSWORD": "service.password",
        "MCC_LICENSE_PATH": "bootstrap.license_file",
    }

    # Default values for secrets (if not provided via env vars)
    DEFAULT_BMC_USERNAME = "root"
    DEFAULT_BMC_PASSWORD = "admin123"
    DEFAULT_ROOT_PASSWORD = "r00tme"
    DEFAULT_SERVICE_PASSWORD = "Mirantis@123"

    def __init__(self, config_path: str = "config.yaml"):
        """
        Initialize configuration from YAML file.

        Args:
            config_path: Path to configuration file
        """
        self.config_path = Path(config_path)
        self.base_dir = self.config_path.parent
        self._raw_config: Dict[str, Any] = {}
        self._load_config()
        self._apply_env_overrides()
        self._validate_config()

    def _load_config(self) -> None:
        """Load configuration from YAML file."""
        if not self.config_path.exists():
            raise FileNotFoundError(f"Configuration file not found: {self.config_path}")

        with open(self.config_path, 'r') as f:
            self._raw_config = yaml.safe_load(f)

    def _apply_env_overrides(self) -> None:
        """Apply environment variable overrides for sensitive data."""
        # BMC credentials
        self._bmc_username = os.environ.get("MCC_BMC_USERNAME", self.DEFAULT_BMC_USERNAME)
        self._bmc_password = os.environ.get("MCC_BMC_PASSWORD", self.DEFAULT_BMC_PASSWORD)

        # Root password for VMs
        self._root_password = os.environ.get("MCC_ROOT_PASSWORD", self.DEFAULT_ROOT_PASSWORD)

        # Service user password
        self._service_password = os.environ.get("MCC_SERVICE_PASSWORD", self.DEFAULT_SERVICE_PASSWORD)

        # License file path override
        license_env = os.environ.get("MCC_LICENSE_PATH")
        if license_env:
            self._raw_config.setdefault("bootstrap", {})["license_file"] = license_env

    def _validate_config(self) -> None:
        """Validate configuration completeness and consistency."""
        required_sections = ["deployment", "network", "topology", "kubernetes"]
        for section in required_sections:
            if section not in self._raw_config:
                raise ValueError(f"Missing required configuration section: {section}")

        # Validate MCC count is fixed at 3
        mcc_count = self._raw_config.get("topology", {}).get("mcc", {}).get("count", 0)
        if mcc_count != 3:
            raise ValueError(f"MCC control plane must have exactly 3 nodes, got {mcc_count}")

        # Validate MOSK control count is fixed at 3
        mosk_ctl_count = self._raw_config.get("topology", {}).get("mosk_control", {}).get("count", 0)
        if mosk_ctl_count != 3:
            raise ValueError(f"MOSK control plane must have exactly 3 nodes, got {mosk_ctl_count}")

        # Validate MOSK compute count is at least 3 for Ceph quorum
        mosk_cmp_count = self._raw_config.get("topology", {}).get("mosk_compute", {}).get("count", 0)
        if mosk_cmp_count < 3:
            raise ValueError(f"MOSK compute nodes must be at least 3 for Ceph, got {mosk_cmp_count}")

    # ==========================================================================
    # Property accessors for configuration values
    # ==========================================================================

    @property
    def deployment_name(self) -> str:
        """Get deployment name."""
        return self._raw_config.get("deployment", {}).get("name", "mcc-mosk-virtual")

    @property
    def environment(self) -> str:
        """Get deployment environment."""
        return self._raw_config.get("deployment", {}).get("environment", "development")

    # Secrets (from environment variables)
    @property
    def bmc_username(self) -> str:
        """Get BMC username."""
        return self._bmc_username

    @property
    def bmc_password(self) -> str:
        """Get BMC password."""
        return self._bmc_password

    @property
    def root_password(self) -> str:
        """Get VM root password."""
        return self._root_password

    @property
    def service_password(self) -> str:
        """Get service user password."""
        return self._service_password

    # Version requirements
    @property
    def mcc_version(self) -> str:
        """Get target MCC version to deploy (optional, defaults to latest)."""
        return self._raw_config.get("versions", {}).get("mcc_version", "")

    @property
    def mcc_minimum_version(self) -> str:
        """Get minimum MCC version."""
        return self._raw_config.get("versions", {}).get("mcc_minimum", "2.30.0")

    @property
    def mosk_minimum_version(self) -> str:
        """Get minimum MOSK version."""
        return self._raw_config.get("versions", {}).get("mosk_minimum", "25.2")

    @property
    def openstack_version(self) -> str:
        """Get OpenStack version."""
        return self._raw_config.get("versions", {}).get("openstack", "antelope")

    # Network configuration
    @property
    def primary_interface(self) -> str:
        """Get primary network interface."""
        return self._raw_config.get("network", {}).get("primary_interface", "auto")

    @property
    def bridges(self) -> Dict[str, NetworkBridge]:
        """Get network bridge configurations."""
        bridges_config = self._raw_config.get("network", {}).get("bridges", {})
        result = {}
        for name, cfg in bridges_config.items():
            result[name] = NetworkBridge(
                name=cfg.get("name", f"br-{name}"),
                cidr=cfg.get("cidr", ""),
                gateway=cfg.get("gateway", ""),
                dhcp_range=cfg.get("dhcp_range"),
            )
        return result

    @property
    def dns_servers(self) -> List[str]:
        """Get DNS servers."""
        return self._raw_config.get("network", {}).get("dns_servers", ["8.8.8.8", "1.1.1.1"])

    @property
    def mcc_api_endpoint(self) -> str:
        """Get MCC API endpoint IP."""
        return self._raw_config.get("network", {}).get("api_endpoints", {}).get("mcc", "192.168.123.10")

    @property
    def mosk_api_endpoint(self) -> str:
        """Get MOSK API endpoint IP."""
        return self._raw_config.get("network", {}).get("api_endpoints", {}).get("mosk", "192.168.123.100")

    # Storage configuration
    @property
    def images_path(self) -> str:
        """Get VM images storage path."""
        return self._raw_config.get("storage", {}).get("images_path", "/var/lib/libvirt/images_new")

    @property
    def auto_mount_storage(self) -> bool:
        """Check if auto-mount storage is enabled."""
        return self._raw_config.get("storage", {}).get("auto_mount", True)

    @property
    def ceph_osd_devices(self) -> List[str]:
        """Get Ceph OSD devices."""
        return self._raw_config.get("storage", {}).get("ceph", {}).get("osd_devices", ["sdb", "sdc", "sdd"])

    @property
    def ceph_pools(self) -> List[CephPool]:
        """Get Ceph pool configurations."""
        pools_config = self._raw_config.get("storage", {}).get("ceph", {}).get("pools", [])
        return [
            CephPool(
                name=p.get("name", ""),
                role=p.get("role", ""),
                size=p.get("size", 2),
                default=p.get("default", False),
            )
            for p in pools_config
        ]

    # VM topology
    @property
    def mcc_topology(self) -> VMTopology:
        """Get MCC VM topology."""
        cfg = self._raw_config.get("topology", {}).get("mcc", {})
        resources_cfg = cfg.get("resources", {})
        return VMTopology(
            count=cfg.get("count", 3),
            resources=VMResources(
                ram_mb=resources_cfg.get("ram_mb", 32768),
                vcpus=resources_cfg.get("vcpus", 8),
                disk_root_gb=resources_cfg.get("disk_root_gb", 100),
                disk_local_gb=resources_cfg.get("disk_local_gb", 50),
            ),
            mac_prefix=cfg.get("mac_prefix", "52:54:00:c5:91"),
            vbmc_port_start=cfg.get("vbmc_port_start", 6231),
        )

    @property
    def mosk_control_topology(self) -> VMTopology:
        """Get MOSK control plane VM topology."""
        cfg = self._raw_config.get("topology", {}).get("mosk_control", {})
        resources_cfg = cfg.get("resources", {})
        return VMTopology(
            count=cfg.get("count", 3),
            resources=VMResources(
                ram_mb=resources_cfg.get("ram_mb", 32768),
                vcpus=resources_cfg.get("vcpus", 8),
                disk_root_gb=resources_cfg.get("disk_root_gb", 100),
                disk_local_gb=resources_cfg.get("disk_local_gb", 50),
            ),
            mac_prefix=cfg.get("mac_prefix", "52:54:00:c5:92"),
            vbmc_port_start=cfg.get("vbmc_port_start", 6241),
        )

    @property
    def mosk_compute_topology(self) -> VMTopology:
        """Get MOSK compute VM topology."""
        cfg = self._raw_config.get("topology", {}).get("mosk_compute", {})
        resources_cfg = cfg.get("resources", {})
        return VMTopology(
            count=cfg.get("count", 3),
            resources=VMResources(
                ram_mb=resources_cfg.get("ram_mb", 49152),
                vcpus=resources_cfg.get("vcpus", 12),
                disk_root_gb=resources_cfg.get("disk_root_gb", 100),
                disk_local_gb=resources_cfg.get("disk_local_gb", 50),
                disk_ceph_gb=resources_cfg.get("disk_ceph_gb", 50),
                ceph_disk_count=resources_cfg.get("ceph_disk_count", 3),
            ),
            mac_prefix=cfg.get("mac_prefix", "52:54:00:c5:93"),
            vbmc_port_start=cfg.get("vbmc_port_start", 6251),
        )

    @property
    def total_vm_count(self) -> int:
        """Get total number of VMs."""
        return (
            self.mcc_topology.count +
            self.mosk_control_topology.count +
            self.mosk_compute_topology.count
        )

    # Kubernetes configuration
    @property
    def mcc_cluster_name(self) -> str:
        """Get MCC cluster name."""
        return self._raw_config.get("kubernetes", {}).get("mcc", {}).get("cluster_name", "kaas-mgmt")

    @property
    def mosk_namespace(self) -> str:
        """Get MOSK namespace."""
        return self._raw_config.get("kubernetes", {}).get("mosk", {}).get("namespace", "mosk")

    # Bootstrap configuration
    @property
    def bootstrap_pxe_ip(self) -> str:
        """Get bootstrap PXE IP."""
        return self._raw_config.get("bootstrap", {}).get("pxe_ip", "192.168.122.2")

    @property
    def bootstrap_pxe_mask(self) -> str:
        """Get bootstrap PXE mask."""
        return self._raw_config.get("bootstrap", {}).get("pxe_mask", "24")

    @property
    def bootstrap_pxe_bridge(self) -> str:
        """Get bootstrap PXE bridge."""
        return self._raw_config.get("bootstrap", {}).get("pxe_bridge", "br-pxe")

    @property
    def license_file(self) -> str:
        """Get license file path."""
        return self._raw_config.get("bootstrap", {}).get("license_file", "mirantis.lic")

    # Timeouts
    @property
    def timeout_bmh_available(self) -> int:
        """Get BMH available timeout."""
        return self._raw_config.get("timeouts", {}).get("bmh_available", 3600)

    @property
    def timeout_bmh_provisioned(self) -> int:
        """Get BMH provisioned timeout."""
        return self._raw_config.get("timeouts", {}).get("bmh_provisioned", 7200)

    @property
    def timeout_machine_ready(self) -> int:
        """Get machine ready timeout."""
        return self._raw_config.get("timeouts", {}).get("machine_ready", 3600)

    @property
    def timeout_cluster_ready(self) -> int:
        """Get cluster ready timeout."""
        return self._raw_config.get("timeouts", {}).get("cluster_ready", 1800)

    @property
    def timeout_ceph_healthy(self) -> int:
        """Get Ceph healthy timeout."""
        return self._raw_config.get("timeouts", {}).get("ceph_healthy", 3600)

    @property
    def timeout_osdpl_applied(self) -> int:
        """Get OSDPL applied timeout."""
        return self._raw_config.get("timeouts", {}).get("osdpl_applied", 7200)

    @property
    def poll_interval(self) -> int:
        """Get polling interval."""
        return self._raw_config.get("timeouts", {}).get("poll_interval", 30)

    @property
    def max_retries(self) -> int:
        """Get maximum retries."""
        return self._raw_config.get("timeouts", {}).get("max_retries", 3)

    # Logging
    @property
    def log_level(self) -> str:
        """Get log level."""
        return self._raw_config.get("logging", {}).get("level", "INFO")

    @property
    def log_file(self) -> str:
        """Get log file path."""
        return self._raw_config.get("logging", {}).get("file", "deployment.log")

    @property
    def log_format(self) -> str:
        """Get log format."""
        return self._raw_config.get("logging", {}).get("format", "json")

    # State management
    @property
    def state_file(self) -> str:
        """Get state file path."""
        return self._raw_config.get("state", {}).get("file", "deployment_state.json")

    # OpenStack configuration
    @property
    def openstack_preset(self) -> str:
        """Get OpenStack preset."""
        return self._raw_config.get("openstack", {}).get("preset", "compute")

    @property
    def openstack_size(self) -> str:
        """Get OpenStack size."""
        return self._raw_config.get("openstack", {}).get("size", "tiny")

    @property
    def openstack_dvr_enabled(self) -> bool:
        """Check if DVR is enabled."""
        return self._raw_config.get("openstack", {}).get("features", {}).get("dvr_enabled", True)

    # Raw config access for templates
    def get_raw(self, path: str, default: Any = None) -> Any:
        """
        Get raw configuration value by dot-separated path.

        Args:
            path: Dot-separated path (e.g., "network.bridges.pxe.cidr")
            default: Default value if path not found

        Returns:
            Configuration value or default
        """
        keys = path.split(".")
        value = self._raw_config
        for key in keys:
            if isinstance(value, dict) and key in value:
                value = value[key]
            else:
                return default
        return value

    def to_template_vars(self) -> Dict[str, Any]:
        """
        Convert configuration to template variables dictionary.

        Returns:
            Dictionary of template variables
        """
        return {
            # Deployment info
            "deployment_name": self.deployment_name,
            "environment": self.environment,

            # Secrets
            "bmc_username": self.bmc_username,
            "bmc_password": self.bmc_password,
            "root_password": self.root_password,
            "service_password": self.service_password,

            # Versions
            "mcc_minimum_version": self.mcc_minimum_version,
            "mosk_minimum_version": self.mosk_minimum_version,
            "openstack_version": self.openstack_version,

            # Network
            "dns_servers": self.dns_servers,
            "mcc_api_endpoint": self.mcc_api_endpoint,
            "mosk_api_endpoint": self.mosk_api_endpoint,

            # Storage
            "ceph_osd_devices": self.ceph_osd_devices,
            "ceph_pools": [
                {"name": p.name, "role": p.role, "size": p.size, "default": p.default}
                for p in self.ceph_pools
            ],

            # Kubernetes
            "mcc_cluster_name": self.mcc_cluster_name,
            "mosk_namespace": self.mosk_namespace,

            # OpenStack
            "openstack_preset": self.openstack_preset,
            "openstack_size": self.openstack_size,
            "openstack_dvr_enabled": self.openstack_dvr_enabled,
        }
