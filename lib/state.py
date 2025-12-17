"""
State Management Module

Handles deployment state persistence, tracking, and recovery.
Enables resume capability after failures.
"""

import json
import shutil
from dataclasses import dataclass, field, asdict
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any


class DeploymentPhase(Enum):
    """Deployment phases for tracking progress."""
    NOT_STARTED = "not_started"
    INFRASTRUCTURE_SETUP = "infrastructure_setup"
    VM_CREATION = "vm_creation"
    BOOTSTRAP_DOWNLOAD = "bootstrap_download"
    MCC_BOOTSTRAP = "mcc_bootstrap"
    MCC_DEPLOYMENT = "mcc_deployment"
    MCC_PROVISIONING = "mcc_provisioning"
    MCC_READY = "mcc_ready"
    MOSK_SETUP = "mosk_setup"
    MOSK_PROVISIONING = "mosk_provisioning"
    MOSK_READY = "mosk_ready"
    CEPH_DEPLOYMENT = "ceph_deployment"
    OPENSTACK_DEPLOYMENT = "openstack_deployment"
    COMPLETED = "completed"
    FAILED = "failed"


class StepStatus(Enum):
    """Status of individual deployment steps."""
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class StepState:
    """State of a single deployment step."""
    name: str
    status: str = StepStatus.PENDING.value
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    error: Optional[str] = None
    retries: int = 0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def start(self) -> None:
        """Mark step as started."""
        self.status = StepStatus.IN_PROGRESS.value
        self.started_at = datetime.utcnow().isoformat()

    def complete(self, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Mark step as completed."""
        self.status = StepStatus.COMPLETED.value
        self.completed_at = datetime.utcnow().isoformat()
        if metadata:
            self.metadata.update(metadata)

    def fail(self, error: str) -> None:
        """Mark step as failed."""
        self.status = StepStatus.FAILED.value
        self.completed_at = datetime.utcnow().isoformat()
        self.error = error
        self.retries += 1

    def skip(self, reason: str = "") -> None:
        """Mark step as skipped."""
        self.status = StepStatus.SKIPPED.value
        self.completed_at = datetime.utcnow().isoformat()
        if reason:
            self.metadata["skip_reason"] = reason


@dataclass
class DeploymentState:
    """Complete deployment state."""
    deployment_id: str = ""
    phase: str = DeploymentPhase.NOT_STARTED.value
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    steps: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    resources: Dict[str, Any] = field(default_factory=dict)
    kubeconfigs: Dict[str, str] = field(default_factory=dict)
    versions: Dict[str, str] = field(default_factory=dict)
    errors: List[Dict[str, Any]] = field(default_factory=list)

    def get_step(self, name: str) -> StepState:
        """Get or create step state."""
        if name not in self.steps:
            self.steps[name] = asdict(StepState(name=name))
        step_data = self.steps[name]
        return StepState(**step_data)

    def update_step(self, step: StepState) -> None:
        """Update step state."""
        self.steps[step.name] = asdict(step)

    def add_error(self, phase: str, error: str, details: Optional[Dict[str, Any]] = None) -> None:
        """Record an error."""
        self.errors.append({
            "timestamp": datetime.utcnow().isoformat(),
            "phase": phase,
            "error": error,
            "details": details or {},
        })


class StateManager:
    """
    State manager for deployment persistence and recovery.

    Handles:
    - State persistence to JSON file
    - Automatic backup on changes
    - Resume capability
    - State querying
    """

    def __init__(
        self,
        state_file: str = "deployment_state.json",
        deployment_dir: Optional[Path] = None,
        backup_on_change: bool = True
    ):
        """
        Initialize state manager.

        Args:
            state_file: Name of state file (not full path)
            deployment_dir: Directory to store state file. If None, uses current directory.
            backup_on_change: Whether to backup state before changes
        """
        if deployment_dir:
            self.state_file = Path(deployment_dir) / state_file
        else:
            self.state_file = Path(state_file)
        self.backup_on_change = backup_on_change
        self._state: Optional[DeploymentState] = None

    def load(self) -> DeploymentState:
        """
        Load state from file or create new state.

        Returns:
            Deployment state
        """
        if self._state is not None:
            return self._state

        if self.state_file.exists():
            with open(self.state_file, 'r') as f:
                data = json.load(f)
                self._state = DeploymentState(**data)
        else:
            self._state = DeploymentState(
                deployment_id=datetime.utcnow().strftime("%Y%m%d_%H%M%S"),
                started_at=datetime.utcnow().isoformat(),
            )
            self.save()

        return self._state

    def save(self) -> None:
        """Save state to file."""
        if self._state is None:
            return

        if self.backup_on_change and self.state_file.exists():
            backup_path = self.state_file.with_suffix(
                f".{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}.backup.json"
            )
            shutil.copy(self.state_file, backup_path)

            # Keep only last 10 backups
            backups = sorted(self.state_file.parent.glob("*.backup.json"))
            for old_backup in backups[:-10]:
                old_backup.unlink()

        with open(self.state_file, 'w') as f:
            json.dump(asdict(self._state), f, indent=2)

    @property
    def state(self) -> DeploymentState:
        """Get current state (loading if necessary)."""
        if self._state is None:
            self.load()
        return self._state

    def set_phase(self, phase: DeploymentPhase) -> None:
        """
        Set current deployment phase.

        Args:
            phase: New deployment phase
        """
        self.state.phase = phase.value
        self.save()

    def get_phase(self) -> DeploymentPhase:
        """
        Get current deployment phase.

        Returns:
            Current phase
        """
        return DeploymentPhase(self.state.phase)

    def start_step(self, name: str) -> StepState:
        """
        Start a deployment step.

        Args:
            name: Step name

        Returns:
            Step state
        """
        step = self.state.get_step(name)
        step.start()
        self.state.update_step(step)
        self.save()
        return step

    def complete_step(self, name: str, metadata: Optional[Dict[str, Any]] = None) -> StepState:
        """
        Complete a deployment step.

        Args:
            name: Step name
            metadata: Additional metadata

        Returns:
            Step state
        """
        step = self.state.get_step(name)
        step.complete(metadata)
        self.state.update_step(step)
        self.save()
        return step

    def fail_step(self, name: str, error: str) -> StepState:
        """
        Fail a deployment step.

        Args:
            name: Step name
            error: Error message

        Returns:
            Step state
        """
        step = self.state.get_step(name)
        step.fail(error)
        self.state.update_step(step)
        self.state.add_error(self.state.phase, error, {"step": name})
        self.save()
        return step

    def skip_step(self, name: str, reason: str = "") -> StepState:
        """
        Skip a deployment step.

        Args:
            name: Step name
            reason: Skip reason

        Returns:
            Step state
        """
        step = self.state.get_step(name)
        step.skip(reason)
        self.state.update_step(step)
        self.save()
        return step

    def is_step_completed(self, name: str) -> bool:
        """
        Check if a step is completed.

        Args:
            name: Step name

        Returns:
            True if completed
        """
        step = self.state.get_step(name)
        return step.status == StepStatus.COMPLETED.value

    def is_step_failed(self, name: str) -> bool:
        """
        Check if a step has failed.

        Args:
            name: Step name

        Returns:
            True if failed
        """
        step = self.state.get_step(name)
        return step.status == StepStatus.FAILED.value

    def get_step_retries(self, name: str) -> int:
        """
        Get number of retries for a step.

        Args:
            name: Step name

        Returns:
            Number of retries
        """
        step = self.state.get_step(name)
        return step.retries

    def should_run_step(self, name: str, max_retries: int = 3) -> bool:
        """
        Check if a step should run.

        Args:
            name: Step name
            max_retries: Maximum allowed retries

        Returns:
            True if step should run
        """
        step = self.state.get_step(name)
        if step.status == StepStatus.COMPLETED.value:
            return False
        if step.status == StepStatus.SKIPPED.value:
            return False
        if step.retries >= max_retries:
            return False
        return True

    def set_resource(self, key: str, value: Any) -> None:
        """
        Set a resource value.

        Args:
            key: Resource key
            value: Resource value
        """
        self.state.resources[key] = value
        self.save()

    def get_resource(self, key: str, default: Any = None) -> Any:
        """
        Get a resource value.

        Args:
            key: Resource key
            default: Default value

        Returns:
            Resource value or default
        """
        return self.state.resources.get(key, default)

    def set_kubeconfig(self, name: str, path: str) -> None:
        """
        Set a kubeconfig path.

        Args:
            name: Kubeconfig name
            path: Kubeconfig file path
        """
        self.state.kubeconfigs[name] = path
        self.save()

    def get_kubeconfig(self, name: str) -> Optional[str]:
        """
        Get a kubeconfig path.

        Args:
            name: Kubeconfig name

        Returns:
            Kubeconfig path or None
        """
        return self.state.kubeconfigs.get(name)

    def set_version(self, name: str, version: str) -> None:
        """
        Set a detected version.

        Args:
            name: Component name
            version: Version string
        """
        self.state.versions[name] = version
        self.save()

    def get_version(self, name: str) -> Optional[str]:
        """
        Get a detected version.

        Args:
            name: Component name

        Returns:
            Version string or None
        """
        return self.state.versions.get(name)

    def mark_completed(self) -> None:
        """Mark deployment as completed."""
        self.state.phase = DeploymentPhase.COMPLETED.value
        self.state.completed_at = datetime.utcnow().isoformat()
        self.save()

    def mark_failed(self, error: str) -> None:
        """
        Mark deployment as failed.

        Args:
            error: Error message
        """
        self.state.phase = DeploymentPhase.FAILED.value
        self.state.completed_at = datetime.utcnow().isoformat()
        self.state.add_error("deployment", error)
        self.save()

    def can_resume(self) -> bool:
        """
        Check if deployment can be resumed.

        Returns:
            True if resumable
        """
        phase = self.get_phase()
        return phase not in [
            DeploymentPhase.NOT_STARTED,
            DeploymentPhase.COMPLETED,
        ]

    def get_resume_phase(self) -> DeploymentPhase:
        """
        Get phase to resume from.

        Returns:
            Resume phase
        """
        current_phase = self.get_phase()

        # If failed, try to resume from current phase
        if current_phase == DeploymentPhase.FAILED:
            # Find the last completed phase
            phase_order = list(DeploymentPhase)
            for phase in reversed(phase_order):
                phase_step = f"phase_{phase.value}"
                if self.is_step_completed(phase_step):
                    # Return the next phase
                    idx = phase_order.index(phase)
                    if idx + 1 < len(phase_order):
                        return phase_order[idx + 1]

        return current_phase

    def reset(self) -> None:
        """Reset state to initial state."""
        self._state = DeploymentState(
            deployment_id=datetime.utcnow().strftime("%Y%m%d_%H%M%S"),
            started_at=datetime.utcnow().isoformat(),
        )
        self.save()

    def get_summary(self) -> Dict[str, Any]:
        """
        Get deployment summary.

        Returns:
            Summary dictionary
        """
        completed_steps = sum(
            1 for s in self.state.steps.values()
            if s.get("status") == StepStatus.COMPLETED.value
        )
        failed_steps = sum(
            1 for s in self.state.steps.values()
            if s.get("status") == StepStatus.FAILED.value
        )
        total_steps = len(self.state.steps)

        return {
            "deployment_id": self.state.deployment_id,
            "phase": self.state.phase,
            "started_at": self.state.started_at,
            "completed_at": self.state.completed_at,
            "progress": {
                "completed": completed_steps,
                "failed": failed_steps,
                "total": total_steps,
            },
            "versions": self.state.versions,
            "kubeconfigs": self.state.kubeconfigs,
            "error_count": len(self.state.errors),
        }
