"""
Utility Functions Module

Common utility functions for command execution, waiting, network detection, etc.
"""

import json
import os
import re
import shutil
import socket
import subprocess
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from .logger import get_logger

logger = get_logger("utils")


class CommandError(Exception):
    """Exception raised when a command fails."""

    def __init__(self, command: str, exit_code: int, stdout: str, stderr: str):
        self.command = command
        self.exit_code = exit_code
        self.stdout = stdout
        self.stderr = stderr
        super().__init__(
            f"Command failed with exit code {exit_code}: {command}\n"
            f"stdout: {stdout[:500]}\nstderr: {stderr[:500]}"
        )


def run_command(
    command: Any,  # str or List[str]
    check: bool = True,
    capture_output: bool = True,
    timeout: Optional[int] = None,
    env: Optional[Dict[str, str]] = None,
    cwd: Optional[str] = None,
) -> subprocess.CompletedProcess:
    """
    Run a shell command.

    Args:
        command: Command to run (string for shell execution, list for direct execution)
        check: Whether to raise exception on failure
        capture_output: Whether to capture stdout/stderr
        timeout: Command timeout in seconds
        env: Environment variables
        cwd: Working directory

    Returns:
        CompletedProcess instance

    Raises:
        CommandError: If command fails and check=True
    """
    # Determine if we should use shell mode
    use_shell = isinstance(command, str)
    cmd_str = command if use_shell else " ".join(command)
    logger.debug(f"Running command: {cmd_str}")

    # Merge environment
    cmd_env = os.environ.copy()
    if env:
        cmd_env.update(env)

    try:
        result = subprocess.run(
            command,
            shell=use_shell,
            capture_output=capture_output,
            text=True,
            timeout=timeout,
            env=cmd_env,
            cwd=cwd,
        )

        if check and result.returncode != 0:
            raise CommandError(
                command=cmd_str,
                exit_code=result.returncode,
                stdout=result.stdout or "",
                stderr=result.stderr or "",
            )

        return result

    except subprocess.TimeoutExpired as e:
        raise CommandError(
            command=cmd_str,
            exit_code=-1,
            stdout="",
            stderr=f"Command timed out after {timeout} seconds",
        ) from e


def run_command_output(
    command: Any,  # str or List[str]
    timeout: Optional[int] = None,
    env: Optional[Dict[str, str]] = None,
    cwd: Optional[str] = None,
) -> str:
    """
    Run a command and return stdout.

    Args:
        command: Command to run (string or list)
        timeout: Command timeout in seconds
        env: Environment variables
        cwd: Working directory

    Returns:
        Command stdout
    """
    result = run_command(command, timeout=timeout, env=env, cwd=cwd)
    return result.stdout.strip()


def run_command_json(
    command: str,
    timeout: Optional[int] = None,
    env: Optional[Dict[str, str]] = None,
) -> Any:
    """
    Run a command and parse JSON output.

    Args:
        command: Command to run
        timeout: Command timeout
        env: Environment variables

    Returns:
        Parsed JSON data
    """
    output = run_command_output(command, timeout=timeout, env=env)
    return json.loads(output)


def wait_for_condition(
    check_fn: Callable[[], Tuple[bool, str]],
    description: str,
    timeout: int = 3600,
    interval: int = 30,
    progress_fn: Optional[Callable[[str], None]] = None,
) -> bool:
    """
    Wait for a condition to become true.

    Args:
        check_fn: Function that returns (success, current_state)
        description: Description of what we're waiting for
        timeout: Maximum wait time in seconds
        interval: Check interval in seconds
        progress_fn: Optional function to report progress

    Returns:
        True if condition met, False if timeout

    Raises:
        TimeoutError: If timeout exceeded
    """
    start_time = time.time()
    last_state = ""

    while True:
        try:
            success, current_state = check_fn()

            if success:
                logger.debug(f"Condition met: {description}")
                return True

            if current_state != last_state:
                last_state = current_state
                if progress_fn:
                    progress_fn(current_state)
                logger.debug(f"Waiting for {description}: {current_state}")

        except Exception as e:
            logger.warning(f"Check failed: {e}")

        elapsed = time.time() - start_time
        if elapsed > timeout:
            raise TimeoutError(
                f"Timeout waiting for {description} after {elapsed:.0f}s. "
                f"Last state: {last_state}"
            )

        time.sleep(interval)


