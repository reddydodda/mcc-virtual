#!/usr/bin/env python3
"""
MCC/MOSK Virtual Deployment Tool

Enterprise-ready deployment automation for Mirantis Container Cloud
and Mirantis OpenStack for Kubernetes.

Usage:
    python3 deploy.py deploy [--resume] [--skip-validation]
    python3 deploy.py validate
    python3 deploy.py status
    python3 deploy.py cleanup [--full]
    python3 deploy.py create-vms
    python3 deploy.py setup-infra

Remote Execution:
    python3 deploy.py --host root@kvm-server validate
    python3 deploy.py --host root@kvm-server deploy
    python3 deploy.py --host root@kvm-server --sync-only  # Just sync files

Environment Variables:
    MCC_BMC_USERNAME    - BMC username (default: root)
    MCC_BMC_PASSWORD    - BMC password (default: admin123)
    MCC_ROOT_PASSWORD   - VM root password (default: r00tme)
    MCC_SERVICE_PASSWORD - Service user password (default: Mirantis@123)
    MCC_LICENSE_PATH    - Path to mirantis.lic file
"""

import argparse
import os
import shlex
import subprocess
import sys
from pathlib import Path

# Add lib to path
sys.path.insert(0, str(Path(__file__).parent))

from lib.deployer import Deployer
from lib.config import Config
from lib.validation import PreflightValidator
from lib.logger import setup_logging, DeploymentLogger
from lib.state import StateManager


# Remote execution constants
REMOTE_DIR = "/root/mcc-virtual"
RSYNC_EXCLUDES = [
    ".git",
    "__pycache__",
    "*.pyc",
    ".DS_Store",
    "deployment_state.json",
    "certs/",
    "*.log",
    ".claude/",
    "kaas-bootstrap/",  # Downloaded on remote, don't delete
    "kubeconfig-*",     # Generated kubeconfigs
    "hosts.txt",        # Generated file
    "keycloak.yaml",    # Generated credentials
]


def sync_to_remote(host: str, local_dir: str, verbose: bool = False) -> bool:
    """
    Sync local deployment files to remote host.

    Args:
        host: SSH host (e.g., root@192.168.1.100 or root@mosk)
        local_dir: Local directory to sync
        verbose: Show detailed output

    Returns:
        True if successful, False otherwise
    """
    print(f"Syncing files to {host}:{REMOTE_DIR}...")

    # Build rsync command
    rsync_cmd = [
        "rsync", "-az", "--delete",
        "--progress" if verbose else "--quiet",
    ]

    # Add excludes
    for exclude in RSYNC_EXCLUDES:
        rsync_cmd.extend(["--exclude", exclude])

    # Source and destination
    rsync_cmd.extend([
        f"{local_dir}/",
        f"{host}:{REMOTE_DIR}/",
    ])

    try:
        result = subprocess.run(rsync_cmd, check=True, capture_output=not verbose)
        print(f"Files synced to {host}:{REMOTE_DIR}")
        return True
    except subprocess.CalledProcessError as e:
        print(f"Failed to sync files: {e}")
        if e.stderr:
            print(e.stderr.decode())
        return False


def install_remote_deps(host: str, verbose: bool = False) -> bool:
    """
    Install Python dependencies on remote host.

    Args:
        host: SSH host
        verbose: Show detailed output

    Returns:
        True if successful, False otherwise
    """
    print(f"Checking/installing dependencies on {host}...")

    # Check if Jinja2 is available
    check_cmd = f"python3 -c 'import jinja2; import yaml' 2>/dev/null && echo OK || echo MISSING"

    try:
        result = subprocess.run(
            ["ssh", host, check_cmd],
            capture_output=True,
            text=True,
        )

        if "OK" in result.stdout:
            if verbose:
                print("Dependencies already installed")
            return True

        # Install dependencies
        print("Installing Python dependencies...")
        install_cmd = "apt-get update -qq && apt-get install -y -qq python3-yaml python3-jinja2"
        result = subprocess.run(
            ["ssh", host, install_cmd],
            capture_output=not verbose,
            text=True,
        )

        if result.returncode != 0:
            print(f"Failed to install dependencies")
            return False

        print("Dependencies installed")
        return True

    except subprocess.CalledProcessError as e:
        print(f"Failed to check/install dependencies: {e}")
        return False


