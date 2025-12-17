"""
Pre-flight Validation Module

Comprehensive validation checks before starting deployment.
Ensures all prerequisites are met.
"""

import os
import socket
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, List, Optional, Tuple

from .config import Config
from .logger import DeploymentLogger, get_logger
from .utils import (
    check_command_exists,
    check_cpu_count,
    check_disk_space,
    check_memory_available,
    check_port_available,
    detect_primary_interface,
    get_interface_ip,
    run_command,
    run_command_output,
)

logger = get_logger("validation")


@dataclass
class ValidationResult:
    """Result of a validation check."""
    name: str
    passed: bool
    message: str
    critical: bool = True
    details: Optional[dict] = None


class ValidationError(Exception):
    """Exception raised when validation fails."""

    def __init__(self, results: List[ValidationResult]):
        failed = [r for r in results if not r.passed and r.critical]
        message = "Pre-flight validation failed:\n" + "\n".join(
            f"  - {r.name}: {r.message}" for r in failed
        )
        super().__init__(message)
        self.results = results


class PreflightValidator:
    """
    Pre-flight validation for MCC/MOSK deployment.

    Performs comprehensive checks to ensure all prerequisites are met
    before starting the deployment process.
    """

    # Minimum resource requirements
    MIN_RAM_GB = 256
    MIN_CPU_CORES = 32
    MIN_DISK_GB = 500

    # Required commands
    REQUIRED_COMMANDS = [
        "virsh",
        "virt-install",
        "qemu-img",
        "docker",
        "python3",
        "wget",
        "curl",
        "jq",
        "ssh",
        "ipmitool",
    ]

    # Required Python packages
    REQUIRED_PYTHON_PACKAGES = [
        "yaml",
        "json",
    ]

    def __init__(self, config: Config, log: Optional[DeploymentLogger] = None):
        """
        Initialize validator.

        Args:
            config: Deployment configuration
            log: Optional deployment logger
        """
        self.config = config
        self.log = log or DeploymentLogger("validation")
        self.results: List[ValidationResult] = []

    def _add_result(
        self,
        name: str,
        passed: bool,
        message: str,
        critical: bool = True,
        details: Optional[dict] = None,
    ) -> None:
        """Add a validation result."""
        result = ValidationResult(
            name=name,
            passed=passed,
            message=message,
            critical=critical,
            details=details,
        )
        self.results.append(result)

        if passed:
            self.log.validation_passed(name)
        else:
            self.log.validation_failed(name, message)

    def check_running_as_root(self) -> None:
        """Check if running with appropriate privileges."""
        # Not requiring root, but checking sudo access
        try:
            run_command("sudo -n true", check=True, capture_output=True)
            self._add_result(
                "sudo_access",
                True,
                "Sudo access available without password",
            )
        except Exception:
            self._add_result(
                "sudo_access",
                False,
                "Sudo access required. Please configure passwordless sudo or run as root.",
            )

    def check_operating_system(self) -> None:
        """Check operating system compatibility."""
        try:
            os_info = run_command_output("cat /etc/os-release")
            if "Ubuntu" in os_info:
                # Extract version
                for line in os_info.split("\n"):
                    if line.startswith("VERSION_ID="):
                        version = line.split("=")[1].strip('"')
                        if version in ["20.04", "22.04", "24.04"]:
                            self._add_result(
                                "operating_system",
                                True,
                                f"Ubuntu {version} detected",
                                details={"version": version},
                            )
                            return

                self._add_result(
                    "operating_system",
                    False,
                    "Ubuntu 20.04, 22.04, or 24.04 required",
                    critical=False,
                )
            else:
                self._add_result(
                    "operating_system",
                    False,
                    "Ubuntu Linux required",
                )
        except Exception as e:
            self._add_result(
                "operating_system",
                False,
                f"Could not detect OS: {e}",
            )

    def check_memory(self) -> None:
        """Check available memory."""
        has_enough, available = check_memory_available(self.MIN_RAM_GB)

        # Calculate required memory based on topology
        required = (
            self.config.mcc_topology.count * self.config.mcc_topology.resources.ram_mb +
            self.config.mosk_control_topology.count * self.config.mosk_control_topology.resources.ram_mb +
            self.config.mosk_compute_topology.count * self.config.mosk_compute_topology.resources.ram_mb
        )
        # Add storage nodes if in dedicated mode
        if self.config.mosk_storage_topology:
            required += (
                self.config.mosk_storage_topology.count *
                self.config.mosk_storage_topology.resources.ram_mb
            )
        required = required // 1024  # Convert to GB

        self._add_result(
            "memory",
            available >= required,
            f"{available}GB available, {required}GB required",
            details={"available_gb": available, "required_gb": required},
        )

    def check_cpu(self) -> None:
        """Check CPU cores."""
        has_enough, available = check_cpu_count(self.MIN_CPU_CORES)

        # Calculate required CPUs based on topology
        required = (
            self.config.mcc_topology.count * self.config.mcc_topology.resources.vcpus +
            self.config.mosk_control_topology.count * self.config.mosk_control_topology.resources.vcpus +
            self.config.mosk_compute_topology.count * self.config.mosk_compute_topology.resources.vcpus
        )
        # Add storage nodes if in dedicated mode
        if self.config.mosk_storage_topology:
            required += (
                self.config.mosk_storage_topology.count *
                self.config.mosk_storage_topology.resources.vcpus
            )

        self._add_result(
            "cpu_cores",
            available >= required,
            f"{available} cores available, {required} required",
            details={"available": available, "required": required},
        )

    def check_disk_space(self) -> None:
        """Check disk space."""
        images_path = self.config.images_path

        # Calculate required disk space
        required = (
            self.config.mcc_topology.count * (
                self.config.mcc_topology.resources.disk_root_gb +
                self.config.mcc_topology.resources.disk_local_gb
            ) +
            self.config.mosk_control_topology.count * (
                self.config.mosk_control_topology.resources.disk_root_gb +
                self.config.mosk_control_topology.resources.disk_local_gb
            ) +
            self.config.mosk_compute_topology.count * (
                self.config.mosk_compute_topology.resources.disk_root_gb +
                self.config.mosk_compute_topology.resources.disk_local_gb
            )
        )
        # Add Ceph disks based on storage mode
        if self.config.mosk_storage_topology:
            # Dedicated mode: Ceph disks on storage nodes
            required += self.config.mosk_storage_topology.count * (
                self.config.mosk_storage_topology.resources.disk_root_gb +
                self.config.mosk_storage_topology.resources.disk_ceph_gb *
                self.config.mosk_storage_topology.resources.ceph_disk_count
            )
        else:
            # Hyperconverged mode: Ceph disks on compute nodes
            required += self.config.mosk_compute_topology.count * (
                self.config.mosk_compute_topology.resources.disk_ceph_gb *
                self.config.mosk_compute_topology.resources.ceph_disk_count
            )

        # Add buffer
        required = int(required * 1.2)

        # Check parent directory if images path doesn't exist
        check_path = images_path
        if not os.path.exists(check_path):
            check_path = str(Path(check_path).parent)

        has_enough, available = check_disk_space(check_path, required)

        self._add_result(
            "disk_space",
            has_enough,
            f"{available}GB available at {check_path}, {required}GB required",
            details={"available_gb": available, "required_gb": required, "path": check_path},
        )

    def check_required_commands(self) -> None:
        """Check required commands are available."""
        missing = []
        for cmd in self.REQUIRED_COMMANDS:
            if not check_command_exists(cmd):
                missing.append(cmd)

        if missing:
            self._add_result(
                "required_commands",
                False,
                f"Missing commands: {', '.join(missing)}",
                details={"missing": missing},
            )
        else:
            self._add_result(
                "required_commands",
                True,
                "All required commands available",
            )

    def check_virtualization(self) -> None:
        """Check KVM virtualization is available."""
        try:
            # Check KVM module
            kvm_loaded = os.path.exists("/dev/kvm")

            # Check libvirt service
            result = run_command("systemctl is-active libvirtd", check=False)
            libvirt_active = result.returncode == 0

            if kvm_loaded and libvirt_active:
                self._add_result(
                    "virtualization",
                    True,
                    "KVM and libvirt available",
                )
            else:
                issues = []
                if not kvm_loaded:
                    issues.append("KVM module not loaded (/dev/kvm missing)")
                if not libvirt_active:
                    issues.append("libvirtd service not active")

                self._add_result(
                    "virtualization",
                    False,
                    "; ".join(issues),
                )
        except Exception as e:
            self._add_result(
                "virtualization",
                False,
                f"Could not check virtualization: {e}",
            )

    def check_network_interface(self) -> None:
        """Check network interface is available."""
        interface = self.config.primary_interface

        if interface == "auto":
            interface = detect_primary_interface()

        try:
            ip = get_interface_ip(interface)
            self._add_result(
                "network_interface",
                True,
                f"Interface {interface} has IP {ip}",
                details={"interface": interface, "ip": ip},
            )
        except Exception as e:
            self._add_result(
                "network_interface",
                False,
                f"Interface {interface} not available: {e}",
            )

    def check_docker(self) -> None:
        """Check Docker is available and running."""
        try:
            # Check Docker daemon
            run_command("docker info", check=True, timeout=30)

            # Check Docker registry access (optional)
            self._add_result(
                "docker",
                True,
                "Docker daemon running",
            )
        except Exception as e:
            self._add_result(
                "docker",
                False,
                f"Docker not available: {e}",
            )

    def check_license_file(self) -> None:
        """Check Mirantis license file exists."""
        license_path = Path(self.config.base_dir) / self.config.license_file

        if license_path.exists():
            self._add_result(
                "license_file",
                True,
                f"License file found: {license_path}",
            )
        else:
            self._add_result(
                "license_file",
                False,
                f"License file not found: {license_path}. "
                f"Please obtain mirantis.lic from Mirantis.",
            )

    def check_internet_connectivity(self) -> None:
        """Check internet connectivity."""
        urls_to_check = [
            ("binary.mirantis.com", 443),
            ("github.com", 443),
        ]

        for host, port in urls_to_check:
            try:
                sock = socket.create_connection((host, port), timeout=10)
                sock.close()
                self._add_result(
                    f"connectivity_{host}",
                    True,
                    f"Can reach {host}:{port}",
                    critical=True,
                )
            except socket.error as e:
                self._add_result(
                    f"connectivity_{host}",
                    False,
                    f"Cannot reach {host}:{port}: {e}",
                    critical=True,
                )

    def check_dns_resolution(self) -> None:
        """Check DNS resolution works."""
        try:
            socket.gethostbyname("binary.mirantis.com")
            self._add_result(
                "dns_resolution",
                True,
                "DNS resolution working",
            )
        except socket.error as e:
            self._add_result(
                "dns_resolution",
                False,
                f"DNS resolution failed: {e}",
            )

    def check_ports_available(self) -> None:
        """Check required ports are available."""
        ports_to_check = [
            (80, "HTTP for bootstrap"),
            (443, "HTTPS for API"),
        ]

        # Collect all vBMC port ranges
        port_starts = [
            self.config.mcc_topology.vbmc_port_start,
            self.config.mosk_control_topology.vbmc_port_start,
            self.config.mosk_compute_topology.vbmc_port_start,
        ]
        port_ends = [
            self.config.mcc_topology.vbmc_port_start + self.config.mcc_topology.count,
            self.config.mosk_control_topology.vbmc_port_start + self.config.mosk_control_topology.count,
            self.config.mosk_compute_topology.vbmc_port_start + self.config.mosk_compute_topology.count,
        ]
        # Include storage nodes if in dedicated mode
        if self.config.mosk_storage_topology:
            port_starts.append(self.config.mosk_storage_topology.vbmc_port_start)
            port_ends.append(
                self.config.mosk_storage_topology.vbmc_port_start +
                self.config.mosk_storage_topology.count
            )

        vbmc_start = min(port_starts)
        vbmc_end = max(port_ends)

        unavailable = []
        for port, desc in ports_to_check:
            if not check_port_available(port):
                unavailable.append(f"{port} ({desc})")

        # Just check a sample of vBMC ports
        for port in [vbmc_start, vbmc_end - 1]:
            if not check_port_available(port):
                unavailable.append(f"{port} (vBMC)")

        if unavailable:
            self._add_result(
                "ports_available",
                False,
                f"Ports in use: {', '.join(unavailable)}",
                critical=False,  # Not critical as they might be from previous run
            )
        else:
            self._add_result(
                "ports_available",
                True,
                "Required ports available",
            )

    def check_ssh_key(self) -> None:
        """Check SSH key exists."""
        ssh_key = Path.home() / ".ssh" / "id_rsa"

        if ssh_key.exists():
            self._add_result(
                "ssh_key",
                True,
                "SSH key found",
            )
        else:
            self._add_result(
                "ssh_key",
                False,
                "SSH key not found. Will be generated during setup.",
                critical=False,
            )

    def check_existing_vms(self) -> None:
        """Check for existing VMs that might conflict."""
        try:
            output = run_command_output("virsh list --all --name")
            existing = [vm for vm in output.split("\n") if vm.strip()]

            conflicting = []
            vm_prefixes = ["mcc-", "mosk-ctl-", "mosk-cmp-", "mosk-storage-"]
            for vm in existing:
                for prefix in vm_prefixes:
                    if vm.startswith(prefix):
                        conflicting.append(vm)

            if conflicting:
                self._add_result(
                    "existing_vms",
                    False,
                    f"Conflicting VMs exist: {', '.join(conflicting)}. "
                    f"Run cleanup first or use different names.",
                    critical=False,
                )
            else:
                self._add_result(
                    "existing_vms",
                    True,
                    "No conflicting VMs found",
                )
        except Exception as e:
            self._add_result(
                "existing_vms",
                True,  # Assume OK if can't check
                f"Could not check existing VMs: {e}",
                critical=False,
            )

    def check_existing_bridges(self) -> None:
        """Check for existing network bridges."""
        bridges = [b.name for b in self.config.bridges.values()]
        existing = []

        for bridge in bridges:
            try:
                run_command(f"virsh net-info {bridge}", check=True)
                existing.append(bridge)
            except Exception:
                pass

        if existing:
            self._add_result(
                "existing_bridges",
                True,  # Not critical - we can reuse
                f"Existing bridges found: {', '.join(existing)} (will be reused)",
                critical=False,
            )
        else:
            self._add_result(
                "existing_bridges",
                True,
                "No conflicting bridges found",
            )

    def check_environment_variables(self) -> None:
        """Check for recommended environment variables."""
        env_vars = {
            "MCC_BMC_PASSWORD": "BMC password (using default if not set)",
            "MCC_ROOT_PASSWORD": "Root password (using default if not set)",
            "MCC_SERVICE_PASSWORD": "Service password (using default if not set)",
        }

        warnings = []
        for var, desc in env_vars.items():
            if var not in os.environ:
                warnings.append(f"{var}: {desc}")

        if warnings:
            self._add_result(
                "environment_variables",
                True,  # Not critical
                "Using default credentials. Set env vars for custom values.",
                critical=False,
                details={"missing": warnings},
            )
        else:
            self._add_result(
                "environment_variables",
                True,
                "Custom credentials provided via environment variables",
            )

    def check_ceph_disk_configuration(self) -> None:
        """Check Ceph disk configuration consistency."""
        osd_devices = self.config.ceph_osd_devices
        device_count = len(osd_devices)

        # Check consistency with topology configuration
        if self.config.is_hyperconverged:
            # Hyperconverged: Ceph disks on compute nodes
            expected_count = self.config.mosk_compute_topology.resources.ceph_disk_count
            node_type = "compute"
        else:
            # Dedicated: Ceph disks on storage nodes
            if self.config.mosk_storage_topology:
                expected_count = self.config.mosk_storage_topology.resources.ceph_disk_count
                node_type = "storage"
            else:
                # No storage topology defined in dedicated mode
                self._add_result(
                    "ceph_disk_configuration",
                    False,
                    "Dedicated storage mode requires mosk_storage topology configuration",
                )
                return

        if device_count != expected_count:
            self._add_result(
                "ceph_disk_configuration",
                False,
                f"Ceph OSD devices mismatch: {device_count} devices configured "
                f"(storage.ceph.osd_devices), but {node_type} topology expects "
                f"{expected_count} disks (ceph_disk_count)",
                details={
                    "configured_devices": osd_devices,
                    "expected_count": expected_count,
                    "mode": self.config.storage_mode,
                },
            )
        else:
            self._add_result(
                "ceph_disk_configuration",
                True,
                f"Ceph configuration valid: {device_count} OSD devices for "
                f"{self.config.storage_mode} mode",
                details={
                    "devices": osd_devices,
                    "mode": self.config.storage_mode,
                },
            )

    def run_all_checks(self) -> List[ValidationResult]:
        """
        Run all validation checks.

        Returns:
            List of validation results
        """
        self.log.phase_start("preflight_validation", "Running pre-flight checks")
        self.results = []

        checks = [
            ("System Access", self.check_running_as_root),
            ("Operating System", self.check_operating_system),
            ("Memory", self.check_memory),
            ("CPU Cores", self.check_cpu),
            ("Disk Space", self.check_disk_space),
            ("Required Commands", self.check_required_commands),
            ("Virtualization", self.check_virtualization),
            ("Network Interface", self.check_network_interface),
            ("Docker", self.check_docker),
            ("License File", self.check_license_file),
            ("Internet Connectivity", self.check_internet_connectivity),
            ("DNS Resolution", self.check_dns_resolution),
            ("Port Availability", self.check_ports_available),
            ("SSH Key", self.check_ssh_key),
            ("Existing VMs", self.check_existing_vms),
            ("Existing Bridges", self.check_existing_bridges),
            ("Environment Variables", self.check_environment_variables),
            ("Ceph Disk Configuration", self.check_ceph_disk_configuration),
        ]

        for name, check_fn in checks:
            self.log.step_start(name)
            try:
                check_fn()
                self.log.step_complete(name)
            except Exception as e:
                self._add_result(name, False, str(e))
                self.log.step_failed(name, str(e))

        # Summary
        passed = sum(1 for r in self.results if r.passed)
        failed_critical = sum(1 for r in self.results if not r.passed and r.critical)
        failed_warning = sum(1 for r in self.results if not r.passed and not r.critical)

        self.log.progress(
            f"Validation complete: {passed} passed, "
            f"{failed_critical} critical failures, {failed_warning} warnings"
        )

        if failed_critical > 0:
            self.log.phase_failed("preflight_validation", f"{failed_critical} critical checks failed")
        else:
            self.log.phase_complete("preflight_validation")

        return self.results

    def validate(self, fail_on_critical: bool = True) -> List[ValidationResult]:
        """
        Run validation and optionally fail on critical errors.

        Args:
            fail_on_critical: Whether to raise exception on critical failures

        Returns:
            List of validation results

        Raises:
            ValidationError: If critical checks fail and fail_on_critical=True
        """
        results = self.run_all_checks()

        if fail_on_critical:
            critical_failures = [r for r in results if not r.passed and r.critical]
            if critical_failures:
                raise ValidationError(results)

        return results

    def print_summary(self) -> None:
        """Print validation summary to console."""
        print("\n" + "=" * 60)
        print("PRE-FLIGHT VALIDATION SUMMARY")
        print("=" * 60)

        for result in self.results:
            status = "PASS" if result.passed else ("FAIL" if result.critical else "WARN")
            color = "\033[32m" if result.passed else ("\033[31m" if result.critical else "\033[33m")
            reset = "\033[0m"
            print(f"{color}[{status:4}]{reset} {result.name}: {result.message}")

        print("=" * 60)

        passed = sum(1 for r in self.results if r.passed)
        total = len(self.results)
        critical = sum(1 for r in self.results if not r.passed and r.critical)

        if critical > 0:
            print(f"\033[31mValidation FAILED: {critical} critical issues\033[0m")
        else:
            print(f"\033[32mValidation PASSED: {passed}/{total} checks\033[0m")

        print("")