def detect_primary_interface() -> str:
    """
    Auto-detect the primary network interface.

    Returns:
        Interface name (e.g., bond0, eth0, ens0)
    """
    # Try common interface names in order of preference
    candidates = ["bond0", "eno1", "ens0", "eth0", "enp0s3"]

    # Get list of interfaces with IP addresses
    try:
        result = run_command_output("ip -o -4 addr show scope global")
        lines = result.strip().split("\n")

        for line in lines:
            parts = line.split()
            if len(parts) >= 2:
                iface = parts[1]
                # Prefer candidates in order
                for candidate in candidates:
                    if iface == candidate or iface.startswith(candidate):
                        logger.info(f"Auto-detected primary interface: {iface}")
                        return iface

                # If no preferred candidate, use the first global interface
                if not iface.startswith(("lo", "virbr", "br-", "docker", "veth")):
                    logger.info(f"Auto-detected primary interface: {iface}")
                    return iface

    except CommandError:
        pass

    # Fallback to first available
    logger.warning("Could not auto-detect interface, defaulting to bond0")
    return "bond0"


def get_interface_ip(interface: str) -> str:
    """
    Get IP address of a network interface.

    Args:
        interface: Interface name

    Returns:
        IP address
    """
    try:
        result = run_command_output(
            f"ip -4 addr show {interface} | grep -oP '(?<=inet\\s)\\d+(\\.\\d+){{3}}' | head -n 1"
        )
        return result.strip()
    except CommandError:
        raise ValueError(f"Could not get IP address for interface: {interface}")


def check_command_exists(command: str) -> bool:
    """
    Check if a command exists.

    Args:
        command: Command name

    Returns:
        True if command exists
    """
    return shutil.which(command) is not None


