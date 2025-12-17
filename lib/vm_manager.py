"""
Virtual Machine Manager Module

Handles VM creation, vBMC registration, and cleanup.
Supports configurable compute node counts.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from .config import Config, VMTopology
from .logger import DeploymentLogger
from .state import StateManager, DeploymentPhase
from .utils import (
    CommandError,
    get_vm_list,
    run_command,
    run_command_output,
    vbmc_exists,
    vm_exists,
)


@dataclass
class VMDefinition:
    """Virtual machine definition."""
    name: str
    mac_address: str
    vbmc_port: int
    ram_mb: int
    vcpus: int
    disks: List[Dict[str, any]]  # List of disk definitions
    role: str  # mcc, mosk-ctl, mosk-cmp
    index: int


class VMManager:
    """
    Manages virtual machines for MCC/MOSK deployment.

    Handles:
    - VM creation with configurable resources
    - vBMC registration for IPMI simulation
    - VM cleanup
    - Power management
    """

    def __init__(
        self,
        config: Config,
        state: StateManager,
        log: Optional[DeploymentLogger] = None,
    ):
        """
        Initialize VM manager.

        Args:
            config: Deployment configuration
            state: State manager
            log: Optional deployment logger
        """
        self.config = config
        self.state = state
        self.log = log or DeploymentLogger("vm_manager")
        self._kvm_node_ip: Optional[str] = None

    @property
    def kvm_node_ip(self) -> str:
        """Get KVM node IP (vBMC address).

        This is the IP where vBMC is listening, which should be the br-pxe gateway
        since that's accessible from both the host and the Kind cluster network.
        """
        if self._kvm_node_ip is None:
            # Priority: 1. State, 2. br-pxe gateway from config, 3. hosts.txt fallback
            ip = self.state.get_resource("kvm_node_ip")
            if ip:
                self._kvm_node_ip = ip
            else:
                # Use br-pxe gateway - this is where vBMC listens
                pxe_bridge = self.config.bridges.get("pxe")
                if pxe_bridge:
                    self._kvm_node_ip = pxe_bridge.gateway
            if not self._kvm_node_ip:
                # Fallback to hosts.txt for backwards compatibility
                hosts_file = Path(self.config.base_dir) / "hosts.txt"
                if hosts_file.exists():
                    self._kvm_node_ip = hosts_file.read_text().strip()
            if not self._kvm_node_ip:
                raise ValueError("KVM node IP not found. Check config or run infrastructure setup.")
        return self._kvm_node_ip

    def generate_vm_definitions(self) -> List[VMDefinition]:
        """
        Generate VM definitions based on configuration.

        Returns:
            List of VM definitions
        """
        vms = []

        # MCC VMs (fixed at 3)
        mcc = self.config.mcc_topology
        for i in range(1, mcc.count + 1):
            vms.append(VMDefinition(
                name=f"mcc-{i}{i}",
                mac_address=f"{mcc.mac_prefix}:{i}{i}",
                vbmc_port=mcc.vbmc_port_start + i - 1,
                ram_mb=mcc.resources.ram_mb,
                vcpus=mcc.resources.vcpus,
                disks=[
                    {"size_gb": mcc.resources.disk_root_gb, "name": "disk1"},
                    {"size_gb": mcc.resources.disk_local_gb, "name": "disk2"},
                ],
                role="mcc",
                index=i,
            ))

        # MOSK Control VMs (fixed at 3)
        mosk_ctl = self.config.mosk_control_topology
        for i in range(1, mosk_ctl.count + 1):
            vms.append(VMDefinition(
                name=f"mosk-ctl-{i}{i}",
                mac_address=f"{mosk_ctl.mac_prefix}:{i}{i}",
                vbmc_port=mosk_ctl.vbmc_port_start + i - 1,
                ram_mb=mosk_ctl.resources.ram_mb,
                vcpus=mosk_ctl.resources.vcpus,
                disks=[
                    {"size_gb": mosk_ctl.resources.disk_root_gb, "name": "disk1"},
                    {"size_gb": mosk_ctl.resources.disk_local_gb, "name": "disk2"},
                ],
                role="mosk-ctl",
                index=i,
            ))

        # MOSK Compute VMs (configurable count)
        mosk_cmp = self.config.mosk_compute_topology
        for i in range(1, mosk_cmp.count + 1):
            # Generate disks for compute nodes (including Ceph disks)
            disks = [
                {"size_gb": mosk_cmp.resources.disk_root_gb, "name": "disk1"},
                {"size_gb": mosk_cmp.resources.disk_local_gb, "name": "disk2"},
            ]
            # Add Ceph disks
            for j in range(mosk_cmp.resources.ceph_disk_count):
                disks.append({
                    "size_gb": mosk_cmp.resources.disk_ceph_gb,
                    "name": f"disk{j + 3}",
                })

            # For 2-digit MAC, pad single digits
            mac_suffix = f"{i:02d}" if i < 10 else f"{i}{i}" if i < 10 else f"{i:02d}"
            if mosk_cmp.count <= 9:
                mac_suffix = f"{i}{i}"

            vms.append(VMDefinition(
                name=f"mosk-cmp-{i}{i}" if i < 10 else f"mosk-cmp-{i:02d}",
                mac_address=f"{mosk_cmp.mac_prefix}:{mac_suffix}",
                vbmc_port=mosk_cmp.vbmc_port_start + i - 1,
                ram_mb=mosk_cmp.resources.ram_mb,
                vcpus=mosk_cmp.resources.vcpus,
                disks=disks,
                role="mosk-cmp",
                index=i,
            ))

        return vms

    def create_all_vms(self) -> None:
        """Create all VMs based on configuration."""
        self.log.phase_start("vm_creation", "Creating virtual machines")
        self.state.set_phase(DeploymentPhase.VM_CREATION)

        vms = self.generate_vm_definitions()
        self.log.progress(f"Creating {len(vms)} virtual machines")

        try:
            for vm in vms:
                step_name = f"create_vm_{vm.name}"
                if self.state.should_run_step(step_name):
                    self._create_vm(vm)

            # Start vBMC for all VMs
            if self.state.should_run_step("start_vbmc"):
                self._start_all_vbmc(vms)

            # Power off all VMs
            if self.state.should_run_step("power_off_vms"):
                self._power_off_all(vms)

            self.log.phase_complete("vm_creation")

        except Exception as e:
            self.log.phase_failed("vm_creation", str(e))
            raise

    def _create_vm(self, vm: VMDefinition) -> None:
        """
        Create a single VM.

        Args:
            vm: VM definition
        """
        step_name = f"create_vm_{vm.name}"
        self.log.step_start(step_name, f"Creating VM: {vm.name}")
        self.state.start_step(step_name)

        try:
            # Check if VM already exists
            if vm_exists(vm.name):
                self.log.progress(f"VM {vm.name} already exists, skipping creation")
            else:
                # Build disk arguments
                disk_args = []
                for disk in vm.disks:
                    disk_path = f"{self.config.images_path}/{vm.name}-{disk['name']}.qcow2"
                    disk_args.append(
                        f"--disk size={disk['size_gb']},path={disk_path},bus=sata,format=qcow2"
                    )

                # Build virt-install command - use local connection (qemu:///system)
                # instead of SSH connection since we're running directly on the KVM node
                cmd = f"""sudo virt-install \\
                    --connect qemu:///system \\
                    --virt-type=kvm \\
                    --name={vm.name} \\
                    --os-variant=ubuntu20.04 \\
                    --ram={vm.ram_mb} \\
                    --vcpus={vm.vcpus} \\
                    {' '.join(disk_args)} \\
                    --network bridge=br-pxe,model=virtio,mac={vm.mac_address} \\
                    --network bridge=br-lcm,model=virtio \\
                    --network bridge=br-others,model=virtio \\
                    --network bridge=br-fip,model=virtio \\
                    --graphics vnc \\
                    --boot network,hd \\
                    --noautoconsole"""

                self.log.progress(f"Running virt-install for {vm.name}")
                run_command(cmd, timeout=300)

            # Register with vBMC
            self._register_vbmc(vm)

            self.state.complete_step(step_name, {
                "name": vm.name,
                "mac": vm.mac_address,
                "vbmc_port": vm.vbmc_port,
            })
            self.log.step_complete(step_name)
            self.log.resource_created("vm", vm.name)

        except Exception as e:
            self.state.fail_step(step_name, str(e))
            self.log.step_failed(step_name, str(e))
            raise

    def _register_vbmc(self, vm: VMDefinition) -> None:
        """
        Register VM with vBMC.

        Args:
            vm: VM definition
        """
        if vbmc_exists(vm.name):
            self.log.progress(f"vBMC entry for {vm.name} already exists")
            return

        # Get vbmc binary path from state or find it
        vbmc_bin = self.state.get_resource("vbmc_bin")
        if not vbmc_bin:
            # Try to find vbmc in standard locations
            try:
                vbmc_bin = run_command_output("which vbmc", timeout=10).strip()
            except Exception:
                # Fallback to common paths
                for path in ["/usr/local/bin/vbmc", "/opt/vbmc/bin/vbmc"]:
                    if os.path.exists(path):
                        vbmc_bin = path
                        break

        if not vbmc_bin:
            raise RuntimeError("vbmc binary not found")

        cmd = (
            f"sudo {vbmc_bin} add {vm.name} "
            f"--port {vm.vbmc_port} "
            f"--username {self.config.bmc_username} "
            f"--password {self.config.bmc_password} "
            f"--address {self.kvm_node_ip}"
        )
        run_command(cmd)
        self.log.progress(f"Registered vBMC for {vm.name} on port {vm.vbmc_port}")

    def _start_all_vbmc(self, vms: List[VMDefinition]) -> None:
        """
        Start vBMC for all VMs.

        Args:
            vms: List of VM definitions
        """
        step_name = "start_vbmc"
        self.log.step_start(step_name, "Starting vBMC services")
        self.state.start_step(step_name)

        try:
            # Get vbmc binary path from state or find it
            vbmc_bin = self.state.get_resource("vbmc_bin")
            if not vbmc_bin:
                try:
                    vbmc_bin = run_command_output("which vbmc", timeout=10).strip()
                except Exception:
                    for path in ["/usr/local/bin/vbmc", "/opt/vbmc/bin/vbmc"]:
                        if os.path.exists(path):
                            vbmc_bin = path
                            break

            if not vbmc_bin:
                raise RuntimeError("vbmc binary not found")

            for vm in vms:
                try:
                    run_command(f"sudo {vbmc_bin} start {vm.name}", check=False)
                except Exception:
                    pass  # May already be running

            # Verify
            output = run_command_output(f"{vbmc_bin} list")
            self.log.progress(f"vBMC status:\n{output}")

            self.state.complete_step(step_name)
            self.log.step_complete(step_name)

        except Exception as e:
            self.state.fail_step(step_name, str(e))
            self.log.step_failed(step_name, str(e))
            raise

    def _power_off_all(self, vms: List[VMDefinition]) -> None:
        """
        Power off all VMs using IPMI.

        Args:
            vms: List of VM definitions
        """
        step_name = "power_off_vms"
        self.log.step_start(step_name, "Powering off VMs")
        self.state.start_step(step_name)

        try:
            for vm in vms:
                self.log.progress(f"Powering off {vm.name}")
                try:
                    cmd = (
                        f"ipmitool -I lanplus -H {self.kvm_node_ip} "
                        f"-U {self.config.bmc_username} -P {self.config.bmc_password} "
                        f"-p {vm.vbmc_port} power off"
                    )
                    run_command(cmd, check=False, timeout=30)
                except Exception as e:
                    self.log.warning(f"Could not power off {vm.name}: {e}")

            self.state.complete_step(step_name)
            self.log.step_complete(step_name)

        except Exception as e:
            self.state.fail_step(step_name, str(e))
            self.log.step_failed(step_name, str(e))
            raise

    def cleanup_all_vms(self) -> None:
        """Clean up all VMs."""
        self.log.phase_start("vm_cleanup", "Cleaning up virtual machines")

        vms = self.generate_vm_definitions()

        for vm in vms:
            self._cleanup_vm(vm)

        self.log.phase_complete("vm_cleanup")

    def _cleanup_vm(self, vm: VMDefinition) -> None:
        """
        Clean up a single VM.

        Args:
            vm: VM definition
        """
        self.log.progress(f"Cleaning up VM: {vm.name}")

        # Stop and delete from vBMC
        try:
            run_command(f"sudo /opt/vbmc/bin/vbmc stop {vm.name}", check=False)
            run_command(f"sudo /opt/vbmc/bin/vbmc delete {vm.name}", check=False)
        except Exception:
            pass

        # Destroy and undefine VM
        try:
            run_command(f"sudo virsh destroy {vm.name}", check=False)
            run_command(f"sudo virsh undefine {vm.name}", check=False)
        except Exception:
            pass

        # Delete disk files
        for disk in vm.disks:
            disk_path = f"{self.config.images_path}/{vm.name}-{disk['name']}.qcow2"
            try:
                run_command(f"sudo rm -f {disk_path}", check=False)
            except Exception:
                pass

        self.log.progress(f"Cleaned up VM: {vm.name}")

    def verify_vms(self) -> Dict[str, bool]:
        """
        Verify all VMs exist and are accessible.

        Returns:
            Dictionary of VM name to status
        """
        vms = self.generate_vm_definitions()
        status = {}

        for vm in vms:
            exists = vm_exists(vm.name)
            status[vm.name] = exists
            if exists:
                self.log.progress(f"VM {vm.name}: OK")
            else:
                self.log.warning(f"VM {vm.name}: NOT FOUND")

        return status

    def get_vm_info(self, role: Optional[str] = None) -> List[Dict[str, any]]:
        """
        Get information about VMs.

        Args:
            role: Optional role filter (mcc, mosk-ctl, mosk-cmp)

        Returns:
            List of VM information dictionaries
        """
        vms = self.generate_vm_definitions()
        if role:
            vms = [v for v in vms if v.role == role]

        info = []
        for vm in vms:
            info.append({
                "name": vm.name,
                "role": vm.role,
                "index": vm.index,
                "mac_address": vm.mac_address,
                "vbmc_port": vm.vbmc_port,
                "bmc_address": f"{self.kvm_node_ip}:{vm.vbmc_port}",
            })

        return info
