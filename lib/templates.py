"""
Template Generator Module

Generates Kubernetes manifests for MCC and MOSK deployment.
Uses Jinja2 templating with TLS certificate generation.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .config import Config
from .logger import DeploymentLogger
from .state import StateManager
from .vm_manager import VMManager
from .jinja_engine import get_template_engine
from .certs import CertificateGenerator, CertificateInfo


class TemplateGenerator:
    """
    Generates deployment templates for MCC/MOSK.

    Creates manifests dynamically based on configuration using Jinja2 templates.
    Supports configurable compute nodes, TLS certificates, and version requirements.
    """

    def __init__(
        self,
        config: Config,
        state: StateManager,
        vm_manager: VMManager,
        log: Optional[DeploymentLogger] = None,
    ):
        """
        Initialize template generator.

        Args:
            config: Deployment configuration
            state: State manager
            vm_manager: VM manager
            log: Optional deployment logger
        """
        self.config = config
        self.state = state
        self.vm_manager = vm_manager
        self.log = log or DeploymentLogger("templates")
        self._kvm_node_ip: Optional[str] = None
        self._certs: Optional[CertificateInfo] = None

        # Initialize template engine
        template_dir = Path(self.config.base_dir) / "templates"
        if template_dir.exists():
            self.engine = get_template_engine(str(template_dir))
        else:
            self.engine = None

    @property
    def kvm_node_ip(self) -> str:
        """Get KVM node IP (vBMC address).

        This is the IP where vBMC is listening, which should be the br-pxe gateway
        since that's accessible from both the host and the Kind cluster network.
        """
        if self._kvm_node_ip is None:
            # Priority: 1. State, 2. br-pxe gateway from config, 3. hosts.txt fallback
            self._kvm_node_ip = self.state.get_resource("kvm_node_ip")
            if not self._kvm_node_ip:
                # Use br-pxe gateway - this is where vBMC listens
                pxe_bridge = self.config.bridges.get("pxe")
                if pxe_bridge:
                    self._kvm_node_ip = pxe_bridge.gateway
            if not self._kvm_node_ip:
                # Fallback to hosts.txt for backwards compatibility
                hosts_file = Path(self.config.base_dir) / "hosts.txt"
                if hosts_file.exists():
                    self._kvm_node_ip = hosts_file.read_text().strip()
        return self._kvm_node_ip

    @property
    def certificates(self) -> CertificateInfo:
        """Get or generate TLS certificates."""
        if self._certs is None:
            certs_dir = Path(self.config.base_dir) / "certs"
            generator = CertificateGenerator(output_dir=str(certs_dir))

            # Get domain from config
            domain = self.config.get_raw("tls.domain", "it.just.works")
            api_ips = self.config.get_raw("tls.api_ips", None)

            self._certs = generator.generate_mcc_mosk_certs(
                domain=domain,
                api_ips=api_ips,
            )
            self.log.progress(f"Generated TLS certificates for domain: {domain}")

        return self._certs

    def build_mcc_context(self) -> Dict[str, Any]:
        """
        Build template context for MCC templates.

        Returns:
            Dictionary of template variables
        """
        mcc_vms = self.vm_manager.get_vm_info(role="mcc")

        # Build node list
        mcc_nodes = []
        for vm in mcc_vms:
            mcc_nodes.append({
                "index": vm["index"],
                "name": vm["name"],
                "mac_address": vm["mac_address"],
                "vbmc_port": vm["vbmc_port"],
                "ip_address": vm.get("ip_address", f"192.168.122.{10 + vm['index']}"),
            })

        # Get versions (detected during deployment, stored in state)
        mcc_kaas_release = self.state.get_version("mcc_kaas_release") or ""
        mcc_cluster_release = self.state.get_version("mcc_cluster_release") or ""

        context = {
            # Node information
            "mcc_nodes": mcc_nodes,
            "kvm_node_ip": self.kvm_node_ip,

            # Credentials
            "bmc_username": self.config.bmc_username,
            "bmc_password": self.config.bmc_password,
            "root_password": self.config.root_password,
            "service_password": self.config.service_password,

            # Versions
            "mcc_kaas_release": mcc_kaas_release,
            "mcc_cluster_release": mcc_cluster_release,

            # Cluster settings
            "mcc_cluster_name": self.config.mcc_cluster_name,

            # Network configuration (defaults match config.yaml)
            "mcc_pod_cidr": self.config.get_raw("kubernetes.mcc.pod_cidr", "10.233.64.0/18"),
            "mcc_service_cidr": self.config.get_raw("kubernetes.mcc.service_cidr", "10.233.0.0/18"),
            "mcc_node_cidr": self.config.get_raw("network.bridges.lcm.cidr", "192.168.123.0/24"),
            "mcc_lcm_cidr": self.config.get_raw("network.bridges.lcm.cidr", "192.168.123.0/24"),
            "mcc_lcm_gateway": self.config.get_raw("network.bridges.lcm.gateway", "192.168.123.1"),
            "mcc_lcm_range_start": self.config.get_raw("network.mcc.lcm_range_start", "192.168.123.10"),
            "mcc_lcm_range_end": self.config.get_raw("network.mcc.lcm_range_end", "192.168.123.100"),
            "mcc_metallb_range_start": self.config.get_raw("network.mcc.metallb_range_start", "192.168.123.200"),
            "mcc_metallb_range_end": self.config.get_raw("network.mcc.metallb_range_end", "192.168.123.220"),

            # DNS
            "dns_servers": self.config.dns_servers,

            # Storage
            "mcc_system_disk": self.config.get_raw("vm.mcc.system_disk", "/dev/vda"),

            # Monitoring/StackLight configuration
            "stacklight_elasticsearch_size": self.config.get_raw("openstack.monitoring.elasticsearch_size", "30Gi"),
            "stacklight_prometheus_size": self.config.get_raw("openstack.monitoring.prometheus_size", "16Gi"),

            # TLS certificates
            "tls_ca_cert": self.certificates.ca_cert,
            "tls_server_cert": self.certificates.server_cert,
            "tls_server_key": self.certificates.server_key,
            "tls_ca_cert_b64": self.certificates.ca_cert_b64,
            "tls_server_cert_b64": self.certificates.server_cert_b64,
            "tls_server_key_b64": self.certificates.server_key_b64,
        }

        return context

    def build_mosk_context(self) -> Dict[str, Any]:
        """
        Build template context for MOSK templates.

        Returns:
            Dictionary of template variables
        """
        mosk_ctl_vms = self.vm_manager.get_vm_info(role="mosk-ctl")
        mosk_cmp_vms = self.vm_manager.get_vm_info(role="mosk-cmp")
        mosk_storage_vms = self.vm_manager.get_vm_info(role="mosk-storage")

        # Build control node list
        mosk_control_nodes = []
        for vm in mosk_ctl_vms:
            mosk_control_nodes.append({
                "index": vm["index"],
                "name": vm["name"],
                "mac_address": vm["mac_address"],
                "vbmc_port": vm["vbmc_port"],
            })

        # Build compute node list
        mosk_compute_nodes = []
        for vm in mosk_cmp_vms:
            mosk_compute_nodes.append({
                "index": vm["index"],
                "name": vm["name"],
                "mac_address": vm["mac_address"],
                "vbmc_port": vm["vbmc_port"],
            })

        # Build storage node list (only in dedicated mode)
        mosk_storage_nodes = []
        for vm in mosk_storage_vms:
            mosk_storage_nodes.append({
                "index": vm["index"],
                "name": vm["name"],
                "mac_address": vm["mac_address"],
                "vbmc_port": vm["vbmc_port"],
            })

        # Get versions (detected during deployment, stored in state)
        mosk_release = self.state.get_version("mosk_release") or ""
        openstack_version = self.config.get_raw("openstack.version", "antelope")

        context = {
            # Namespace
            "mosk_namespace": self.config.mosk_namespace,

            # Cluster settings
            "dedicated_control_plane": self.config.mosk_dedicated_control_plane,

            # Storage mode
            "storage_mode": self.config.storage_mode,
            "is_hyperconverged": self.config.is_hyperconverged,

            # Node information
            "mosk_control_nodes": mosk_control_nodes,
            "mosk_compute_nodes": mosk_compute_nodes,
            "mosk_storage_nodes": mosk_storage_nodes,
            "kvm_node_ip": self.kvm_node_ip,

            # Credentials
            "bmc_username": self.config.bmc_username,
            "bmc_password": self.config.bmc_password,

            # Versions
            "mosk_release": mosk_release,
            "openstack_version": openstack_version,
            "openstack_preset": self.config.get_raw("openstack.preset", "compute"),
            "openstack_size": self.config.get_raw("openstack.size", "small"),

            # Network configuration
            "mosk_pod_cidr": self.config.get_raw("network.mosk.pod_cidr", "10.245.0.0/16"),
            "mosk_service_cidr": self.config.get_raw("network.mosk.service_cidr", "10.97.0.0/16"),
            "mosk_lcm_cidr": self.config.get_raw("network.mosk.lcm_cidr", "192.168.123.0/24"),
            "mosk_lcm_gateway": self.config.get_raw("network.mosk.lcm_gateway", "192.168.123.1"),
            "mosk_lcm_range_start": self.config.get_raw("network.mosk.lcm_range_start", "192.168.123.10"),
            "mosk_lcm_range_end": self.config.get_raw("network.mosk.lcm_range_end", "192.168.123.100"),
            "mosk_pxe_cidr": self.config.get_raw("network.mosk.pxe_cidr", "192.168.124.0/24"),
            "mosk_pxe_range_start": self.config.get_raw("network.mosk.pxe_range_start", "192.168.124.10"),
            "mosk_pxe_range_end": self.config.get_raw("network.mosk.pxe_range_end", "192.168.124.100"),
            "mosk_storage_cidr": self.config.get_raw("network.mosk.storage_cidr", "192.168.125.0/24"),
            "mosk_storage_range_start": self.config.get_raw("network.mosk.storage_range_start", "192.168.125.10"),
            "mosk_storage_range_end": self.config.get_raw("network.mosk.storage_range_end", "192.168.125.100"),
            "mosk_metallb_range_start": self.config.get_raw("network.mosk.metallb_range_start", "192.168.123.200"),
            "mosk_metallb_range_end": self.config.get_raw("network.mosk.metallb_range_end", "192.168.123.220"),
            "mosk_metallb_internal_start": self.config.get_raw("network.mosk.metallb_internal_start", "192.168.123.230"),
            "mosk_metallb_internal_end": self.config.get_raw("network.mosk.metallb_internal_end", "192.168.123.240"),

            # DNS
            "dns_servers": self.config.get_raw("network.dns_servers", ["8.8.8.8", "8.8.4.4"]),

            # Ceph configuration
            "ceph_public_network": self.config.get_raw("storage.ceph.public_network", "192.168.125.0/24"),
            "ceph_cluster_network": self.config.get_raw("storage.ceph.cluster_network", "192.168.125.0/24"),
            "ceph_osd_devices": self.config.ceph_osd_devices,
            "ceph_pool_replication_size": self.config.get_raw("storage.ceph.pool_replication_size", 2),
            "ceph_rgw_instances": self.config.get_raw("storage.ceph.rgw_instances", 3),
            "ceph_rgw_store_name": self.config.get_raw("storage.ceph.rgw_store_name", "rgw-store"),
            "ceph_public_domain": self.config.get_raw("storage.ceph.public_domain", "ceph.it.just.works"),
            "ceph_pools": [
                {"name": pool.name, "role": pool.role, "default": pool.default, "size": pool.size}
                for pool in self.config.ceph_pools
            ],

            # OpenStack configuration
            "osdpl_public_domain": self.config.get_raw("openstack.public_domain", "it.just.works"),
            "openstack_services": self.config.get_raw(
                "openstack.services",
                ["barbican", "cinder", "glance", "heat", "horizon", "keystone", "neutron", "nova", "octavia", "placement", "tempest"]
            ),
            "openstack_dvr_enabled": self.config.get_raw("openstack.dvr_enabled", True),
            "openstack_baremetal_enabled": self.config.get_raw("openstack.baremetal_enabled", False),
            "openstack_db_backup_enabled": self.config.get_raw("openstack.db_backup_enabled", True),

            # Nova configuration
            "nova_cpu_allocation_ratio": self.config.get_raw("openstack.nova.cpu_allocation_ratio", 4.0),
            "nova_ram_allocation_ratio": self.config.get_raw("openstack.nova.ram_allocation_ratio", 1.0),
            "nova_disk_allocation_ratio": self.config.get_raw("openstack.nova.disk_allocation_ratio", 1.0),
            "nova_live_migration_interface": self.config.get_raw("openstack.nova.live_migration_interface", "k8s-lcm"),

            # Neutron configuration
            "neutron_dns_domain": self.config.get_raw("openstack.neutron.dns_domain", "openstacklocal"),
            "neutron_global_mtu": self.config.get_raw("openstack.neutron.global_mtu", 1500),
            "neutron_flat_networks": self.config.get_raw("openstack.neutron.flat_networks", "physnet1"),
            "neutron_vlan_ranges": self.config.get_raw("openstack.neutron.vlan_ranges", "physnet1:100:200"),
            "neutron_tunnel_interface": self.config.get_raw("openstack.neutron.tunnel_interface", "k8s-others"),

            # Octavia configuration
            "octavia_amp_flavor_id": self.config.get_raw("openstack.octavia.amp_flavor_id", "65"),
            "octavia_lb_network_name": self.config.get_raw("openstack.octavia.lb_network_name", "lb-mgmt-net"),
            "octavia_lb_cidr": self.config.get_raw("openstack.octavia.lb_cidr", "192.168.200.0/24"),

            # StackLight configuration
            "stacklight_enabled": self.config.get_raw("monitoring.stacklight.enabled", True),
            "stacklight_version": self.config.get_raw("monitoring.stacklight.version", "3.0"),
            "stacklight_log_retention_days": self.config.get_raw("monitoring.stacklight.log_retention_days", 7),
            "stacklight_metric_retention_days": self.config.get_raw("monitoring.stacklight.metric_retention_days", 15),

            # TLS certificates
            "tls_ca_cert": self.certificates.ca_cert,
            "tls_server_cert": self.certificates.server_cert,
            "tls_server_key": self.certificates.server_key,
            "tls_ca_cert_b64": self.certificates.ca_cert_b64,
            "tls_server_cert_b64": self.certificates.server_cert_b64,
            "tls_server_key_b64": self.certificates.server_key_b64,
        }

        return context

    def render_mcc_templates(self, output_dir: str) -> Dict[str, str]:
        """
        Render all MCC templates.

        Args:
            output_dir: Output directory for rendered templates

        Returns:
            Dictionary of template name to output path
        """
        if not self.engine:
            raise RuntimeError("Template engine not initialized")

        self.log.step_start("render_mcc", "Rendering MCC templates")

        context = self.build_mcc_context()
        rendered = {}

        # List of MCC templates to render
        mcc_templates = [
            ("mcc/cluster.yaml.j2", "01-cluster/cluster.yaml"),
            ("mcc/baremetalhosts.yaml.j2", "02-bmh/baremetalhosts.yaml"),
            ("mcc/machines.yaml.j2", "03-machines/machines.yaml"),
            ("mcc/metallbconfig.yaml.j2", "04-metallb/metallbconfig.yaml"),
            ("mcc/ipam-objects.yaml.j2", "05-ipam/ipam-objects.yaml"),
            ("mcc/bootstrapregion.yaml.j2", "06-region/bootstrapregion.yaml"),
            ("mcc/serviceusers.yaml.j2", "07-users/serviceusers.yaml"),
            ("mcc/baremetalhostprofiles.yaml.j2", "08-profiles/baremetalhostprofiles.yaml"),
        ]

        for template_name, output_name in mcc_templates:
            try:
                output_path = Path(output_dir) / output_name
                self.engine.render_to_file(template_name, str(output_path), context)
                rendered[template_name] = str(output_path)
                self.log.progress(f"Rendered: {output_name}")
            except Exception as e:
                self.log.warning(f"Failed to render {template_name}: {e}")

        self.log.step_complete("render_mcc")
        return rendered

    def render_mosk_templates(self, output_dir: str) -> Dict[str, str]:
        """
        Render all MOSK templates.

        Args:
            output_dir: Output directory for rendered templates

        Returns:
            Dictionary of template name to output path
        """
        if not self.engine:
            raise RuntimeError("Template engine not initialized")

        self.log.step_start("render_mosk", "Rendering MOSK templates")

        context = self.build_mosk_context()
        rendered = {}

        # Base MOSK templates (always rendered)
        # Output paths are designed to match deployer expectations
        mosk_templates = [
            ("mosk/namespace.yaml.j2", "01-namespace.yaml"),
            ("mosk/metallbconfig.yaml.j2", "02-metallbconfig.yaml"),
            ("mosk/bmh-control.yaml.j2", "03-bmh/01-bmh-control.yaml"),
            ("mosk/bmh-compute.yaml.j2", "03-bmh/02-bmh-compute.yaml"),
            ("mosk/cluster.yaml.j2", "04-cluster.yaml"),
            ("mosk/bmhp-ctl.yaml.j2", "05-bmhp-ctl.yaml"),
            ("mosk/bmhp-cmp.yaml.j2", "05-bmhp-cmp.yaml"),
            ("mosk/l2template.yaml.j2", "06-l2template.yaml"),
            ("mosk/subnet.yaml.j2", "07-subnet.yaml"),
            ("mosk/machines-control.yaml.j2", "08-machines/01-machines-control.yaml"),
            ("mosk/machines-compute.yaml.j2", "08-machines/02-machines-compute.yaml"),
            # OSDPL templates (applied after MOSK cluster is ready)
            ("mosk/osdpl-secret.yaml.j2", "10-osdpl/osdpl-secret.yaml"),
            ("mosk/osdpl.yaml.j2", "10-osdpl/osdpl.yaml"),
        ]

        # Add storage node templates only in dedicated mode
        if not self.config.is_hyperconverged:
            mosk_templates.extend([
                ("mosk/bmh-storage.yaml.j2", "03-bmh/03-bmh-storage.yaml"),
                ("mosk/bmhp-storage.yaml.j2", "05-bmhp-storage.yaml"),
                ("mosk/machines-storage.yaml.j2", "08-machines/03-machines-storage.yaml"),
            ])
            self.log.progress("Including dedicated storage node templates")

        for template_name, output_name in mosk_templates:
            try:
                output_path = Path(output_dir) / output_name
                self.engine.render_to_file(template_name, str(output_path), context)
                rendered[template_name] = str(output_path)
                self.log.progress(f"Rendered: {output_name}")
            except Exception as e:
                self.log.warning(f"Failed to render {template_name}: {e}")

        self.log.step_complete("render_mosk")
        return rendered

    def generate_all_templates(self, mcc_output: str, mosk_output: str) -> Dict[str, Dict[str, str]]:
        """
        Generate all templates for both MCC and MOSK.

        Args:
            mcc_output: Output directory for MCC templates
            mosk_output: Output directory for MOSK templates

        Returns:
            Dictionary with 'mcc' and 'mosk' keys containing rendered files
        """
        result = {
            "mcc": self.render_mcc_templates(mcc_output),
            "mosk": self.render_mosk_templates(mosk_output),
        }

        self.log.progress(f"Generated {len(result['mcc'])} MCC templates")
        self.log.progress(f"Generated {len(result['mosk'])} MOSK templates")

        return result

    # ========================================================================
    # Legacy methods for backward compatibility
    # ========================================================================

    def generate_mcc_bmh_credentials(self) -> List[Dict[str, Any]]:
        """Generate BareMetalHostCredential resources for MCC."""
        credentials = []
        mcc_vms = self.vm_manager.get_vm_info(role="mcc")

        for vm in mcc_vms:
            credentials.append({
                "apiVersion": "kaas.mirantis.com/v1alpha1",
                "kind": "BareMetalHostCredential",
                "metadata": {
                    "name": f"master-{vm['index'] - 1}-bmc-credentials",
                    "namespace": "default",
                    "labels": {
                        "kaas.mirantis.com/provider": "baremetal",
                    },
                },
                "spec": {
                    "username": self.config.bmc_username,
                    "password": {
                        "value": self.config.bmc_password,
                    },
                },
            })

        return credentials

    def generate_mcc_bmh(self) -> List[Dict[str, Any]]:
        """Generate BareMetalHost resources for MCC."""
        hosts = []
        mcc_vms = self.vm_manager.get_vm_info(role="mcc")

        for vm in mcc_vms:
            hosts.append({
                "apiVersion": "metal3.io/v1alpha1",
                "kind": "BareMetalHost",
                "metadata": {
                    "name": f"master-{vm['index'] - 1}",
                    "labels": {
                        "kaas.mirantis.com/provider": "baremetal",
                        "baremetal": f"hw-master-{vm['index'] - 1}",
                    },
                    "annotations": {
                        "kaas.mirantis.com/baremetalhost-credentials-name": f"master-{vm['index'] - 1}-bmc-credentials",
                    },
                },
                "spec": {
                    "bootMode": "UEFI",
                    "online": True,
                    "bootMACAddress": vm["mac_address"],
                    "bmc": {
                        "address": f"{self.kvm_node_ip}:{vm['vbmc_port']}",
                        "credentialsName": "",
                    },
                },
            })

        return hosts

    def generate_mosk_bmh_credentials(self, namespace: str = "mosk") -> List[Dict[str, Any]]:
        """Generate BareMetalHostCredential resources for MOSK."""
        credentials = []

        # Control nodes
        for vm in self.vm_manager.get_vm_info(role="mosk-ctl"):
            cred_name = f"bm-mosk-ctl-{vm['index']:02d}-credentials"
            credentials.append({
                "apiVersion": "kaas.mirantis.com/v1alpha1",
                "kind": "BareMetalHostCredential",
                "metadata": {
                    "name": cred_name,
                    "namespace": namespace,
                    "labels": {
                        "kaas.mirantis.com/provider": "baremetal",
                        "kaas.mirantis.com/region": "region-one",
                    },
                },
                "spec": {
                    "username": self.config.bmc_username,
                    "password": {
                        "value": self.config.bmc_password,
                    },
                },
            })

        # Compute nodes
        for vm in self.vm_manager.get_vm_info(role="mosk-cmp"):
            cred_name = f"bm-mosk-cmp-{vm['index']:02d}-credentials"
            credentials.append({
                "apiVersion": "kaas.mirantis.com/v1alpha1",
                "kind": "BareMetalHostCredential",
                "metadata": {
                    "name": cred_name,
                    "namespace": namespace,
                    "labels": {
                        "kaas.mirantis.com/provider": "baremetal",
                        "kaas.mirantis.com/region": "region-one",
                    },
                },
                "spec": {
                    "username": self.config.bmc_username,
                    "password": {
                        "value": self.config.bmc_password,
                    },
                },
            })

        return credentials

    def write_manifest(self, resources: List[Dict[str, Any]], output_path: str) -> str:
        """
        Write resources to a YAML manifest file.

        Args:
            resources: List of Kubernetes resources
            output_path: Output file path

        Returns:
            Path to written file
        """
        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)

        with open(output, 'w') as f:
            for i, resource in enumerate(resources):
                if i > 0:
                    f.write("---\n")
                yaml.dump(resource, f, default_flow_style=False, allow_unicode=True)

        self.log.progress(f"Wrote manifest: {output_path}")
        return str(output)

    def update_templates_with_config(self) -> None:
        """Update template files with configuration values."""
        self.log.step_start("update_templates", "Updating templates with configuration")

        # Get versions from state or detect
        mcc_kaas_release = self.state.get_version("mcc_kaas_release")
        mcc_cluster_release = self.state.get_version("mcc_cluster_release")
        mosk_release = self.state.get_version("mosk_release")

        replacements = {
            "SET_KVM_ADDRESS": self.kvm_node_ip,
            "SET_NAMESPACE": self.config.mosk_namespace,
            "KVM_NODE_IP": self.kvm_node_ip,
        }

        if mcc_kaas_release:
            replacements["SET_MCC_KAAS_RELEASE"] = mcc_kaas_release
        if mcc_cluster_release:
            replacements["SET_MCC_CLUSTER_RELEASE"] = mcc_cluster_release
        if mosk_release:
            replacements["SET_MOSK_RELEASE"] = mosk_release

        # Update MCC templates
        mcc_dir = Path(self.config.base_dir) / "mcc"
        if mcc_dir.exists():
            for template in mcc_dir.glob("*.template"):
                self._update_file(template, replacements)

        # Update MOSK templates
        mosk_dir = Path(self.config.base_dir) / "mosk"
        if mosk_dir.exists():
            for yaml_file in mosk_dir.rglob("*.yaml"):
                self._update_file(yaml_file, replacements)

        self.log.step_complete("update_templates")

    def generate_miraceph_manifest(self, output_dir: str) -> str:
        """
        Generate MiraCeph manifest with dynamic TLS certificates.

        MiraCeph replaces deprecated KaaSCephCluster for MOSK 25.2+.
        This should be called AFTER MOSK cluster is ready.

        Args:
            output_dir: Output directory for the manifest

        Returns:
            Path to the generated manifest file
        """
        if not self.engine:
            raise RuntimeError("Template engine not initialized")

        self.log.step_start("generate_miraceph", "Generating MiraCeph manifest")

        # Get MOSK context with TLS certificates
        context = self.build_mosk_context()

        # Render the template
        output_path = Path(output_dir) / "09-miraceph.yaml"
        output_path.parent.mkdir(parents=True, exist_ok=True)

        self.engine.render_to_file(
            "mosk/miraceph.yaml.j2",
            str(output_path),
            context
        )

        self.log.progress(f"Generated MiraCeph manifest: {output_path}")
        self.log.step_complete("generate_miraceph")

        return str(output_path)

    def _update_file(self, filepath: Path, replacements: Dict[str, str]) -> None:
        """
        Update a file with replacements.

        Args:
            filepath: File path
            replacements: Dictionary of replacements
        """
        content = filepath.read_text()
        modified = False

        for old, new in replacements.items():
            if old in content:
                content = content.replace(old, new)
                modified = True

        if modified:
            filepath.write_text(content)
            self.log.progress(f"Updated: {filepath}")