def check_port_available(port: int, host: str = "127.0.0.1") -> bool:
    """
    Check if a port is available.

    Args:
        port: Port number
        host: Host to check

    Returns:
        True if port is available
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((host, port))
        return True
    except socket.error:
        return False
    finally:
        sock.close()


def check_disk_space(path: str, required_gb: int) -> Tuple[bool, int]:
    """
    Check available disk space.

    Args:
        path: Path to check
        required_gb: Required space in GB

    Returns:
        Tuple of (has_enough_space, available_gb)
    """
    stat = os.statvfs(path)
    available_gb = (stat.f_bavail * stat.f_frsize) // (1024 ** 3)
    return available_gb >= required_gb, available_gb


def check_memory_available(required_gb: int) -> Tuple[bool, int]:
    """
    Check available memory.

    Args:
        required_gb: Required memory in GB

    Returns:
        Tuple of (has_enough_memory, available_gb)
    """
    try:
        with open("/proc/meminfo", "r") as f:
            for line in f:
                if line.startswith("MemTotal:"):
                    total_kb = int(line.split()[1])
                    total_gb = total_kb // (1024 * 1024)
                    return total_gb >= required_gb, total_gb
    except Exception:
        pass

    return False, 0


def check_cpu_count(required_cores: int) -> Tuple[bool, int]:
    """
    Check CPU core count.

    Args:
        required_cores: Required number of cores

    Returns:
        Tuple of (has_enough_cores, available_cores)
    """
    available = os.cpu_count() or 0
    return available >= required_cores, available


def file_contains(filepath: str, pattern: str) -> bool:
    """
    Check if file contains a pattern.

    Args:
        filepath: File path
        pattern: Pattern to search

    Returns:
        True if pattern found
    """
    try:
        with open(filepath, "r") as f:
            return pattern in f.read()
    except Exception:
        return False


def ensure_directory(path: str) -> None:
    """
    Ensure a directory exists.

    Args:
        path: Directory path
    """
    Path(path).mkdir(parents=True, exist_ok=True)


def backup_file(filepath: str, suffix: str = ".backup") -> Optional[str]:
    """
    Create a backup of a file.

    Args:
        filepath: File path
        suffix: Backup suffix

    Returns:
        Backup file path or None
    """
    path = Path(filepath)
    if not path.exists():
        return None

    timestamp = time.strftime("%Y%m%d_%H%M%S")
    backup_path = path.with_suffix(f".{timestamp}{suffix}")
    shutil.copy(path, backup_path)
    return str(backup_path)


def render_template(template: str, variables: Dict[str, Any]) -> str:
    """
    Simple template rendering with variable substitution.

    Args:
        template: Template string
        variables: Variables to substitute

    Returns:
        Rendered string
    """
    result = template
    for key, value in variables.items():
        placeholder = f"${{{key}}}"
        result = result.replace(placeholder, str(value))

        # Also support SET_KEY style placeholders
        set_placeholder = f"SET_{key.upper()}"
        result = result.replace(set_placeholder, str(value))

    return result


def parse_version(version_string: str) -> Tuple[int, ...]:
    """
    Parse a version string into a tuple of integers.

    Args:
        version_string: Version string (e.g., "2.30.0", "25.2")

    Returns:
        Tuple of version components
    """
    # Remove any prefix (e.g., "kaas-", "mosk-")
    version_string = re.sub(r"^[a-zA-Z-]+", "", version_string)

    # Extract numbers
    parts = re.findall(r"\d+", version_string)
    return tuple(int(p) for p in parts)


def compare_versions(version1: str, version2: str) -> int:
    """
    Compare two version strings.

    Args:
        version1: First version
        version2: Second version

    Returns:
        -1 if v1 < v2, 0 if equal, 1 if v1 > v2
    """
    v1 = parse_version(version1)
    v2 = parse_version(version2)

    # Pad shorter version
    max_len = max(len(v1), len(v2))
    v1 = v1 + (0,) * (max_len - len(v1))
    v2 = v2 + (0,) * (max_len - len(v2))

    if v1 < v2:
        return -1
    elif v1 > v2:
        return 1
    return 0


def kubectl_command(
    command: str,
    kubeconfig: Optional[str] = None,
    namespace: Optional[str] = None,
    timeout: int = 60,
) -> str:
    """
    Run a kubectl command.

    Args:
        command: kubectl command (without 'kubectl' prefix)
        kubeconfig: Optional kubeconfig path
        namespace: Optional namespace
        timeout: Command timeout

    Returns:
        Command output
    """
    cmd = "kubectl"
    if kubeconfig:
        cmd = f"KUBECONFIG={kubeconfig} {cmd}"
    if namespace:
        cmd = f"{cmd} -n {namespace}"
    cmd = f"{cmd} {command}"

    return run_command_output(cmd, timeout=timeout)


def kubectl_apply(
    manifest_path: str,
    kubeconfig: Optional[str] = None,
    namespace: Optional[str] = None,
) -> str:
    """
    Apply a Kubernetes manifest.

    Args:
        manifest_path: Path to manifest file
        kubeconfig: Optional kubeconfig path
        namespace: Optional namespace

    Returns:
        Command output
    """
    return kubectl_command(
        f"apply -f {manifest_path}",
        kubeconfig=kubeconfig,
        namespace=namespace,
    )


def kubectl_get_json(
    resource: str,
    name: Optional[str] = None,
    kubeconfig: Optional[str] = None,
    namespace: Optional[str] = None,
) -> Any:
    """
    Get Kubernetes resource as JSON.

    Args:
        resource: Resource type
        name: Optional resource name
        kubeconfig: Optional kubeconfig path
        namespace: Optional namespace

    Returns:
        Parsed JSON data
    """
    cmd = f"get {resource}"
    if name:
        cmd = f"{cmd} {name}"
    cmd = f"{cmd} -o json"

    output = kubectl_command(cmd, kubeconfig=kubeconfig, namespace=namespace)
    return json.loads(output)


def kubectl_wait(
    resource: str,
    condition: str,
    timeout: int = 300,
    kubeconfig: Optional[str] = None,
    namespace: Optional[str] = None,
) -> bool:
    """
    Wait for a Kubernetes resource condition.

    Args:
        resource: Resource specification (e.g., "pod/mypod")
        condition: Condition to wait for (e.g., "condition=Ready")
        timeout: Wait timeout in seconds
        kubeconfig: Optional kubeconfig path
        namespace: Optional namespace

    Returns:
        True if condition met
    """
    try:
        kubectl_command(
            f"wait {resource} --for={condition} --timeout={timeout}s",
            kubeconfig=kubeconfig,
            namespace=namespace,
            timeout=timeout + 30,
        )
        return True
    except CommandError:
        return False


def get_vm_list(filter_pattern: Optional[str] = None) -> List[str]:
    """
    Get list of VMs.

    Args:
        filter_pattern: Optional grep pattern

    Returns:
        List of VM names
    """
    cmd = "virsh list --all --name"
    if filter_pattern:
        cmd = f"{cmd} | grep '{filter_pattern}'"

    try:
        output = run_command_output(cmd)
        return [vm.strip() for vm in output.split("\n") if vm.strip()]
    except CommandError:
        return []


def vm_exists(name: str) -> bool:
    """
    Check if a VM exists.

    Args:
        name: VM name

    Returns:
        True if VM exists
    """
    return name in get_vm_list()


def bridge_exists(name: str) -> bool:
    """
    Check if a network bridge exists.

    Args:
        name: Bridge name

    Returns:
        True if bridge exists
    """
    try:
        run_command(f"virsh net-info {name}", check=True)
        return True
    except CommandError:
        return False


def vbmc_exists(vm_name: str) -> bool:
    """
    Check if a vBMC entry exists.

    Args:
        vm_name: VM name

    Returns:
        True if vBMC entry exists
    """
    # Find vbmc binary
    vbmc_bin = None
    try:
        vbmc_bin = run_command_output("which vbmc", timeout=10).strip()
    except Exception:
        # Fallback to common paths
        import os
        for path in ["/usr/local/bin/vbmc", "/opt/vbmc/bin/vbmc"]:
            if os.path.exists(path):
                vbmc_bin = path
                break

    if not vbmc_bin:
        return False

    try:
        output = run_command_output(f"{vbmc_bin} list")
        return vm_name in output
    except CommandError:
        return False
