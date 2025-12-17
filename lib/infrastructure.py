"""
Infrastructure Setup Module

Handles network bridge creation, vBMC setup, storage mounting,
and other infrastructure prerequisites.
"""

import os
import re
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

from .config import Config, NetworkBridge
from .logger import DeploymentLogger
from .state import StateManager, DeploymentPhase
from .utils import (
    CommandError,
    bridge_exists,
    detect_primary_interface,
    get_interface_ip,
    run_command,
    run_command_output,
)


class InfrastructureManager:
    """
    Manages infrastructure setup for MCC/MOSK deployment.

    Handles:
    - Network bridge creation
    - vBMC installation and configuration
    - Storage mounting
    - SSH key setup
    - System configuration
    """

    def __init__(
        self,
        config: Config,
        state: StateManager,
        log: Optional[DeploymentLogger] = None,
    ):
        """
        Initialize infrastructure manager.

        Args:
            config: Deployment configuration
            state: State manager
            log: Optional deployment logger
        """
        self.config = config
        self.state = state
        self.log = log or DeploymentLogger("infrastructure")

    def setup_all(self) -> None:
        """Run all infrastructure setup steps."""
        self.log.phase_start("infrastructure_setup", "Setting up infrastructure")
        self.state.set_phase(DeploymentPhase.INFRASTRUCTURE_SETUP)

        try:
            # Configure kernel modules and sysctl (must be early)
            if self.state.should_run_step("configure_kernel"):
                self._configure_kernel()

            # Install required packages
            if self.state.should_run_step("install_packages"):
                self._install_packages()

            # Install Docker
            if self.state.should_run_step("install_docker"):
                self._install_docker()

            # Detect and save primary interface IP
            if self.state.should_run_step("detect_network"):
                self._detect_network()

            # Setup network bridges
            if self.state.should_run_step("setup_bridges"):
                self._setup_bridges()

            # Mount storage
            if self.state.should_run_step("mount_storage"):
                self._mount_storage()

            # Install vBMC
            if self.state.should_run_step("install_vbmc"):
                self._install_vbmc()

            # Setup SSH keys
            if self.state.should_run_step("setup_ssh"):
                self._setup_ssh()

            # Configure firewall
            if self.state.should_run_step("configure_firewall"):
                self._configure_firewall()

            self.log.phase_complete("infrastructure_setup")

        except Exception as e:
            self.log.phase_failed("infrastructure_setup", str(e))
            raise

    def _configure_kernel(self) -> None:
        """Configure kernel modules and sysctl settings required for Kubernetes networking."""
        step_name = "configure_kernel"
        self.log.step_start(step_name, "Configuring kernel modules and sysctl")
        self.state.start_step(step_name)

        try:
            # Load required kernel modules
            modules = ["br_netfilter", "overlay"]
            for module in modules:
                self.log.progress(f"Loading kernel module: {module}")
                # Check if already loaded
                result = run_command(f"grep -q {module} /proc/modules", check=False)
                if result.returncode != 0:
                    run_command(f"sudo modprobe {module}", timeout=30)

            # Make modules persistent across reboots
            modules_conf = "/etc/modules-load.d/k8s-mcc.conf"
            self.log.progress("Making kernel modules persistent")
            modules_content = "\n".join(modules) + "\n"
            run_command(f"echo '{modules_content}' | sudo tee {modules_conf}", timeout=10)

            # Configure sysctl settings for Kubernetes networking
            sysctl_settings = {
                "net.bridge.bridge-nf-call-iptables": "1",
                "net.bridge.bridge-nf-call-ip6tables": "1",
                "net.ipv4.ip_forward": "1",
                "net.ipv4.conf.all.forwarding": "1",
                "net.ipv6.conf.all.forwarding": "1",
            }

            self.log.progress("Configuring sysctl settings")
            sysctl_conf = "/etc/sysctl.d/99-k8s-mcc.conf"
            sysctl_content = "\n".join(f"{k} = {v}" for k, v in sysctl_settings.items()) + "\n"
            run_command(f"echo '{sysctl_content}' | sudo tee {sysctl_conf}", timeout=10)

            # Apply sysctl settings
            run_command("sudo sysctl --system", timeout=30)

            self.state.complete_step(step_name)
            self.log.step_complete(step_name)

        except Exception as e:
            self.state.fail_step(step_name, str(e))
            self.log.step_failed(step_name, str(e))
            raise

    def _install_packages(self) -> None:
        """Install required system packages."""
        step_name = "install_packages"
        self.log.step_start(step_name, "Installing system packages")
        self.state.start_step(step_name)

        try:
            # Update package lists
            self.log.progress("Updating package lists")
            run_command("sudo apt update", timeout=300)

            # Install packages
            # Note: docker.io is NOT included here because we install Docker
            # via get.docker.com script which uses containerd.io (conflicts with docker.io)
            # The qemu package is also excluded as qemu-kvm + qemu-system-x86 is sufficient
            packages = [
                "gcc",
                "libpq-dev",
                "libvirt-dev",
                "python3-dev",
                "python3-pip",
                "python3-venv",
                "python3-wheel",
                "python3-virtualenv",
                "ipmitool",
                "jq",
                "wget",
                "curl",
                "libvirt-daemon-system",
                "libvirt-clients",
                "bridge-utils",
                "qemu-kvm",
                "qemu-system-x86",
                "virtinst",
                "virt-manager",
                "netcat-openbsd",
                "ovmf",  # UEFI firmware for VMs
            ]

            self.log.progress(f"Installing {len(packages)} packages")
            run_command(
                f"sudo apt install -y {' '.join(packages)}",
                timeout=600,
            )

            # Add user to groups
            user = os.environ.get("USER", "root")
            self.log.progress(f"Adding {user} to libvirt and kvm groups")
            run_command(f"sudo usermod -aG libvirt {user}", check=False)
            run_command(f"sudo usermod -aG kvm {user}", check=False)

            self.state.complete_step(step_name)
            self.log.step_complete(step_name)

        except Exception as e:
            self.state.fail_step(step_name, str(e))
            self.log.step_failed(step_name, str(e))
            raise

    def _install_docker(self) -> None:
        """Install Docker using get.docker.com script."""
        step_name = "install_docker"
        self.log.step_start(step_name, "Installing Docker")
        self.state.start_step(step_name)

        try:
            # Check if Docker is already installed
            try:
                output = run_command_output("docker --version", timeout=10)
                if "Docker version" in output:
                    self.log.progress("Docker is already installed")
                    self.state.complete_step(step_name)
                    self.log.step_complete(step_name)
                    return
            except Exception:
                pass  # Docker not installed, continue

            # Install Docker via official script
            self.log.progress("Downloading Docker installer")
            run_command("curl -fsSL https://get.docker.com -o /tmp/get-docker.sh", timeout=60)
            run_command("chmod +x /tmp/get-docker.sh", timeout=10)

            self.log.progress("Installing Docker (this may take a few minutes)")
            run_command("sudo /tmp/get-docker.sh", timeout=600)

            # Add user to docker group
            user = os.environ.get("USER", "root")
            self.log.progress(f"Adding {user} to docker group")
            run_command(f"sudo usermod -aG docker {user}", check=False)

            # Start and enable Docker
            self.log.progress("Starting Docker service")
            run_command("sudo systemctl start docker", check=False)
            run_command("sudo systemctl enable docker", check=False)

            # Cleanup
            run_command("rm -f /tmp/get-docker.sh", check=False)

            self.state.complete_step(step_name)
            self.log.step_complete(step_name)

        except Exception as e:
            self.state.fail_step(step_name, str(e))
            self.log.step_failed(step_name, str(e))
            raise

    def _detect_network(self) -> None:
        """Detect primary network interface and IP."""
        step_name = "detect_network"
        self.log.step_start(step_name, "Detecting network configuration")
        self.state.start_step(step_name)

        try:
            # Get primary interface
            interface = self.config.primary_interface
            if interface == "auto":
                interface = detect_primary_interface()

            self.log.progress(f"Using interface: {interface}")

            # Get IP address
            ip = get_interface_ip(interface)
            self.log.progress(f"Detected IP: {ip}")

            # Save to state and hosts.txt
            self.state.set_resource("primary_interface", interface)
            self.state.set_resource("kvm_node_ip", ip)

            # Write hosts.txt for backward compatibility
            hosts_file = Path(self.config.base_dir) / "hosts.txt"
            hosts_file.write_text(ip)
            self.log.progress(f"Saved IP to {hosts_file}")

            self.state.complete_step(step_name, {"interface": interface, "ip": ip})
            self.log.step_complete(step_name)

        except Exception as e:
            self.state.fail_step(step_name, str(e))
            self.log.step_failed(step_name, str(e))
            raise

    def _setup_bridges(self) -> None:
        """Setup network bridges."""
        step_name = "setup_bridges"
        self.log.step_start(step_name, "Setting up network bridges")
        self.state.start_step(step_name)

        try:
            # Remove default virbr0 if exists
            self._remove_default_bridge()

            # Create each bridge
            bridges = self.config.bridges
            for name, bridge in bridges.items():
                self._create_bridge(bridge)

            self.state.complete_step(step_name)
            self.log.step_complete(step_name)

        except Exception as e:
            self.state.fail_step(step_name, str(e))
            self.log.step_failed(step_name, str(e))
            raise

    def _remove_default_bridge(self) -> None:
        """Remove default virbr0 bridge if exists."""
        try:
            # Check if virbr0 exists as interface
            result = run_command("ip link show virbr0", check=False)
            if result.returncode == 0:
                self.log.progress("Removing default virbr0 bridge")
                run_command("sudo ip link set virbr0 down", check=False)
                run_command("sudo brctl delbr virbr0", check=False)
        except Exception:
            pass

        # Remove virsh network if exists
        try:
            run_command("sudo virsh net-destroy default", check=False)
            run_command("sudo virsh net-undefine default", check=False)
        except Exception:
            pass

    def _create_bridge(self, bridge: NetworkBridge) -> None:
        """
        Create a network bridge.

        Args:
            bridge: Bridge configuration
        """
        self.log.progress(f"Creating bridge: {bridge.name}")

        # Check if bridge already exists
        if bridge_exists(bridge.name):
            self.log.progress(f"Bridge {bridge.name} already exists, skipping")
            return

        # Create XML definition
        xml_content = f"""<network>
  <name>{bridge.name}</name>
  <forward mode="nat">
    <nat>
      <port start="1024" end="65535"/>
    </nat>
  </forward>
  <bridge name="{bridge.name}" stp="on" delay="0"/>
  <ip address="{bridge.gateway}" netmask="255.255.255.0"/>
</network>"""

        # Write to temp file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.xml', delete=False) as f:
            f.write(xml_content)
            xml_file = f.name

        try:
            # Define and start network
            run_command(f"sudo virsh net-define {xml_file}")
            run_command(f"sudo virsh net-start {bridge.name}")
            run_command(f"sudo virsh net-autostart {bridge.name}")
            self.log.resource_created("bridge", bridge.name)

        finally:
            os.unlink(xml_file)

    def _mount_storage(self) -> None:
        """Mount additional storage for VM images."""
        step_name = "mount_storage"
        self.log.step_start(step_name, "Setting up storage")
        self.state.start_step(step_name)

        try:
            images_path = self.config.images_path

            # Check if already mounted
            result = run_command(f"mountpoint -q {images_path}", check=False)
            if result.returncode == 0:
                self.log.progress(f"{images_path} is already mounted")
                self.state.skip_step(step_name, "Already mounted")
                return

            if not self.config.auto_mount_storage:
                self.log.progress("Auto-mount disabled, skipping")
                # Just create the directory
                run_command(f"sudo mkdir -p {images_path}")
                self.state.skip_step(step_name, "Auto-mount disabled")
                return

            # Find largest unmounted disk
            self.log.progress("Looking for unmounted disk")
            output = run_command_output(
                "lsblk -nd --output NAME,SIZE,TYPE,MOUNTPOINT | "
                "awk '$3==\"disk\" && $4==\"\" {print $1,$2}' | "
                "sort -k2 -hr | head -n 1"
            )

            if not output.strip():
                self.log.progress("No unmounted disk found, using existing storage")
                run_command(f"sudo mkdir -p {images_path}")
                self.state.skip_step(step_name, "No unmounted disk")
                return

            disk = output.split()[0]

            # Validate disk name to prevent command injection
            # Valid disk names: sda, nvme0n1, vda, xvda, etc.
            if not re.match(r'^[a-zA-Z0-9_-]+$', disk):
                raise ValueError(f"Invalid disk name format: {disk}")

            self.log.progress(f"Found disk: /dev/{disk}")

            # Check if disk needs formatting
            fstype = run_command_output(f"lsblk -no FSTYPE /dev/{disk}")
            if not fstype.strip():
                self.log.progress(f"Formatting /dev/{disk} as ext4")
                run_command(f"sudo mkfs.ext4 /dev/{disk}")

            # Create mount point and mount
            run_command(f"sudo mkdir -p {images_path}")
            run_command(f"sudo mount /dev/{disk} {images_path}")

            # Add to fstab for persistence
            fstab_entry = f"/dev/{disk} {images_path} ext4 defaults 0 0"
            result = run_command(f"grep -q '{images_path}' /etc/fstab", check=False)
            if result.returncode != 0:
                run_command(f"echo '{fstab_entry}' | sudo tee -a /etc/fstab")
                self.log.progress("Added mount to /etc/fstab")

            self.state.complete_step(step_name, {"disk": disk, "path": images_path})
            self.log.step_complete(step_name)

        except Exception as e:
            self.state.fail_step(step_name, str(e))
            self.log.step_failed(step_name, str(e))
            raise

    def _install_vbmc(self) -> None:
        """Install and configure Virtual BMC."""
        step_name = "install_vbmc"
        self.log.step_start(step_name, "Installing Virtual BMC")
        self.state.start_step(step_name)

        try:
            # Determine vbmc binary path - check system path first
            vbmc_bin = None
            vbmcd_bin = None

            # Check if vbmc is already in system PATH
            try:
                system_vbmc = run_command_output("which vbmc", timeout=10).strip()
                if system_vbmc and os.path.exists(system_vbmc):
                    vbmc_bin = system_vbmc
                    # vbmcd should be in same directory
                    vbmcd_bin = os.path.join(os.path.dirname(system_vbmc), "vbmcd")
                    if not os.path.exists(vbmcd_bin):
                        vbmcd_bin = run_command_output("which vbmcd", timeout=10).strip()
                    self.log.progress(f"vBMC already installed at {vbmc_bin}")
            except Exception:
                pass  # Not in system path

            # If not found, check /opt/vbmc virtualenv
            if not vbmc_bin:
                vbmc_path = "/opt/vbmc"
                if os.path.exists(f"{vbmc_path}/bin/vbmc"):
                    vbmc_bin = f"{vbmc_path}/bin/vbmc"
                    vbmcd_bin = f"{vbmc_path}/bin/vbmcd"
                    self.log.progress("vBMC found in virtualenv")

            # If still not found, install via pip
            if not vbmc_bin:
                self.log.progress("Installing vBMC via pip")
                run_command("sudo pip3 install wheel setuptools pkgconfig", timeout=120)
                run_command("sudo pip3 install virtualbmc", timeout=300)

                # Find installed binary
                vbmc_bin = run_command_output("which vbmc", timeout=10).strip()
                vbmcd_bin = run_command_output("which vbmcd", timeout=10).strip()
                self.log.progress(f"vBMC installed at {vbmc_bin}")

            # Store paths in state
            self.state.set_resource("vbmc_bin", vbmc_bin)
            self.state.set_resource("vbmcd_bin", vbmcd_bin)

            # Create systemd service with correct path
            service_content = f"""[Install]
WantedBy = multi-user.target

[Service]
BlockIOAccounting = True
CPUAccounting = True
ExecReload = /bin/kill -HUP $MAINPID
ExecStart = {vbmcd_bin} --foreground
Group = root
MemoryAccounting = True
PrivateDevices = False
PrivateNetwork = False
PrivateTmp = False
PrivateUsers = False
Restart = on-failure
RestartSec = 2
Slice = vbmc.slice
TasksAccounting = True
TimeoutSec = 120
Type = simple
User = root

[Unit]
After = libvirtd.service
After = syslog.target
After = network.target
Description = vbmc service
"""

            service_path = "/usr/lib/systemd/system/virtualbmc.service"
            with tempfile.NamedTemporaryFile(mode='w', suffix='.service', delete=False) as f:
                f.write(service_content)
                temp_service = f.name

            run_command(f"sudo mv {temp_service} {service_path}")
            run_command(f"sudo chmod 644 {service_path}")

            # Enable and start service
            self.log.progress("Starting vBMC service")
            run_command("sudo systemctl daemon-reload")
            run_command("sudo systemctl enable virtualbmc")
            run_command("sudo systemctl restart virtualbmc")

            # Verify
            run_command(f"{vbmc_bin} list")

            self.state.complete_step(step_name)
            self.log.step_complete(step_name)

        except Exception as e:
            self.state.fail_step(step_name, str(e))
            self.log.step_failed(step_name, str(e))
            raise

    def _setup_ssh(self) -> None:
        """Setup SSH keys."""
        step_name = "setup_ssh"
        self.log.step_start(step_name, "Setting up SSH keys")
        self.state.start_step(step_name)

        try:
            ssh_dir = Path.home() / ".ssh"
            key_file = ssh_dir / "id_rsa"

            # Create .ssh directory if needed
            ssh_dir.mkdir(mode=0o700, exist_ok=True)

            # Generate key if not exists
            if not key_file.exists():
                self.log.progress("Generating SSH key pair")
                run_command(f"ssh-keygen -t rsa -b 4096 -N '' -f {key_file}")

            # Add to authorized_keys
            pub_key = (ssh_dir / "id_rsa.pub").read_text().strip()
            auth_keys = ssh_dir / "authorized_keys"

            if not auth_keys.exists():
                auth_keys.write_text(pub_key + "\n")
                auth_keys.chmod(0o600)
            else:
                existing = auth_keys.read_text()
                if pub_key not in existing:
                    with auth_keys.open("a") as f:
                        f.write(pub_key + "\n")

            self.log.progress("SSH key configured")

            self.state.complete_step(step_name)
            self.log.step_complete(step_name)

        except Exception as e:
            self.state.fail_step(step_name, str(e))
            self.log.step_failed(step_name, str(e))
            raise

    def _configure_firewall(self) -> None:
        """Configure firewall rules."""
        step_name = "configure_firewall"
        self.log.step_start(step_name, "Configuring firewall")
        self.state.start_step(step_name)

        try:
            # Block port 80 (required for bootstrap)
            self.log.progress("Blocking port 80 for bootstrap")

            # Check if rule already exists
            result = run_command(
                "sudo iptables -C INPUT -p tcp --dport 80 -j REJECT 2>/dev/null",
                check=False,
            )

            if result.returncode != 0:
                run_command("sudo iptables -A INPUT -p tcp --dport 80 -j REJECT")

            # Persist iptables rules
            try:
                run_command("sudo netfilter-persistent save", check=False, timeout=30)
            except Exception:
                self.log.warning("Could not persist iptables rules")

            self.state.complete_step(step_name)
            self.log.step_complete(step_name)

        except Exception as e:
            self.state.fail_step(step_name, str(e))
            self.log.step_failed(step_name, str(e))
            raise

    def cleanup(self) -> None:
        """Clean up infrastructure (bridges, etc.)."""
        self.log.phase_start("infrastructure_cleanup", "Cleaning up infrastructure")

        # Remove bridges
        for name, bridge in self.config.bridges.items():
            if bridge_exists(bridge.name):
                self.log.progress(f"Removing bridge: {bridge.name}")
                try:
                    run_command(f"sudo virsh net-destroy {bridge.name}", check=False)
                    run_command(f"sudo virsh net-undefine {bridge.name}", check=False)
                except Exception as e:
                    self.log.warning(f"Could not remove bridge {bridge.name}: {e}")

        self.log.phase_complete("infrastructure_cleanup")

    def get_kvm_node_ip(self) -> str:
        """
        Get KVM node IP address.

        Returns:
            IP address
        """
        ip = self.state.get_resource("kvm_node_ip")
        if ip:
            return ip

        # Try to read from hosts.txt
        hosts_file = Path(self.config.base_dir) / "hosts.txt"
        if hosts_file.exists():
            return hosts_file.read_text().strip()

        # Detect
        interface = self.config.primary_interface
        if interface == "auto":
            interface = detect_primary_interface()
        return get_interface_ip(interface)