def run_remote_command(host: str, command: str, args_list: list, verbose: bool = False) -> int:
    """
    Run deployment command on remote host.

    Args:
        host: SSH host
        command: Command to run (validate, deploy, etc.)
        args_list: Additional arguments
        verbose: Show detailed output

    Returns:
        Exit code from remote command
    """
    # Build the remote command parts safely using shlex.quote
    remote_parts = [f"cd {shlex.quote(REMOTE_DIR)}", "python3 deploy.py"]

    if verbose:
        remote_parts[1] += " -v"

    # Quote command to prevent injection
    remote_parts[1] += f" {shlex.quote(command)}"

    # Add any extra arguments with proper escaping
    for arg in args_list:
        remote_parts[1] += f" {shlex.quote(arg)}"

    # Join with && for the remote shell
    remote_cmd = " && ".join(remote_parts)

    print(f"Running on {host}: {command}")
    print("-" * 60)

    # Execute via SSH with live output
    try:
        process = subprocess.Popen(
            ["ssh", "-t", host, remote_cmd],
            stdout=sys.stdout,
            stderr=sys.stderr,
        )
        return process.wait()
    except KeyboardInterrupt:
        print("\nRemote command interrupted")
        return 130


def cmd_deploy(args: argparse.Namespace) -> int:
    """Run full deployment."""
    try:
        deployer = Deployer(args.config, resume=args.resume)
        deployer.deploy(
            skip_validation=args.skip_validation,
            resume=args.resume,
        )
        return 0
    except KeyboardInterrupt:
        print("\nDeployment interrupted by user")
        return 130
    except Exception as e:
        print(f"\nDeployment failed: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


def cmd_validate(args: argparse.Namespace) -> int:
    """Run pre-flight validation only."""
    try:
        config = Config(args.config)
        setup_logging(level="INFO" if not args.verbose else "DEBUG")
        log = DeploymentLogger("validate")

        validator = PreflightValidator(config, log)
        results = validator.run_all_checks()
        validator.print_summary()

        critical_failures = [r for r in results if not r.passed and r.critical]
        return 1 if critical_failures else 0

    except Exception as e:
        print(f"Validation error: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


def cmd_status(args: argparse.Namespace) -> int:
    """Show deployment status."""
    try:
        # Use resume=True to find existing deployment state
        deployer = Deployer(args.config, resume=True)
        deployer.status()
        return 0
    except Exception as e:
        print(f"Error getting status: {e}")
        return 1


def cmd_cleanup(args: argparse.Namespace) -> int:
    """Clean up deployment."""
    try:
        # Use resume=True to find existing deployment state
        deployer = Deployer(args.config, resume=True)
        deployer.cleanup(full=args.full)
        print("Cleanup completed successfully")
        return 0
    except Exception as e:
        print(f"Cleanup error: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


def cmd_create_vms(args: argparse.Namespace) -> int:
    """Create VMs only."""
    try:
        # Use resume=True to continue existing deployment
        deployer = Deployer(args.config, resume=True)
        deployer.vm_manager.create_all_vms()
        print("VMs created successfully")
        return 0
    except Exception as e:
        print(f"VM creation error: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


def cmd_setup_infra(args: argparse.Namespace) -> int:
    """Setup infrastructure only."""
    try:
        # Use resume=True to continue existing deployment
        deployer = Deployer(args.config, resume=True)
        deployer.infrastructure.setup_all()
        print("Infrastructure setup completed successfully")
        return 0
    except Exception as e:
        print(f"Infrastructure setup error: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


def cmd_bootstrap(args: argparse.Namespace) -> int:
    """Bootstrap only - clone bootstrap directory and update templates."""
    try:
        # Use resume=True to continue existing deployment
        deployer = Deployer(args.config, resume=True)

        print("=" * 60)
        print("BOOTSTRAP PHASE")
        print("=" * 60)

        # Run pre-flight validation unless skipped
        if not args.skip_validation:
            deployer.run_validation()

        # Setup infrastructure (bridges, vBMC, storage)
        print("\n[1/4] Setting up infrastructure...")
        deployer.infrastructure.setup_all()

        # Create VMs
        print("\n[2/4] Creating virtual machines...")
        deployer.vm_manager.create_all_vms()

        # Clone/download bootstrap
        print("\n[3/4] Cloning MCC bootstrap...")
        deployer.clone_bootstrap()

        # Update templates
        print("\n[4/4] Updating templates...")
        deployer.templates.update_templates_with_config()

        print("\n" + "=" * 60)
        print("BOOTSTRAP COMPLETE")
        print("=" * 60)
        print("Next steps:")
        print("  1. Run 'deploy.py --host <host> mcc' to deploy MCC")
        print("  2. Or run 'deploy.py --host <host> all' for full deployment")

        return 0
    except KeyboardInterrupt:
        print("\nBootstrap interrupted by user")
        return 130
    except Exception as e:
        print(f"\nBootstrap failed: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


def cmd_mcc(args: argparse.Namespace) -> int:
    """Deploy MCC cluster and monitor until ready."""
    try:
        # Use resume=True to continue existing deployment
        deployer = Deployer(args.config, resume=True)

        print("=" * 60)
        print("MCC DEPLOYMENT PHASE")
        print("=" * 60)

        # Deploy MCC
        print("\n[1/2] Deploying MCC cluster...")
        deployer.deploy_mcc()

        # Monitor until ready
        print("\n[2/2] Monitoring MCC cluster until ready...")
        deployer.wait_for_mcc_ready()

        print("\n" + "=" * 60)
        print("MCC DEPLOYMENT COMPLETE")
        print("=" * 60)
        print("Next steps:")
        print("  1. Run 'deploy.py --host <host> mosk' to deploy MOSK")

        return 0
    except KeyboardInterrupt:
        print("\nMCC deployment interrupted by user")
        return 130
    except Exception as e:
        print(f"\nMCC deployment failed: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


def cmd_mosk(args: argparse.Namespace) -> int:
    """Deploy MOSK cluster (requires MCC to be ready)."""
    try:
        # Use resume=True to continue existing deployment
        deployer = Deployer(args.config, resume=True)

        print("=" * 60)
        print("MOSK DEPLOYMENT PHASE")
        print("=" * 60)

        # Check MCC is ready
        print("\n[1/3] Checking MCC cluster status...")
        if not deployer.check_mcc_ready():
            if not getattr(args, 'force', False):
                print("ERROR: MCC cluster is not ready. Please deploy MCC first.")
                print("Run: deploy.py --host <host> mcc")
                print("Or use --force to skip this check")
                return 1
            print("WARNING: MCC cluster is not ready, but --force specified. Proceeding...")
        else:
            print("MCC cluster is ready!")

        # Deploy MOSK
        print("\n[2/3] Deploying MOSK cluster...")
        deployer.deploy_mosk()

        # Monitor until ready
        print("\n[3/3] Monitoring MOSK cluster until ready...")
        deployer.wait_for_mosk_ready()

        print("\n" + "=" * 60)
        print("MOSK DEPLOYMENT COMPLETE")
        print("=" * 60)

        return 0
    except KeyboardInterrupt:
        print("\nMOSK deployment interrupted by user")
        return 130
    except Exception as e:
        print(f"\nMOSK deployment failed: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


def cmd_all(args: argparse.Namespace) -> int:
    """Run complete deployment - bootstrap, MCC, and MOSK."""
    try:
        # Pass resume flag to constructor for proper deployment directory handling
        deployer = Deployer(args.config, resume=args.resume)

        print("=" * 60)
        print("FULL DEPLOYMENT - MCC + MOSK")
        print("=" * 60)

        # Full deployment via deployer
        deployer.deploy(
            skip_validation=args.skip_validation,
            resume=args.resume,
        )

        print("\n" + "=" * 60)
        print("FULL DEPLOYMENT COMPLETE")
        print("=" * 60)

        return 0
    except KeyboardInterrupt:
        print("\nDeployment interrupted by user")
        return 130
    except Exception as e:
        print(f"\nDeployment failed: {e}")
        if args.verbose:
            import traceback
            traceback.print_exc()
        return 1


def cmd_show_config(args: argparse.Namespace) -> int:
    """Show current configuration."""
    try:
        config = Config(args.config)

        print("\n" + "=" * 60)
        print("DEPLOYMENT CONFIGURATION")
        print("=" * 60)
        print(f"Config file: {args.config}")
        print(f"Deployment name: {config.deployment_name}")
        print(f"Environment: {config.environment}")
        print()
        print("Versions:")
        print(f"  MCC minimum: {config.mcc_minimum_version}")
        print(f"  MOSK minimum: {config.mosk_minimum_version}")
        print(f"  OpenStack: {config.openstack_version}")
        print()
        print("Topology:")
        print(f"  MCC nodes: {config.mcc_topology.count}")
        print(f"  MOSK control nodes: {config.mosk_control_topology.count}")
        print(f"  MOSK compute nodes: {config.mosk_compute_topology.count}")
        print(f"  Total VMs: {config.total_vm_count}")
        print()
        print("Resources per VM type:")
        print(f"  MCC: {config.mcc_topology.resources.ram_mb}MB RAM, {config.mcc_topology.resources.vcpus} vCPUs")
        print(f"  MOSK control: {config.mosk_control_topology.resources.ram_mb}MB RAM, {config.mosk_control_topology.resources.vcpus} vCPUs")
        print(f"  MOSK compute: {config.mosk_compute_topology.resources.ram_mb}MB RAM, {config.mosk_compute_topology.resources.vcpus} vCPUs")
        print()
        total_ram = (
            config.mcc_topology.count * config.mcc_topology.resources.ram_mb +
            config.mosk_control_topology.count * config.mosk_control_topology.resources.ram_mb +
            config.mosk_compute_topology.count * config.mosk_compute_topology.resources.ram_mb
        ) // 1024
        total_cpu = (
            config.mcc_topology.count * config.mcc_topology.resources.vcpus +
            config.mosk_control_topology.count * config.mosk_control_topology.resources.vcpus +
            config.mosk_compute_topology.count * config.mosk_compute_topology.resources.vcpus
        )
        print(f"Total resources: {total_ram}GB RAM, {total_cpu} vCPUs")
        print("=" * 60)

        return 0
    except Exception as e:
        print(f"Error reading config: {e}")
        return 1


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="MCC/MOSK Virtual Deployment Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "-c", "--config",
        default="config.yaml",
        help="Path to configuration file (default: config.yaml)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output",
    )
    parser.add_argument(
        "--host",
        metavar="SSH_HOST",
        help="Remote host to run on (e.g., root@192.168.1.100 or root@mosk)",
    )
    parser.add_argument(
        "--sync-only",
        action="store_true",
        help="Only sync files to remote host, don't run command",
    )
    parser.add_argument(
        "--no-sync",
        action="store_true",
        help="Skip file sync when running remotely (use existing files)",
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # deploy command
    deploy_parser = subparsers.add_parser("deploy", help="Run full deployment")
    deploy_parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from previous state",
    )
    deploy_parser.add_argument(
        "--skip-validation",
        action="store_true",
        help="Skip pre-flight validation",
    )

    # validate command
    subparsers.add_parser("validate", help="Run pre-flight validation")

    # status command
    subparsers.add_parser("status", help="Show deployment status")

    # cleanup command
    cleanup_parser = subparsers.add_parser("cleanup", help="Clean up deployment")
    cleanup_parser.add_argument(
        "--full",
        action="store_true",
        help="Also remove infrastructure (bridges, etc.)",
    )

    # create-vms command
    subparsers.add_parser("create-vms", help="Create VMs only")

    # setup-infra command
    subparsers.add_parser("setup-infra", help="Setup infrastructure only")

    # config command
    subparsers.add_parser("config", help="Show current configuration")

    # bootstrap command - clone bootstrap and update templates only
    bootstrap_parser = subparsers.add_parser(
        "bootstrap",
        help="Bootstrap only - setup infra, create VMs, clone bootstrap, update templates"
    )
    bootstrap_parser.add_argument(
        "--skip-validation",
        action="store_true",
        help="Skip pre-flight validation",
    )

    # mcc command - deploy MCC and wait until ready
    subparsers.add_parser("mcc", help="Deploy MCC cluster and wait until ready")

    # mosk command - deploy MOSK (requires MCC ready)
    mosk_parser = subparsers.add_parser("mosk", help="Deploy MOSK cluster (requires MCC to be ready)")
    mosk_parser.add_argument(
        "--force",
        action="store_true",
        help="Skip MCC ready check and proceed with MOSK deployment",
    )

    # all command - complete deployment
    all_parser = subparsers.add_parser("all", help="Run complete deployment - bootstrap, MCC, and MOSK")
    all_parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from previous state",
    )
    all_parser.add_argument(
        "--skip-validation",
        action="store_true",
        help="Skip pre-flight validation",
    )

    args = parser.parse_args()

    # Handle remote execution
    if args.host:
        local_dir = str(Path(__file__).parent.absolute())

        # Sync files unless --no-sync
        if not args.no_sync:
            if not sync_to_remote(args.host, local_dir, args.verbose):
                return 1

            if not install_remote_deps(args.host, args.verbose):
                return 1

        # If --sync-only, we're done
        if args.sync_only:
            print("Sync completed successfully")
            return 0

        # Run command remotely if specified
        if not args.command:
            print("No command specified. Use --sync-only or specify a command.")
            parser.print_help()
            return 1

        # Build extra args for the remote command
        extra_args = []
        if args.command in ("deploy", "all"):
            if hasattr(args, 'resume') and args.resume:
                extra_args.append("--resume")
            if hasattr(args, 'skip_validation') and args.skip_validation:
                extra_args.append("--skip-validation")
        elif args.command == "bootstrap":
            if hasattr(args, 'skip_validation') and args.skip_validation:
                extra_args.append("--skip-validation")
        elif args.command == "cleanup":
            if hasattr(args, 'full') and args.full:
                extra_args.append("--full")

        return run_remote_command(args.host, args.command, extra_args, args.verbose)

    # Local execution
    if not args.command:
        parser.print_help()
        return 1

    commands = {
        "deploy": cmd_deploy,
        "validate": cmd_validate,
        "status": cmd_status,
        "cleanup": cmd_cleanup,
        "create-vms": cmd_create_vms,
        "setup-infra": cmd_setup_infra,
        "config": cmd_show_config,
        "bootstrap": cmd_bootstrap,
        "mcc": cmd_mcc,
        "mosk": cmd_mosk,
        "all": cmd_all,
    }

    return commands[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
