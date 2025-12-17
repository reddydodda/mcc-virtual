"""
Deployment Orchestrator Module

Main orchestrator for MCC/MOSK deployment with resume capability.
"""

import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from .config import Config
from .infrastructure import InfrastructureManager
from .logger import DeploymentLogger, setup_logging
from .state import DeploymentPhase, StateManager
from .templates import TemplateGenerator
from .utils import (
    CommandError,
    compare_versions,
    kubectl_apply,
    kubectl_command,
    kubectl_get_json,
    run_command,
    run_command_output,
    wait_for_condition,
)
from .validation import PreflightValidator
from .vm_manager import VMManager


def _validate_version_string(version: str) -> bool:
    """Validate version string format to prevent injection."""
    return bool(re.match(r'^[0-9]+\.[0-9]+\.[0-9]+$', version))


def _validate_namespace(namespace: str) -> bool:
    """Validate Kubernetes namespace format."""
    return bool(re.match(r'^[a-z0-9]([a-z0-9-]*[a-z0-9])?$', namespace))


class Deployer:
    """Main deployment orchestrator for MCC/MOSK."""

    def __init__(self, config_path: str = "config.yaml", resume: bool = False):
        from datetime import datetime

        self.config = Config(config_path)

        # Determine deployment directory
        if resume:
            # Try to find existing deployment to resume
            latest_deployment = self.config.find_latest_deployment()
            if latest_deployment:
                self.deployment_dir = latest_deployment
                # Extract deployment_id from directory name
                self.deployment_id = latest_deployment.name.replace(f"{self.config.deployment_name}_", "")
            else:
                # No previous deployment found, create new
                self.deployment_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
                self.deployment_dir = self.config.create_deployment_dir(self.deployment_id)
        else:
            # Create new deployment directory
            self.deployment_id = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            self.deployment_dir = self.config.create_deployment_dir(self.deployment_id)

        # Initialize state manager with deployment directory
        self.state = StateManager(
            state_file=self.config.state_file,
            deployment_dir=self.deployment_dir,
            backup_on_change=True
        )

        # Setup logging with deployment directory
        setup_logging(
            level=self.config.log_level,
            log_file=self.config.log_file,
            log_format=self.config.log_format,
            deployment_dir=self.deployment_dir,
        )

        self.log = DeploymentLogger("deployer")
        self.log.progress(f"Deployment directory: {self.deployment_dir}")

        self.infrastructure = InfrastructureManager(self.config, self.state, self.log)
        self.vm_manager = VMManager(self.config, self.state, self.log)
        self.templates = TemplateGenerator(self.config, self.state, self.vm_manager, self.log)
        self.validator = PreflightValidator(self.config, self.log)

    def deploy(self, skip_validation: bool = False, resume: bool = False) -> None:
        """Run complete deployment."""
        self.log.phase_start("deployment", "Starting MCC/MOSK deployment")

        try:
            if resume and self.state.can_resume():
                resume_phase = self.state.get_resume_phase()
                self.log.progress(f"Resuming from phase: {resume_phase.name_str}")
            else:
                if self.state.can_resume():
                    self.log.warning("Previous deployment found. Use --resume to continue or --clean to start fresh.")
                    return
                self.state.reset()

            if not skip_validation:
                self._run_validation()

            self._run_infrastructure()
            self._run_vm_creation()
            self._run_bootstrap_preparation()
            self._run_mcc_bootstrap()
            self._run_mcc_deployment()
            self._run_mosk_deployment()
            self._run_openstack_deployment()

            self.state.mark_completed()
            self.log.phase_complete("deployment")
            self._print_summary()

        except Exception as e:
            self.log.error(f"Deployment failed: {e}")
            self.state.mark_failed(str(e))
            raise

    def _run_validation(self) -> None:
        """Run pre-flight validation."""
        if self.state.is_step_completed("validation"):
            self.log.step_skipped("validation", "Already completed")
            return

        self.state.start_step("validation")
        try:
            self.validator.validate(fail_on_critical=True)
            self.validator.print_summary()
            self.state.complete_step("validation")
        except Exception as e:
            self.state.fail_step("validation", str(e))
            raise

    def _run_infrastructure(self) -> None:
        """Run infrastructure setup."""
        current_phase = self.state.get_phase()
        # Skip if we're past the VM_CREATION phase (infrastructure is complete)
        if current_phase >= DeploymentPhase.VM_CREATION:
            self.log.step_skipped("infrastructure", "Already completed")
            return
        self.infrastructure.setup_all()

    def _run_vm_creation(self) -> None:
        """Run VM creation."""
        current_phase = self.state.get_phase()
        # Skip if we're past the BOOTSTRAP_DOWNLOAD phase (VMs are created)
        if current_phase >= DeploymentPhase.BOOTSTRAP_DOWNLOAD:
            self.log.step_skipped("vm_creation", "Already completed")
            return
        self.vm_manager.create_all_vms()

    def _run_bootstrap_preparation(self) -> None:
        """Download and prepare MCC bootstrap."""
        step_name = "bootstrap_preparation"
        if self.state.is_step_completed(step_name):
            self.log.step_skipped(step_name, "Already completed")
            return

        self.log.phase_start("bootstrap_preparation", "Preparing MCC bootstrap")
        self.state.set_phase(DeploymentPhase.BOOTSTRAP_DOWNLOAD)
        self.state.start_step(step_name)

        try:
            base_dir = Path(self.config.base_dir)
            bootstrap_dir = base_dir / "kaas-bootstrap"

            # Early license validation - fail fast if license is missing
            license_src = base_dir / self.config.license_file
            if not license_src.exists():
                raise FileNotFoundError(
                    f"License file required but not found: {license_src}. "
                    f"Please place your mirantis.lic file in {base_dir}"
                )

            if bootstrap_dir.exists():
                backup_name = f"kaas-bootstrap-{time.strftime('%Y%m%d_%H%M%S')}"
                shutil.move(str(bootstrap_dir), str(base_dir / backup_name))
                self.log.progress(f"Backed up existing bootstrap to {backup_name}")

            self.log.progress("Downloading MCC bootstrap")
            run_command(
                "wget -q https://binary.mirantis.com/releases/get_container_cloud.sh",
                cwd=str(base_dir),
                timeout=120,
            )
            run_command("chmod 0755 get_container_cloud.sh", cwd=str(base_dir))

            if self.config.mcc_version:
                mcc_version = self.config.mcc_version

                # Validate version format to prevent injection
                if not _validate_version_string(mcc_version):
                    raise ValueError(f"Invalid MCC version format: {mcc_version}. Expected format: X.Y.Z")

                self.log.progress(f"Using specified MCC version: {mcc_version}")

                # Use safe URL construction
                release_yaml_url = f"https://binary.mirantis.com/releases/kaas/{mcc_version}.yaml"
                release_yaml_path = base_dir / f"kaas-{mcc_version}.yaml"
                self.log.progress(f"Downloading release YAML from {release_yaml_url}")

                # Download with validated version
                run_command(
                    ["wget", "-q", release_yaml_url, "-O", str(release_yaml_path)],
                    cwd=str(base_dir),
                    timeout=120,
                )

                release_content = release_yaml_path.read_text()
                cluster_releases = set()
                critical_releases = set()

                for line in release_content.split("\n"):
                    if "clusterRelease:" in line:
                        cr = line.split(":", 1)[1].strip()
                        if cr and _validate_version_string(cr):
                            cluster_releases.add(cr)
                            critical_releases.add(cr)
                    elif "- " in line and any(c.isdigit() for c in line):
                        cr = line.strip().lstrip("- ").strip()
                        if cr and cr[0].isdigit() and _validate_version_string(cr):
                            cluster_releases.add(cr)

                cluster_releases_dir = base_dir / "releases" / "cluster"
                cluster_releases_dir.mkdir(parents=True, exist_ok=True)

                common_releases = [
                    "17.4.0", "17.4.6", "21.0.0", "21.0.1", "21.0.2", "21.0.3",
                    "16.4.0", "16.4.6", "20.0.0", "20.0.1", "20.0.2", "20.0.3"
                ]
                for cr in common_releases:
                    cluster_releases.add(cr)

                self.log.progress(f"Downloading {len(cluster_releases)} cluster releases...")
                failed_critical = []

                for cr in cluster_releases:
                    if not _validate_version_string(cr):
                        self.log.warning(f"Skipping invalid cluster release version: {cr}")
                        continue

                    cluster_url = f"https://binary.mirantis.com/releases/cluster/{cr}.yaml"
                    cluster_path = cluster_releases_dir / f"{cr}.yaml"
                    try:
                        run_command(
                            ["wget", "-q", cluster_url, "-O", str(cluster_path)],
                            cwd=str(base_dir),
                            timeout=60,
                        )
                    except Exception as e:
                        if cr in critical_releases:
                            failed_critical.append(cr)
                            self.log.error(f"Failed to download critical cluster release {cr}: {e}")
                        else:
                            self.log.warning(f"Failed to download cluster release {cr}: {e}")

                # Fail if critical releases couldn't be downloaded
                if failed_critical:
                    raise RuntimeError(
                        f"Failed to download critical cluster releases: {failed_critical}. "
                        "These are required for the specified MCC version."
                    )

                env_vars = {
                    "KAAS_RELEASE_YAML": str(release_yaml_path),
                    "CLUSTER_RELEASES_DIR": str(cluster_releases_dir),
                }
                self.log.progress("Running get_container_cloud.sh with specified version...")
                run_command(
                    "./get_container_cloud.sh",
                    cwd=str(base_dir),
                    timeout=600,
                    env=env_vars,
                )

                self._verify_bootstrap_version(mcc_version, fail_on_mismatch=True)
            else:
                self.log.progress("Downloading latest MCC version...")
                run_command("./get_container_cloud.sh", cwd=str(base_dir), timeout=600)

            self._detect_versions()
            self._update_bootstrap_env()

            license_dst = bootstrap_dir / "mirantis.lic"
            shutil.copy(license_src, license_dst)
            self.log.progress("Copied license file")

            kubectl_src = bootstrap_dir / "bin" / "kubectl"
            if kubectl_src.exists():
                run_command(
                    ["sudo", "install", "-o", "root", "-g", "root", "-m", "0755",
                     str(kubectl_src), "/usr/local/bin/kubectl"]
                )
                self.log.progress("Installed kubectl")

            self.templates.update_templates_with_config()
            (base_dir / "get_container_cloud.sh").unlink(missing_ok=True)

            self.state.complete_step(step_name)
            self.log.phase_complete("bootstrap_preparation")

        except Exception as e:
            self.state.fail_step(step_name, str(e))
            self.log.phase_failed("bootstrap_preparation", str(e))
            raise

    def _detect_versions(self) -> None:
        """Detect MCC/MOSK versions from downloaded bootstrap."""
        self.log.progress("Detecting MCC versions")

        base_dir = Path(self.config.base_dir)
        env_file = base_dir / "kaas-bootstrap" / "bootstrap.env"
        kaas_release_yaml = None

        if env_file.exists():
            for line in env_file.read_text().split("\n"):
                if line.startswith("KAAS_RELEASE_YAML="):
                    kaas_release_yaml = Path(line.split("=", 1)[1].strip())
                    break

        if not kaas_release_yaml or not kaas_release_yaml.exists():
            releases_dir = base_dir / "kaas-bootstrap" / "releases" / "kaas"
            if not releases_dir.exists():
                raise FileNotFoundError(f"Releases directory not found: {releases_dir}")
            yaml_files = sorted(releases_dir.glob("*.yaml"), key=lambda f: f.name, reverse=True)
            if not yaml_files:
                raise FileNotFoundError("No release YAML files found")
            kaas_release_yaml = yaml_files[0]

        latest_yaml = kaas_release_yaml
        version_str = latest_yaml.stem.replace("kaas-", "")

        if compare_versions(version_str, self.config.mcc_minimum_version) < 0:
            raise ValueError(
                f"MCC version {version_str} is below minimum required {self.config.mcc_minimum_version}"
            )

        mcc_kaas_release = f"kaas-{version_str.replace('.', '-')}"
        self.state.set_version("mcc_kaas_release", mcc_kaas_release)
        self.log.progress(f"MCC KaaS Release: {mcc_kaas_release}")

        content = latest_yaml.read_text()
        for line in content.split("\n"):
            if "clusterRelease" in line:
                parts = line.split(":")
                if len(parts) >= 2:
                    mcc_cluster_release = parts[1].strip()
                    self.state.set_version("mcc_cluster_release", mcc_cluster_release)
                    self.log.progress(f"MCC Cluster Release: {mcc_cluster_release}")
                    break

    def _verify_bootstrap_version(self, expected_version: str, fail_on_mismatch: bool = True) -> None:
        """Verify that the downloaded bootstrap matches the expected MCC version."""
        base_dir = Path(self.config.base_dir)
        bootstrap_dir = base_dir / "kaas-bootstrap"
        env_file = bootstrap_dir / "bootstrap.env"
        downloaded_version = None

        if env_file.exists():
            for line in env_file.read_text().split("\n"):
                if line.startswith("KAAS_RELEASE_YAML="):
                    yaml_path = line.split("=", 1)[1].strip()
                    if "kaas-" in yaml_path:
                        filename = Path(yaml_path).stem
                        downloaded_version = filename.replace("kaas-", "")
                    break

        if not downloaded_version:
            releases_dir = bootstrap_dir / "releases" / "kaas"
            if releases_dir.exists():
                yaml_files = list(releases_dir.glob("*.yaml"))
                for yf in yaml_files:
                    if expected_version in yf.name:
                        downloaded_version = expected_version
                        break
                if not downloaded_version and yaml_files:
                    downloaded_version = yaml_files[0].stem.replace("kaas-", "")

        if downloaded_version:
            if downloaded_version == expected_version:
                self.log.progress(f"Verified: Downloaded MCC version {downloaded_version} matches expected")
            else:
                msg = f"Version mismatch: Expected {expected_version}, got {downloaded_version}"
                if fail_on_mismatch:
                    raise ValueError(msg)
                self.log.warning(msg)
        else:
            msg = "Could not verify downloaded MCC version"
            if fail_on_mismatch:
                raise ValueError(msg)
            self.log.warning(msg)

    def _update_bootstrap_env(self) -> None:
        """Update bootstrap.env with bare metal configuration."""
        env_file = Path(self.config.base_dir) / "kaas-bootstrap" / "bootstrap.env"

        if not env_file.exists():
            raise FileNotFoundError(f"bootstrap.env not found: {env_file}")

        bm_config = f"""
export KAAS_BM_ENABLED="true"
export KAAS_BM_PXE_IP="{self.config.bootstrap_pxe_ip}"
export KAAS_BM_PXE_MASK="{self.config.bootstrap_pxe_mask}"
export KAAS_BM_PXE_BRIDGE="{self.config.bootstrap_pxe_bridge}"
"""

        with env_file.open("a") as f:
            f.write(bm_config)

        self.log.progress("Updated bootstrap.env with bare metal configuration")

    def _run_mcc_bootstrap(self) -> None:
        """Run MCC bootstrap to create Kind cluster."""
        step_name = "mcc_bootstrap"
        if self.state.is_step_completed(step_name):
            self.log.step_skipped(step_name, "Already completed")
            return

        self.log.phase_start("mcc_bootstrap", "Running MCC bootstrap")
        self.state.set_phase(DeploymentPhase.MCC_BOOTSTRAP)
        self.state.start_step(step_name)

        try:
            base_dir = Path(self.config.base_dir)
            bootstrap_dir = base_dir / "kaas-bootstrap"

            snap_bin = Path("/snap/bin")
            kind_symlink = snap_bin / "kind"
            bootstrap_kind = bootstrap_dir / "bin" / "kind"
            if not kind_symlink.exists() and bootstrap_kind.exists():
                snap_bin.mkdir(parents=True, exist_ok=True)
                run_command(["ln", "-sf", str(bootstrap_kind), str(kind_symlink)])
                self.log.progress("Created kind symlink at /snap/bin/kind")

            self.log.progress("Running bootstrap.sh bootstrapv2 to create Kind cluster")
            run_command(
                "./bootstrap.sh bootstrapv2",
                cwd=str(bootstrap_dir),
                timeout=3600,
                check=False,
            )

            kind_kubeconfig = Path.home() / ".kube" / "kind-config-clusterapi"
            if not kind_kubeconfig.exists():
                raise RuntimeError("Bootstrap failed - Kind kubeconfig not created")

            self.log.progress("Verifying Kind cluster is accessible")
            run_command(
                ["kubectl", "--kubeconfig", str(kind_kubeconfig), "get", "nodes"],
                timeout=60,
            )

            mcc_crds_installed = False
            try:
                output = run_command_output(
                    ["kubectl", "--kubeconfig", str(kind_kubeconfig),
                     "get", "crd", "bootstrapregions.kaas.mirantis.com"],
                    timeout=30,
                )
                if "bootstrapregions.kaas.mirantis.com" in output:
                    mcc_crds_installed = True
                    self.log.progress("MCC CRDs already installed, skipping bootstrap create")
            except Exception:
                pass

            if not mcc_crds_installed:
                self.log.progress("Installing MCC components with container-cloud bootstrap create")

                env_file = bootstrap_dir / "bootstrap.env"
                kaas_release_yaml = None
                cluster_releases_dir = None
                cdn_region = "public"

                if env_file.exists():
                    for line in env_file.read_text().split("\n"):
                        line = line.strip()
                        if line.startswith("KAAS_RELEASE_YAML="):
                            kaas_release_yaml = line.split("=", 1)[1].strip()
                        elif line.startswith("CLUSTER_RELEASES_DIR="):
                            cluster_releases_dir = line.split("=", 1)[1].strip()
                        elif line.startswith("KAAS_CDN_REGION="):
                            cdn_region = line.split("=", 1)[1].strip()

                if not kaas_release_yaml:
                    releases_dir = bootstrap_dir / "releases" / "kaas"
                    if releases_dir.exists():
                        yaml_files = sorted(releases_dir.glob("*.yaml"), key=lambda f: f.name, reverse=True)
                        if yaml_files:
                            kaas_release_yaml = str(yaml_files[0])

                if not cluster_releases_dir:
                    cluster_releases_dir = str(bootstrap_dir / "releases" / "cluster")

                # Build command as list to avoid shell injection
                cc_cmd = [
                    "./container-cloud", "bootstrap", "create", "--v2",
                    "--use-existing-kind=true",
                    "--bootstrap-cluster-name", "clusterapi",
                    "--private-key-path", "ssh_key",
                    "--cdn-region", cdn_region,
                ]
                if kaas_release_yaml:
                    cc_cmd.extend(["--kaas-release-yaml", kaas_release_yaml])
                if cluster_releases_dir:
                    cc_cmd.extend(["--cluster-release-dir", cluster_releases_dir])

                run_command(
                    cc_cmd,
                    cwd=str(bootstrap_dir),
                    env={"KUBECONFIG": str(kind_kubeconfig)},
                    timeout=1800,
                )

                self.log.progress("Waiting for MCC CRDs to be installed...")
                self._wait_for_crd(
                    "bootstrapregions.kaas.mirantis.com",
                    str(kind_kubeconfig),
                    timeout=600,
                )
                self.log.progress("MCC CRDs are ready")

            self._apply_license(str(kind_kubeconfig))
            self.state.set_kubeconfig("kind", str(kind_kubeconfig))

            self.state.complete_step(step_name)
            self.log.phase_complete("mcc_bootstrap")

        except Exception as e:
            self.state.fail_step(step_name, str(e))
            self.log.phase_failed("mcc_bootstrap", str(e))
            raise

    def _wait_for_crd(self, crd_name: str, kubeconfig: str, timeout: int = 6000) -> None:
        """Wait for a CRD to be installed."""
        def check() -> Tuple[bool, str]:
            try:
                output = run_command_output(
                    ["kubectl", "--kubeconfig", kubeconfig, "get", "crd", crd_name],
                    timeout=30,
                )
                if crd_name in output:
                    return True, "CRD installed"
                return False, "CRD not found"
            except Exception as e:
                return False, str(e)

        wait_for_condition(
            check,
            f"CRD {crd_name}",
            timeout=timeout,
            interval=10,
            progress_fn=lambda s: self.log.progress(f"Waiting for CRD: {s}"),
        )

    def _apply_license(self, kubeconfig: str) -> None:
        """Apply MCC license to the Kind cluster."""
        self.log.progress("Checking license status...")

        try:
            run_command_output(
                ["kubectl", "--kubeconfig", kubeconfig, "get", "crd", "licenses.kaas.mirantis.com"],
                timeout=30,
            )
        except Exception:
            self.log.progress("License CRD not yet available, waiting...")
            self._wait_for_crd("licenses.kaas.mirantis.com", kubeconfig, timeout=120)

        try:
            output = run_command_output(
                ["kubectl", "--kubeconfig", kubeconfig, "get", "license", "license", "-o", "name"],
                timeout=30,
            )
            if "license" in output:
                self.log.progress("License already applied")
                return
        except Exception:
            pass

        self.log.progress("Applying license...")
        base_dir = Path(self.config.base_dir)
        bootstrap_dir = base_dir / "kaas-bootstrap"

        try:
            run_command(
                ["./container-cloud", "bootstrap", "license", "apply", "--license-file", "mirantis.lic"],
                cwd=str(bootstrap_dir),
                env={"KUBECONFIG": kubeconfig},
                timeout=120,
            )
            self.log.progress("License applied successfully")
        except Exception as e:
            self.log.warning(f"container-cloud license apply failed: {e}")
            self.log.progress("Attempting direct license application...")

            license_file = bootstrap_dir / "mirantis.lic"
            if not license_file.exists():
                raise RuntimeError(f"License file not found: {license_file}")

            license_content = license_file.read_text().strip()

            # Use yaml.safe_dump for secure YAML generation
            license_data = {
                "apiVersion": "kaas.mirantis.com/v1alpha1",
                "kind": "License",
                "metadata": {"name": "license"},
                "spec": {"license": license_content},
            }

            license_yaml = bootstrap_dir / "license-cr.yaml"
            license_yaml.write_text(yaml.safe_dump(license_data, default_flow_style=False))

            run_command(
                ["kubectl", "--kubeconfig", kubeconfig, "apply", "-f", str(license_yaml)],
                timeout=60,
            )
            self.log.progress("License applied via kubectl")

    def _is_mgmt_cluster_accessible(self, kubeconfig_path: str) -> bool:
        """Check if management cluster is accessible and ready."""
        try:
            if not Path(kubeconfig_path).exists():
                return False
            output = run_command_output(
                ["kubectl", "--kubeconfig", kubeconfig_path, "get", "cluster", "-o", "json"],
                timeout=30,
            )
            data = json.loads(output)
            items = data.get("items", [data]) if "items" in data else [data]
            for item in items:
                # Check status.providerStatus.ready (MCC cluster structure)
                provider_status = item.get("status", {}).get("providerStatus", {})
                if provider_status.get("ready") is True:
                    return True
                # Fallback: check status.ready for other cluster types
                if item.get("status", {}).get("ready") is True:
                    return True
            return False
        except Exception:
            return False

    def _regenerate_mgmt_kubeconfig(self, bootstrap_dir: Path) -> Optional[Path]:
        """Regenerate management cluster kubeconfig using container-cloud.

        This is used during resume when the kubeconfig file is missing but
        the cluster is accessible via the Kind cluster or other means.
        """
        self.log.progress("Attempting to regenerate management cluster kubeconfig...")

        kind_kubeconfig = Path.home() / ".kube" / "kind-config-clusterapi"
        mgmt_kubeconfig = (bootstrap_dir / f"kubeconfig-{self.config.mcc_cluster_name}").resolve()

        # First try using Kind cluster if available
        if kind_kubeconfig.exists():
            try:
                self.log.progress("Trying to generate kubeconfig via Kind cluster...")
                run_command(
                    ["./container-cloud", "get", "cluster-kubeconfig",
                     "--kubeconfig", str(kind_kubeconfig),
                     "--cluster-name", self.config.mcc_cluster_name],
                    cwd=str(bootstrap_dir),
                    timeout=120,
                )
                if mgmt_kubeconfig.exists():
                    self.log.progress(f"Successfully regenerated kubeconfig at: {mgmt_kubeconfig}")
                    return mgmt_kubeconfig
            except Exception as e:
                self.log.warning(f"Could not regenerate via Kind: {e}")

        # Try extracting from the management cluster directly using kubectl
        try:
            self.log.progress("Trying to extract kubeconfig from cluster secret...")
            # Get the kubeconfig from the cluster secret
            output = run_command_output(
                ["kubectl", "get", "secret",
                 f"{self.config.mcc_cluster_name}-kubeconfig",
                 "-o", "jsonpath={.data.admin\\.conf}"],
                timeout=60,
            )
            if output:
                import base64
                kubeconfig_content = base64.b64decode(output).decode("utf-8")
                mgmt_kubeconfig.write_text(kubeconfig_content)
                self.log.progress(f"Successfully extracted kubeconfig to: {mgmt_kubeconfig}")
                return mgmt_kubeconfig
        except Exception as e:
            self.log.warning(f"Could not extract kubeconfig from secret: {e}")

        return None

    def _run_mcc_deployment(self) -> None:
        """Deploy MCC management cluster."""
        self.log.phase_start("mcc_deployment", "Deploying MCC management cluster")
        self.state.set_phase(DeploymentPhase.MCC_DEPLOYMENT)

        try:
            base_dir = Path(self.config.base_dir)
            bootstrap_dir = base_dir / "kaas-bootstrap"
            kind_kubeconfig = self.state.get_kubeconfig("kind")

            if not kind_kubeconfig:
                kind_kubeconfig = str(Path.home() / ".kube" / "kind-config-clusterapi")

            # Check if management cluster is already accessible (resume scenario)
            # Try multiple possible kubeconfig locations (use absolute paths)
            possible_kubeconfigs = [
                (bootstrap_dir / f"kubeconfig-{self.config.mcc_cluster_name}").resolve(),
                (base_dir / f"kubeconfig-{self.config.mcc_cluster_name}").resolve(),
                Path.home() / f"kubeconfig-{self.config.mcc_cluster_name}",
                Path(f"/root/kubeconfig-{self.config.mcc_cluster_name}"),
            ]

            # Also check state for previously saved kubeconfig
            saved_kubeconfig = self.state.get_kubeconfig("mcc")
            if saved_kubeconfig:
                possible_kubeconfigs.insert(0, Path(saved_kubeconfig).resolve())

            mgmt_kubeconfig = None
            for kc_path in possible_kubeconfigs:
                self.log.progress(f"Checking for kubeconfig at: {kc_path}")
                if kc_path.exists() and self._is_mgmt_cluster_accessible(str(kc_path)):
                    mgmt_kubeconfig = kc_path.resolve()  # Always use absolute path
                    self.log.progress(f"Found accessible management cluster kubeconfig: {mgmt_kubeconfig}")
                    break

            # If no kubeconfig found, try to regenerate it
            if mgmt_kubeconfig is None:
                self.log.progress("No existing kubeconfig found, attempting to regenerate...")
                mgmt_kubeconfig = self._regenerate_mgmt_kubeconfig(bootstrap_dir)

            if mgmt_kubeconfig and self._is_mgmt_cluster_accessible(str(mgmt_kubeconfig)):
                self.log.progress("Management cluster already accessible - skipping Kind-based operations")
                self.state.set_kubeconfig("mcc", str(mgmt_kubeconfig))

                # Skip directly to post-pivot verification
                self.log.progress("Verifying management cluster is ready...")
                self._wait_for_resource_json(
                    "cluster", "status.providerStatus.ready", True,
                    kubeconfig=str(mgmt_kubeconfig),
                    timeout=self.config.timeout_cluster_ready,
                )

                # Get Keycloak credentials if not already done
                keycloak_file = base_dir / "keycloak.yaml"
                if not keycloak_file.exists():
                    self.log.progress("Getting Keycloak credentials")
                    keycloak_output = run_command_output(
                        ["./container-cloud", "get", "keycloak-creds",
                         "--mgmt-kubeconfig", str(mgmt_kubeconfig)],
                        cwd=str(bootstrap_dir),
                        timeout=120,
                    )
                    keycloak_file.write_text(keycloak_output)

                self.state.set_phase(DeploymentPhase.MCC_READY)

                # Clean up Kind cluster if it still exists
                kind_bin = bootstrap_dir / "bin" / "kind"
                if kind_bin.exists():
                    self.log.progress("Cleaning up Kind bootstrap cluster if present")
                    run_command(
                        [str(kind_bin), "delete", "cluster", "-n", "clusterapi"],
                        check=False,
                        timeout=120,
                    )

                self.log.phase_complete("mcc_deployment")
                return

            # If we didn't find an accessible mgmt kubeconfig, set the expected path for later
            # container-cloud generates kubeconfig in cwd (bootstrap_dir), use absolute path
            if mgmt_kubeconfig is None:
                mgmt_kubeconfig = (bootstrap_dir / f"kubeconfig-{self.config.mcc_cluster_name}").resolve()

            templates = [
                "mcc/bootstrapregion.yaml.template",
                "mcc/serviceusers.yaml.template",
                "mcc/cluster.yaml.template",
                "mcc/baremetalhostprofiles.yaml.template",
                "mcc/baremetalhosts.yaml.template",
                "mcc/metallbconfig.yaml.template",
                "mcc/machines.yaml.template",
                "mcc/ipam-objects.yaml.template",
            ]

            for template in templates:
                step_name = f"apply_{template.replace('/', '_')}"
                if self.state.should_run_step(step_name):
                    self.log.step_start(step_name)
                    self.state.start_step(step_name)

                    template_path = base_dir / template
                    if template_path.exists():
                        kubectl_apply(str(template_path), kubeconfig=kind_kubeconfig)
                        self.state.complete_step(step_name)
                        self.log.step_complete(step_name)
                    else:
                        self.state.skip_step(step_name, "File not found")
                        self.log.step_skipped(step_name, "File not found")

            self._wait_for_resource_json(
                "bootstrapregions", "status.ready", True,
                kubeconfig=kind_kubeconfig,
                timeout=self.config.timeout_cluster_ready,
            )

            self._wait_for_bmh_state(
                "available",
                kubeconfig=kind_kubeconfig,
                timeout=self.config.timeout_bmh_available,
            )

            self.log.progress("Approving bootstrap changes")
            run_command(
                ["./container-cloud", "bootstrap", "approve", "all"],
                cwd=str(bootstrap_dir),
                env={"KUBECONFIG": kind_kubeconfig},
                timeout=300,
            )

            self.state.set_phase(DeploymentPhase.MCC_PROVISIONING)
            self._wait_for_bmh_state(
                "provisioned",
                kubeconfig=kind_kubeconfig,
                timeout=self.config.timeout_bmh_provisioned,
            )

            # Replace hardcoded sleep with condition-based wait for LCM stabilization
            self.log.progress("Waiting for LCM machines to stabilize...")
            self._wait_for_lcm_stabilization(kind_kubeconfig, min_stable_checks=3)

            self._wait_for_machines_ready(
                kubeconfig=kind_kubeconfig,
                timeout=self.config.timeout_machine_ready,
            )

            self.log.progress("Generating management cluster kubeconfig")
            run_command(
                ["./container-cloud", "get", "cluster-kubeconfig",
                 "--kubeconfig", kind_kubeconfig,
                 "--cluster-name", self.config.mcc_cluster_name],
                cwd=str(bootstrap_dir),
                timeout=120,
            )

            self.state.set_kubeconfig("mcc", str(mgmt_kubeconfig))

            self.log.progress("Waiting for cluster to be ready...")
            self._wait_for_resource_json(
                "cluster", "status.providerStatus.ready", True,
                kubeconfig=kind_kubeconfig,
                timeout=self.config.timeout_cluster_ready,
            )

            self._wait_for_pivot_completion(kind_kubeconfig)

            self.log.progress("Verifying management cluster is accessible...")
            self._wait_for_resource_json(
                "cluster", "status.providerStatus.ready", True,
                kubeconfig=str(mgmt_kubeconfig),
                timeout=6000,
            )

            self.log.progress("Getting Keycloak credentials")
            keycloak_output = run_command_output(
                ["./container-cloud", "get", "keycloak-creds",
                 "--mgmt-kubeconfig", str(mgmt_kubeconfig)],
                cwd=str(bootstrap_dir),
                timeout=120,
            )
            (base_dir / "keycloak.yaml").write_text(keycloak_output)

            self.state.set_phase(DeploymentPhase.MCC_READY)

            self.log.progress("Deleting Kind bootstrap cluster")
            kind_bin = bootstrap_dir / "bin" / "kind"
            run_command(
                [str(kind_bin), "delete", "cluster", "-n", "clusterapi"],
                check=False,
                timeout=120,
            )

            self.log.phase_complete("mcc_deployment")

        except Exception as e:
            self.log.phase_failed("mcc_deployment", str(e))
            raise

    def _wait_for_lcm_stabilization(
        self,
        kubeconfig: str,
        min_stable_checks: int = 3,
        check_interval: int = 30,
        timeout: int = 6000,
    ) -> None:
        """Wait for LCM machines to stabilize (consistent Ready state)."""
        stable_count = 0
        last_states: Dict[str, str] = {}
        start_time = time.time()

        while time.time() - start_time < timeout:
            try:
                output = run_command_output(
                    ["kubectl", "--kubeconfig", kubeconfig, "get", "lcmmachines", "-o", "json"],
                    timeout=60,
                )
                data = json.loads(output)

                current_states = {}
                all_ready = True
                for item in data.get("items", []):
                    name = item.get("metadata", {}).get("name", "unknown")
                    state = item.get("status", {}).get("state", "Unknown")
                    current_states[name] = state
                    if state != "Ready":
                        all_ready = False

                if current_states == last_states and all_ready:
                    stable_count += 1
                    self.log.progress(f"LCM stable check {stable_count}/{min_stable_checks}")
                    if stable_count >= min_stable_checks:
                        self.log.progress("LCM machines stabilized")
                        return
                else:
                    stable_count = 0
                    self.log.progress(f"LCM states: {current_states}")

                last_states = current_states

            except Exception as e:
                self.log.warning(f"Error checking LCM status: {e}")
                stable_count = 0

            time.sleep(check_interval)

        raise RuntimeError(f"LCM machines did not stabilize within {timeout} seconds")

    def _wait_for_pivot_completion(self, kubeconfig: str, timeout: int = 3600) -> None:
        """Wait for the bootstrap pivot to complete with full verification.

        Checks multiple sources for pivot completion:
        1. Management cluster's Cluster object (status.providerStatus.bootstrapStatus.pivotDone)
        2. Kind cluster's BootstrapRegion (status.pivotDone)

        This handles resume scenarios where the Kind cluster may be gone but the
        management cluster is already operational.
        """
        self.log.progress("Waiting for bootstrap pivot to complete...")

        # First, check if management cluster already shows pivot complete
        # This handles resume scenarios where Kind might be gone
        base_dir = Path(self.config.base_dir)
        mgmt_kubeconfig = base_dir / f"kubeconfig-{self.config.mcc_cluster_name}"

        if mgmt_kubeconfig.exists():
            try:
                output = run_command_output(
                    ["kubectl", "--kubeconfig", str(mgmt_kubeconfig), "get", "cluster", "-o", "json"],
                    timeout=30,
                )
                data = json.loads(output)
                items = data.get("items", [data]) if "items" in data else [data]
                for item in items:
                    bootstrap_status = item.get("status", {}).get("providerStatus", {}).get("bootstrapStatus", {})
                    if bootstrap_status.get("pivotDone") is True:
                        self.log.progress("Pivot already completed (verified from management cluster)")
                        return
            except Exception as e:
                self.log.progress(f"Could not check management cluster pivot status: {e}")

        def check_pivot() -> Tuple[bool, str]:
            # First try management cluster (preferred source after pivot)
            if mgmt_kubeconfig.exists():
                try:
                    output = run_command_output(
                        ["kubectl", "--kubeconfig", str(mgmt_kubeconfig), "get", "cluster", "-o", "json"],
                        timeout=30,
                    )
                    data = json.loads(output)
                    items = data.get("items", [data]) if "items" in data else [data]
                    for item in items:
                        bootstrap_status = item.get("status", {}).get("providerStatus", {}).get("bootstrapStatus", {})
                        if bootstrap_status.get("pivotDone") is True:
                            return True, "Pivot completed (from management cluster)"
                except Exception:
                    pass  # Fall through to Kind check

            # Fall back to Kind cluster bootstrapregion check
            try:
                output = run_command_output(
                    ["kubectl", "--kubeconfig", kubeconfig, "get", "bootstrapregion", "-o", "json"],
                    timeout=60,
                )
                data = json.loads(output)
                if not data.get("items"):
                    return False, "No BootstrapRegion found"

                region = data["items"][0]
                status = region.get("status", {})
                pivot_done = status.get("pivotDone", False)
                deploy_status = status.get("deployStatus", "Unknown")

                # Check multiple conditions for robust pivot verification
                if pivot_done:
                    # Verify deployStatus is in a good state
                    good_statuses = ["DEPLOYED", "READY", "Complete"]
                    if deploy_status in good_statuses or pivot_done:
                        return True, f"Pivot completed (deployStatus={deploy_status})"
                    return False, f"Pivot done but deployStatus={deploy_status}"

                return False, f"deployStatus={deploy_status}, pivotDone={pivot_done}"
            except Exception as e:
                return False, str(e)

        wait_for_condition(
            check_pivot,
            "Bootstrap pivot completion",
            timeout=timeout,
            interval=30,
            progress_fn=lambda s: self.log.progress(f"Pivot status: {s}"),
        )

        self.log.progress("Bootstrap pivot completed successfully")

    def _is_mosk_cluster_ready(self, kubeconfig: str, namespace: str) -> bool:
        """Check if MOSK cluster is already deployed and ready."""
        try:
            output = run_command_output(
                ["kubectl", "--kubeconfig", kubeconfig, "-n", namespace,
                 "get", "cluster", "-o", "json"],
                timeout=30,
            )
            data = json.loads(output)
            items = data.get("items", [data]) if "items" in data else [data]
            for item in items:
                provider_status = item.get("status", {}).get("providerStatus", {})
                if provider_status.get("ready") is True:
                    return True
            return False
        except Exception:
            return False

    def _run_mosk_deployment(self) -> None:
        """Deploy MOSK cluster."""
        self.log.phase_start("mosk_deployment", "Deploying MOSK cluster")
        self.state.set_phase(DeploymentPhase.MOSK_SETUP)

        try:
            base_dir = Path(self.config.base_dir)
            mgmt_kubeconfig = self.state.get_kubeconfig("mcc")
            namespace = self.config.mosk_namespace

            # Fallback kubeconfig locations if state doesn't have it (use absolute paths)
            bootstrap_dir = base_dir / "kaas-bootstrap"
            if not mgmt_kubeconfig or not Path(mgmt_kubeconfig).exists():
                possible_paths = [
                    (bootstrap_dir / f"kubeconfig-{self.config.mcc_cluster_name}").resolve(),
                    (base_dir / f"kubeconfig-{self.config.mcc_cluster_name}").resolve(),
                    Path.home() / f"kubeconfig-{self.config.mcc_cluster_name}",
                    Path(f"/root/kubeconfig-{self.config.mcc_cluster_name}"),
                ]
                for p in possible_paths:
                    if p.exists():
                        mgmt_kubeconfig = str(p.resolve())
                        self.state.set_kubeconfig("mcc", mgmt_kubeconfig)
                        self.log.progress(f"Found MCC kubeconfig at: {mgmt_kubeconfig}")
                        break

            if not mgmt_kubeconfig:
                raise RuntimeError("MCC kubeconfig not found. Please run MCC deployment first.")

            # Validate namespace format
            if not _validate_namespace(namespace):
                raise ValueError(f"Invalid namespace format: {namespace}")

            # Fast-track: Check if MOSK cluster is already ready (resume scenario)
            if self._is_mosk_cluster_ready(mgmt_kubeconfig, namespace):
                self.log.progress("MOSK cluster already ready - checking for kubeconfig")
                mosk_kubeconfig_path = base_dir / "mosk.kubeconfig"
                if mosk_kubeconfig_path.exists():
                    self.state.set_kubeconfig("mosk", str(mosk_kubeconfig_path))
                else:
                    # Generate kubeconfig for already-ready cluster
                    self.log.progress("Generating MOSK kubeconfig for existing cluster")
                    mosk_kubeconfig = self._get_mosk_kubeconfig(mgmt_kubeconfig, namespace)
                    self.state.set_kubeconfig("mosk", str(mosk_kubeconfig))

                # Still need to apply MiraCeph if not done yet (resume scenario)
                mosk_dir = base_dir / "mosk"
                miraceph_step = "apply_09-miraceph"
                if not self.state.is_step_completed(miraceph_step):
                    self.log.progress("Applying MiraCeph (resume scenario)")
                    # Ensure MOSK release is detected for template context
                    if not self.state.get_version("mosk_release"):
                        self._detect_mosk_release(mgmt_kubeconfig)
                    self.templates.update_templates_with_config()
                    miraceph_path = self.templates.generate_miraceph_manifest(str(mosk_dir))
                    self._apply_template(Path(miraceph_path), mgmt_kubeconfig)
                else:
                    self.log.progress("MiraCeph already applied")

                self.state.set_phase(DeploymentPhase.MOSK_READY)
                self.log.phase_complete("mosk_deployment")
                return

            if not self.state.get_version("mosk_release"):
                self._detect_mosk_release(mgmt_kubeconfig)

            self.templates.update_templates_with_config()

            mosk_dir = base_dir / "mosk"

            # Generate MOSK templates if methods exist and templates don't already exist
            # This supports both fresh deployment and resume scenarios
            bmh_dir = mosk_dir / "03-bmh"
            machine_dir = mosk_dir / "08-machine"

            if hasattr(self.templates, 'generate_all_mosk_bmh'):
                if not bmh_dir.exists() or not list(bmh_dir.glob("*.yaml")):
                    self.templates.generate_all_mosk_bmh(str(mosk_dir), namespace)
                else:
                    self.log.progress("MOSK BMH templates already exist, skipping generation")

            if hasattr(self.templates, 'generate_all_mosk_machines'):
                if not machine_dir.exists() or not list(machine_dir.glob("*.yaml")):
                    self.templates.generate_all_mosk_machines(str(mosk_dir), namespace)
                else:
                    self.log.progress("MOSK machine templates already exist, skipping generation")

            # Note: MiraCeph is applied AFTER MOSK cluster is ready (see below)
            # This replaces deprecated KaaSCephCluster for MOSK 25.2+

            templates = [
                "mosk/01-namespace.yaml",
                "mosk/02-metallbconfig.yaml",
                "mosk/03-bmh/01-bmh-master.yaml",
                "mosk/03-bmh/02-bmh-cmp-hc.yaml",
                "mosk/04-cluster.yaml",
                "mosk/05-bmhp-ctl.yaml",
                "mosk/05-bmhp-cmp.yaml",
                "mosk/06-l2template.yaml",
                "mosk/07-subnet.yaml",
                "mosk/08-machine/01-machine-ctl.yaml",
                "mosk/08-machine/02-machine-cmp.yaml",
            ]

            self._apply_template(base_dir / "mosk/01-namespace.yaml", mgmt_kubeconfig)

            # Copy bootstrap key using JSON output to avoid shell piping
            self.log.progress("Copying bootstrap key to MOSK namespace")
            self._copy_publickey_to_namespace(mgmt_kubeconfig, "bootstrap-key", namespace)

            for template in templates[1:]:
                template_path = base_dir / template
                if template_path.exists():
                    self._apply_template(template_path, mgmt_kubeconfig)
                    time.sleep(5)

            self.state.set_phase(DeploymentPhase.MOSK_PROVISIONING)
            self._wait_for_bmh_state(
                "provisioned",
                kubeconfig=mgmt_kubeconfig,
                namespace=namespace,
                timeout=self.config.timeout_bmh_provisioned,
            )

            self._wait_for_machines_ready(
                kubeconfig=mgmt_kubeconfig,
                namespace=namespace,
                timeout=self.config.timeout_machine_ready,
            )

            self._wait_for_resource_json(
                "cluster", "status.providerStatus.ready", True,
                kubeconfig=mgmt_kubeconfig,
                namespace=namespace,
                timeout=self.config.timeout_cluster_ready,
            )

            self.log.progress("Generating MOSK kubeconfig")
            mosk_kubeconfig = self._get_mosk_kubeconfig(mgmt_kubeconfig, namespace)
            self.state.set_kubeconfig("mosk", str(mosk_kubeconfig))

            # Apply MiraCeph after MOSK cluster is ready
            # MiraCeph is applied to management cluster (ceph-lcm-mirantis namespace)
            # but needs MOSK nodes to be ready for Ceph deployment
            miraceph_step = "apply_09-miraceph"
            if not self.state.is_step_completed(miraceph_step):
                self.log.progress("Generating and applying MiraCeph manifest")
                miraceph_path = self.templates.generate_miraceph_manifest(str(mosk_dir))
                self._apply_template(Path(miraceph_path), mgmt_kubeconfig)
            else:
                self.log.progress("MiraCeph already applied, skipping")

            self.state.set_phase(DeploymentPhase.MOSK_READY)
            self.log.phase_complete("mosk_deployment")

        except Exception as e:
            self.log.phase_failed("mosk_deployment", str(e))
            raise

    def _copy_publickey_to_namespace(
        self, kubeconfig: str, key_name: str, target_namespace: str
    ) -> None:
        """Copy a publickey resource to a different namespace."""
        output = run_command_output(
            ["kubectl", "--kubeconfig", kubeconfig, "get", "publickey", key_name, "-o", "json"],
            timeout=60,
        )
        key_data = json.loads(output)

        # Modify namespace
        key_data["metadata"]["namespace"] = target_namespace
        if "resourceVersion" in key_data.get("metadata", {}):
            del key_data["metadata"]["resourceVersion"]
        if "uid" in key_data.get("metadata", {}):
            del key_data["metadata"]["uid"]

        # Write to temp file and apply
        base_dir = Path(self.config.base_dir)
        temp_file = base_dir / f"temp-publickey-{target_namespace}.yaml"
        temp_file.write_text(yaml.safe_dump(key_data))

        try:
            run_command(
                ["kubectl", "--kubeconfig", kubeconfig, "apply", "-f", str(temp_file)],
                timeout=60,
            )
        finally:
            temp_file.unlink(missing_ok=True)

    def _get_mosk_kubeconfig(self, mgmt_kubeconfig: str, namespace: str) -> Path:
        """Extract and fix MOSK kubeconfig."""
        base_dir = Path(self.config.base_dir)

        # Get the secret using JSON output
        output = run_command_output(
            ["kubectl", "--kubeconfig", mgmt_kubeconfig, "-n", namespace,
             "get", "secrets", f"{namespace}-kubeconfig",
             "-o", "jsonpath={.data.admin\\.conf}"],
            timeout=60,
        )

        import base64
        kubeconfig_content = base64.b64decode(output).decode("utf-8")

        # Parse and fix the kubeconfig using YAML
        kubeconfig_data = yaml.safe_load(kubeconfig_content)

        # Fix server port from 5443 to 443
        for cluster in kubeconfig_data.get("clusters", []):
            server = cluster.get("cluster", {}).get("server", "")
            if ":5443" in server:
                cluster["cluster"]["server"] = server.replace(":5443", ":443")

        mosk_kubeconfig = base_dir / "mosk.kubeconfig"
        mosk_kubeconfig.write_text(yaml.safe_dump(kubeconfig_data, default_flow_style=False))

        return mosk_kubeconfig

    def _is_openstack_deployed(self, kubeconfig: str) -> bool:
        """Check if OpenStack is already deployed and ready."""
        try:
            output = run_command_output(
                ["kubectl", "--kubeconfig", kubeconfig, "-n", "openstack",
                 "get", "osdplst", "-o", "json"],
                timeout=30,
            )
            data = json.loads(output)
            items = data.get("items", [data]) if "items" in data else [data]
            for item in items:
                controller = item.get("status", {}).get("controller", "")
                if controller == "APPLIED":
                    return True
            return False
        except Exception:
            return False

    def _run_openstack_deployment(self) -> None:
        """Deploy OpenStack on MOSK cluster."""
        self.log.phase_start("openstack_deployment", "Deploying OpenStack")
        self.state.set_phase(DeploymentPhase.OPENSTACK_DEPLOYMENT)

        try:
            base_dir = Path(self.config.base_dir)
            mosk_kubeconfig = self.state.get_kubeconfig("mosk")

            # Fallback kubeconfig locations if state doesn't have it (use absolute paths)
            if not mosk_kubeconfig or not Path(mosk_kubeconfig).exists():
                possible_paths = [
                    (base_dir / "mosk.kubeconfig").resolve(),
                    Path.home() / "mosk.kubeconfig",
                    Path("/root/mosk.kubeconfig"),
                ]
                for p in possible_paths:
                    if p.exists():
                        mosk_kubeconfig = str(p.resolve())
                        self.state.set_kubeconfig("mosk", mosk_kubeconfig)
                        self.log.progress(f"Found MOSK kubeconfig at: {mosk_kubeconfig}")
                        break

            if not mosk_kubeconfig:
                raise RuntimeError("MOSK kubeconfig not found. Please run MOSK deployment first.")

            # Fast-track: Check if OpenStack is already deployed (resume scenario)
            if self._is_openstack_deployed(mosk_kubeconfig):
                self.log.progress("OpenStack already deployed - skipping deployment")
                self.log.phase_complete("openstack_deployment")
                return

            self.log.progress("Waiting for Ceph cluster to be healthy")
            self._wait_for_ceph_healthy(mosk_kubeconfig)

            osdpl_dir = base_dir / "mosk" / "10-osdpl"
            self._apply_template(osdpl_dir / "osdpl-secret.yaml", mosk_kubeconfig)
            self._apply_template(osdpl_dir / "osdpl.yaml", mosk_kubeconfig)
            self._wait_for_osdpl(mosk_kubeconfig)

            self.log.phase_complete("openstack_deployment")

        except Exception as e:
            self.log.phase_failed("openstack_deployment", str(e))
            raise

    def _apply_template(self, path: Path, kubeconfig: str) -> None:
        """Apply a template with logging."""
        step_name = f"apply_{path.stem}"
        if self.state.is_step_completed(step_name):
            self.log.step_skipped(step_name, "Already applied")
            return

        self.log.step_start(step_name, f"Applying {path.name}")
        self.state.start_step(step_name)

        try:
            kubectl_apply(str(path), kubeconfig=kubeconfig)
            self.state.complete_step(step_name)
            self.log.step_complete(step_name)
        except Exception as e:
            self.state.fail_step(step_name, str(e))
            self.log.step_failed(step_name, str(e))
            raise

    def _parse_mosk_version(self, release_name: str) -> str:
        """Extract MOSK version from release name.

        Release name format: mosk-{mke-major}-{mke-minor}-{mke-patch}-{mosk-major}-{mosk-minor}[-{mosk-patch}]
        Example: mosk-21-0-3-25-2-3 -> 25.2.3
                 mosk-21-0-0-25-2 -> 25.2
        """
        # Remove 'mosk-' prefix
        parts = release_name.replace("mosk-", "").split("-")

        # First 3 parts are MKE version, rest are MOSK version
        if len(parts) >= 5:
            mosk_parts = parts[3:]  # Skip first 3 (MKE version)
            return ".".join(mosk_parts)
        elif len(parts) >= 2:
            # Fallback for unexpected formats
            return ".".join(parts)
        else:
            return release_name.replace("mosk-", "")

    def _detect_mosk_release(self, kubeconfig: str) -> None:
        """Detect MOSK release from cluster.

        If mosk_version is specified in config, use that specific version.
        Otherwise, detect and use the latest available version.
        """
        self.log.progress("Detecting MOSK release")

        output = run_command_output(
            ["kubectl", "--kubeconfig", kubeconfig, "get", "clusterreleases", "-o", "json"],
            timeout=60,
        )

        data = json.loads(output)
        mosk_releases = []
        for item in data.get("items", []):
            name = item.get("metadata", {}).get("name", "")
            if name.startswith("mosk"):
                mosk_releases.append(name)

        if not mosk_releases:
            raise ValueError("Could not detect any MOSK releases in the cluster")

        # Check if a specific MOSK version is configured
        target_version = self.config.mosk_version if hasattr(self.config, 'mosk_version') else None

        if target_version:
            # Find release matching the target version
            self.log.progress(f"Looking for MOSK version: {target_version}")
            matching_releases = []
            for release in mosk_releases:
                mosk_ver = self._parse_mosk_version(release)
                if mosk_ver.startswith(target_version) or target_version in release:
                    matching_releases.append(release)

            if matching_releases:
                # Sort and pick the latest matching release
                matching_releases.sort(
                    key=lambda x: [int(p) if p.isdigit() else p for p in self._parse_mosk_version(x).split(".")]
                )
                mosk_release = matching_releases[-1]
            else:
                self.log.warning(f"No release matching version {target_version} found, using latest")
                target_version = None  # Fall through to latest

        if not target_version:
            # Sort by MOSK version (extracted from release name) and get latest
            mosk_releases.sort(
                key=lambda x: [int(p) if p.isdigit() else 0 for p in self._parse_mosk_version(x).split(".")]
            )
            mosk_release = mosk_releases[-1]

        # Extract and validate MOSK version
        version = self._parse_mosk_version(mosk_release)
        self.log.progress(f"Selected MOSK release: {mosk_release} (version {version})")

        # Check minimum version requirement
        min_version = self.config.mosk_minimum_version
        if min_version and compare_versions(version, min_version) < 0:
            raise ValueError(
                f"MOSK version {version} is below minimum required {min_version}"
            )

        self.state.set_version("mosk_release", mosk_release)
        self.state.set_version("mosk_version", version)
        self.log.progress(f"MOSK Release: {mosk_release}")

    def _wait_for_resource_json(
        self,
        resource: str,
        json_path: str,
        expected: Any,
        kubeconfig: str,
        namespace: Optional[str] = None,
        timeout: int = 3600,
    ) -> None:
        """Wait for a resource to reach expected state using JSON parsing."""
        self.log.progress(f"Waiting for {resource} {json_path}={expected}")

        def check() -> Tuple[bool, str]:
            cmd = ["kubectl", "--kubeconfig", kubeconfig]
            if namespace:
                cmd.extend(["-n", namespace])
            cmd.extend(["get", resource, "-o", "json"])

            output = run_command_output(cmd, timeout=60)
            data = json.loads(output)

            items = data.get("items", [data]) if "items" in data else [data]
            if not items:
                return False, "No resources found"

            # Parse json_path (e.g., "status.ready")
            path_parts = json_path.split(".")

            for item in items:
                value = item
                for part in path_parts:
                    value = value.get(part, {}) if isinstance(value, dict) else None
                    if value is None:
                        break

                if value != expected:
                    return False, f"{value}"

            return True, str(expected)

        wait_for_condition(
            check,
            f"{resource} {json_path}={expected}",
            timeout=timeout,
            interval=self.config.poll_interval,
            progress_fn=lambda s: self.log.resource_waiting(resource, "", json_path, s),
        )

        self.log.resource_ready(resource, "")

    def _wait_for_resource(
        self,
        resource: str,
        column: str,
        expected: str,
        kubeconfig: str,
        namespace: Optional[str] = None,
        timeout: int = 3600,
    ) -> None:
        """Wait for a resource to reach expected state (legacy table parsing)."""
        # Delegate to JSON-based method for better reliability
        json_path_map = {
            ("READY", "true"): "status.ready",
            ("STATE", "Ready"): "status.state",
            ("STATE", "available"): "status.provisioning.state",
            ("STATE", "provisioned"): "status.provisioning.state",
            ("CONTROLLER", "APPLIED"): "status.controller",
        }

        json_path = json_path_map.get((column, expected))
        if json_path:
            expected_val: Any = True if expected == "true" else expected
            self._wait_for_resource_json(
                resource, json_path, expected_val,
                kubeconfig=kubeconfig,
                namespace=namespace,
                timeout=timeout,
            )
        else:
            # Fallback to table parsing for unmapped columns
            self._wait_for_resource_table(
                resource, column, expected,
                kubeconfig=kubeconfig,
                namespace=namespace,
                timeout=timeout,
            )

    def _wait_for_resource_table(
        self,
        resource: str,
        column: str,
        expected: str,
        kubeconfig: str,
        namespace: Optional[str] = None,
        timeout: int = 3600,
    ) -> None:
        """Wait for a resource using table output parsing (fallback)."""
        self.log.progress(f"Waiting for {resource} {column}={expected}")

        def check() -> Tuple[bool, str]:
            cmd = ["kubectl", "--kubeconfig", kubeconfig]
            if namespace:
                cmd.extend(["-n", namespace])
            cmd.extend(["get", resource, "-o", "wide"])

            output = run_command_output(cmd, timeout=60)
            lines = output.strip().split("\n")
            if len(lines) < 2:
                return False, "No resources found"

            header = lines[0].split()
            try:
                col_idx = header.index(column)
            except ValueError:
                return False, f"Column {column} not found"

            for line in lines[1:]:
                parts = line.split()
                if len(parts) > col_idx:
                    value = parts[col_idx]
                    if value != expected:
                        return False, value

            return True, expected

        wait_for_condition(
            check,
            f"{resource} {column}={expected}",
            timeout=timeout,
            interval=self.config.poll_interval,
            progress_fn=lambda s: self.log.resource_waiting(resource, "", column, s),
        )

        self.log.resource_ready(resource, "")

    def _wait_for_bmh_state(
        self,
        expected_state: str,
        kubeconfig: str,
        namespace: Optional[str] = None,
        timeout: int = 3600,
    ) -> None:
        """Wait for all BMH resources to reach expected state or a more advanced state.

        BMH state machine progression:
        available -> provisioning -> provisioned

        When resuming deployment, BMHs may have already progressed past the expected
        state. This method accepts states that are at or beyond the expected state.
        """
        # Define BMH state progression order (earlier states first)
        BMH_STATE_ORDER = ["available", "provisioning", "provisioned"]

        def state_is_at_or_beyond(current_state: str, target_state: str) -> bool:
            """Check if current_state is at or beyond target_state in the lifecycle."""
            try:
                current_idx = BMH_STATE_ORDER.index(current_state)
                target_idx = BMH_STATE_ORDER.index(target_state)
                return current_idx >= target_idx
            except ValueError:
                # Unknown state - only exact match
                return current_state == target_state

        self.log.progress(f"Waiting for BMH state>={expected_state}")

        def check() -> Tuple[bool, str]:
            cmd = ["kubectl", "--kubeconfig", kubeconfig]
            if namespace:
                cmd.extend(["-n", namespace])
            cmd.extend(["get", "bmh", "-o", "json"])

            output = run_command_output(cmd, timeout=60)
            data = json.loads(output)

            items = data.get("items", [])
            if not items:
                return False, "No BMH resources found"

            states = []
            all_satisfied = True
            for item in items:
                name = item.get("metadata", {}).get("name", "unknown")
                state = item.get("status", {}).get("provisioning", {}).get("state", "unknown")
                states.append(f"{name}={state}")
                if not state_is_at_or_beyond(state, expected_state):
                    all_satisfied = False

            if all_satisfied:
                return True, f"All BMH at or beyond {expected_state}"
            return False, ", ".join(states)

        wait_for_condition(
            check,
            f"BMH state>={expected_state}",
            timeout=timeout,
            interval=self.config.poll_interval,
            progress_fn=lambda s: self.log.progress(f"BMH status: {s}"),
        )

        self.log.resource_ready("bmh", "")

    def _wait_for_machines_ready(
        self,
        kubeconfig: str,
        namespace: Optional[str] = None,
        timeout: int = 3600,
    ) -> None:
        """Wait for all LCM machines to be ready."""
        self.log.progress("Waiting for LCM machines to be ready")

        def check() -> Tuple[bool, str]:
            cmd = ["kubectl", "--kubeconfig", kubeconfig]
            if namespace:
                cmd.extend(["-n", namespace])
            cmd.extend(["get", "lcmmachines", "-o", "json"])

            output = run_command_output(cmd, timeout=60)
            data = json.loads(output)

            items = data.get("items", [])
            if not items:
                return False, "No LCM machines found"

            # Collect ALL machine states first
            states = []
            all_ready = True
            for item in items:
                name = item.get("metadata", {}).get("name", "unknown")
                state = item.get("status", {}).get("state", "unknown")
                states.append(f"{name}={state}")
                if state != "Ready":
                    all_ready = False

            # Return all states in status message
            status_str = ", ".join(states)
            if all_ready:
                return True, f"All ready: {status_str}"
            return False, status_str

        wait_for_condition(
            check,
            "LCM machines Ready",
            timeout=timeout,
            interval=self.config.poll_interval,
            progress_fn=lambda s: self.log.progress(f"LCM status: {s}"),
        )

        self.log.resource_ready("lcmmachines", "")

    def _wait_for_ceph_healthy(self, kubeconfig: str, timeout: int = 3600) -> None:
        """Wait for Ceph cluster to be healthy.

        Accepts HEALTH_OK (fully healthy) or HEALTH_WARN (operational with warnings).
        HEALTH_ERR will continue waiting.
        """
        self.log.progress("Waiting for Ceph cluster health")
        final_health = [None]  # Use list to capture in closure

        def check() -> Tuple[bool, str]:
            try:
                # Fixed: removed -it flag that requires TTY
                output = run_command_output(
                    ["kubectl", "--kubeconfig", kubeconfig, "-n", "rook-ceph",
                     "exec", "deploy/rook-ceph-tools", "--", "ceph", "health"],
                    timeout=60,
                )
                health = output.strip()
                final_health[0] = health

                # Accept both HEALTH_OK and HEALTH_WARN
                # HEALTH_WARN means cluster is operational but has warnings
                if health == "HEALTH_OK":
                    return True, health
                elif health.startswith("HEALTH_WARN"):
                    return True, health
                else:
                    return False, health
            except Exception as e:
                return False, str(e)

        wait_for_condition(
            check,
            "Ceph HEALTH_OK or HEALTH_WARN",
            timeout=timeout,
            interval=self.config.poll_interval,
            progress_fn=lambda s: self.log.progress(f"Ceph health: {s}"),
        )

        # Log warning if cluster is in HEALTH_WARN state
        if final_health[0] and final_health[0].startswith("HEALTH_WARN"):
            self.log.warning(f"Ceph cluster has warnings: {final_health[0]}")
            self.log.warning("Proceeding with deployment - cluster is operational")

        self.log.resource_ready("ceph", "cluster")

    def _wait_for_osdpl(self, kubeconfig: str, timeout: int = 7200) -> None:
        """Wait for OpenStack deployment to complete."""
        self._wait_for_resource_json(
            "osdplst", "status.controller", "APPLIED",
            kubeconfig=kubeconfig,
            namespace="openstack",
            timeout=timeout,
        )

    def _print_summary(self) -> None:
        """Print deployment summary."""
        summary = self.state.get_summary()

        print("\n" + "=" * 60)
        print("DEPLOYMENT COMPLETE")
        print("=" * 60)
        print(f"Deployment ID: {summary['deployment_id']}")
        print(f"Started: {summary['started_at']}")
        print(f"Completed: {summary['completed_at']}")
        print()
        print("Versions:")
        for name, version in summary.get("versions", {}).items():
            print(f"  {name}: {version}")
        print()
        print("Kubeconfigs:")
        for name, path in summary.get("kubeconfigs", {}).items():
            print(f"  {name}: {path}")
        print()
        print("Next steps:")
        print("  1. Export KUBECONFIG for MOSK cluster:")
        mosk_kubeconfig = self.state.get_kubeconfig("mosk")
        print(f"     export KUBECONFIG={mosk_kubeconfig}")
        print()
        print("  2. Access OpenStack:")
        print("     kubectl -n openstack get svc keystone-api")
        print()
        print("=" * 60)

    # Public API methods

    def run_validation(self) -> None:
        """Run pre-flight validation."""
        self._run_validation()

    def clone_bootstrap(self) -> None:
        """Clone/download MCC bootstrap and prepare it."""
        self._run_bootstrap_preparation()

    def deploy_mcc(self) -> None:
        """Deploy MCC management cluster."""
        base_dir = Path(self.config.base_dir)
        bootstrap_dir = base_dir / "kaas-bootstrap"
        if not bootstrap_dir.exists():
            self.log.progress("Bootstrap not found, running preparation...")
            self._run_bootstrap_preparation()

        if not self.state.get_version("mcc_kaas_release"):
            self.log.progress("Detecting MCC versions...")
            self._detect_versions()

        self.log.progress("Updating templates with configuration...")
        self.templates.update_templates_with_config()

        self._run_mcc_bootstrap()
        self._run_mcc_deployment()

    def wait_for_mcc_ready(self) -> None:
        """Wait for MCC cluster to be fully ready."""
        mgmt_kubeconfig = self.state.get_kubeconfig("mcc")
        if not mgmt_kubeconfig:
            base_dir = Path(self.config.base_dir)
            mgmt_kubeconfig = str(base_dir / f"kubeconfig-{self.config.mcc_cluster_name}")

        self.log.progress("Waiting for MCC cluster to be fully ready...")

        self._wait_for_machines_ready(
            kubeconfig=mgmt_kubeconfig,
            timeout=self.config.timeout_machine_ready,
        )

        self._wait_for_resource_json(
            "cluster", "status.providerStatus.ready", True,
            kubeconfig=mgmt_kubeconfig,
            timeout=self.config.timeout_cluster_ready,
        )

        self.state.set_phase(DeploymentPhase.MCC_READY)
        self.log.progress("MCC cluster is ready!")

    def check_mcc_ready(self) -> bool:
        """Check if MCC cluster is ready."""
        try:
            mgmt_kubeconfig = self.state.get_kubeconfig("mcc")
            if not mgmt_kubeconfig:
                base_dir = Path(self.config.base_dir)
                potential_path = base_dir / f"kubeconfig-{self.config.mcc_cluster_name}"
                if not potential_path.exists():
                    self.log.warning("MCC kubeconfig not found")
                    return False
                mgmt_kubeconfig = str(potential_path)

            output = run_command_output(
                ["kubectl", "--kubeconfig", mgmt_kubeconfig, "get", "cluster", "-o", "json"],
                timeout=30,
            )

            data = json.loads(output)
            items = data.get("items", [data])
            for item in items:
                if item.get("status", {}).get("ready") is True:
                    return True
            return False

        except Exception as e:
            self.log.warning(f"Error checking MCC status: {e}")
            return False

    def deploy_mosk(self) -> None:
        """Deploy MOSK cluster."""
        self._run_mosk_deployment()

    def wait_for_mosk_ready(self) -> None:
        """Wait for MOSK cluster to be fully ready."""
        mgmt_kubeconfig = self.state.get_kubeconfig("mcc")
        namespace = self.config.mosk_namespace

        self.log.progress("Waiting for MOSK cluster to be fully ready...")

        self._wait_for_bmh_state(
            "provisioned",
            kubeconfig=mgmt_kubeconfig,
            namespace=namespace,
            timeout=self.config.timeout_bmh_provisioned,
        )

        self._wait_for_machines_ready(
            kubeconfig=mgmt_kubeconfig,
            namespace=namespace,
            timeout=self.config.timeout_machine_ready,
        )

        self._wait_for_resource_json(
            "cluster", "status.providerStatus.ready", True,
            kubeconfig=mgmt_kubeconfig,
            namespace=namespace,
            timeout=self.config.timeout_cluster_ready,
        )

        self.state.set_phase(DeploymentPhase.MOSK_READY)
        self.log.progress("MOSK cluster is ready!")

    def deploy_openstack(self) -> None:
        """Deploy OpenStack on MOSK cluster."""
        self._run_openstack_deployment()

    def cleanup(self, full: bool = False) -> None:
        """Clean up deployment."""
        self.log.phase_start("cleanup", "Cleaning up deployment")

        self.vm_manager.cleanup_all_vms()

        try:
            run_command(["kind", "delete", "cluster", "-n", "clusterapi"], check=False)
        except Exception:
            pass

        if full:
            self.infrastructure.cleanup()

        self.state.reset()
        self.log.phase_complete("cleanup")

    def status(self) -> None:
        """Print deployment status."""
        summary = self.state.get_summary()

        print("\n" + "=" * 60)
        print("DEPLOYMENT STATUS")
        print("=" * 60)
        print(f"Deployment ID: {summary['deployment_id']}")
        print(f"Phase: {summary['phase']}")
        print(f"Started: {summary['started_at']}")
        print(f"Progress: {summary['progress']['completed']}/{summary['progress']['total']} steps")
        print(f"Errors: {summary['error_count']}")
        print()

        if summary.get("versions"):
            print("Versions:")
            for name, version in summary["versions"].items():
                print(f"  {name}: {version}")

        if summary.get("kubeconfigs"):
            print("\nKubeconfigs:")
            for name, path in summary["kubeconfigs"].items():
                print(f"  {name}: {path}")

        print("=" * 60)
