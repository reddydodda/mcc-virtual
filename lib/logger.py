"""
Logging Module

Provides structured logging with support for JSON and text formats.
Includes console and file output with rotation.
"""

import json
import logging
import sys
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, Optional


class JsonFormatter(logging.Formatter):
    """JSON log formatter for structured logging."""

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_data = {
            "timestamp": datetime.utcnow().isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add extra fields
        if hasattr(record, "extra_data"):
            log_data.update(record.extra_data)

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        # Add source location
        log_data["source"] = {
            "file": record.filename,
            "line": record.lineno,
            "function": record.funcName,
        }

        return json.dumps(log_data)


class ColoredFormatter(logging.Formatter):
    """Colored text formatter for console output."""

    COLORS = {
        "DEBUG": "\033[36m",     # Cyan
        "INFO": "\033[32m",      # Green
        "WARNING": "\033[33m",   # Yellow
        "ERROR": "\033[31m",     # Red
        "CRITICAL": "\033[35m",  # Magenta
    }
    RESET = "\033[0m"
    BOLD = "\033[1m"

    def format(self, record: logging.LogRecord) -> str:
        """Format log record with colors."""
        color = self.COLORS.get(record.levelname, "")
        reset = self.RESET

        # Format timestamp
        timestamp = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

        # Build message
        msg = f"{color}{timestamp} [{record.levelname:8}]{reset} {record.getMessage()}"

        # Add extra data if present
        if hasattr(record, "extra_data") and record.extra_data:
            extra_str = " ".join(f"{k}={v}" for k, v in record.extra_data.items())
            msg = f"{msg} {self.BOLD}({extra_str}){reset}"

        # Add exception info if present
        if record.exc_info:
            msg = f"{msg}\n{self.formatException(record.exc_info)}"

        return msg


class ContextLogger(logging.LoggerAdapter):
    """Logger adapter that supports extra context data."""

    def process(self, msg: str, kwargs: Dict[str, Any]) -> tuple:
        """Process log message with extra context."""
        extra = kwargs.get("extra", {})

        # Merge adapter extra with call extra
        combined_extra = {**self.extra, **extra}

        # Store extra data for formatters
        kwargs["extra"] = {"extra_data": combined_extra}

        return msg, kwargs


# Global logger registry
_loggers: Dict[str, ContextLogger] = {}


def setup_logging(
    level: str = "INFO",
    log_file: Optional[str] = None,
    log_format: str = "text",
    max_size_mb: int = 100,
    backup_count: int = 5,
    deployment_dir: Optional[Path] = None,
) -> None:
    """
    Configure logging for the deployment system.

    Args:
        level: Log level (DEBUG, INFO, WARNING, ERROR)
        log_file: Optional log file name (not full path)
        log_format: Log format (json, text)
        max_size_mb: Maximum log file size in MB
        backup_count: Number of backup files to keep
        deployment_dir: Directory to store log file. If None, uses current directory.
    """
    root_logger = logging.getLogger("mcc_deploy")
    root_logger.setLevel(getattr(logging, level.upper()))

    # Clear existing handlers
    root_logger.handlers.clear()

    # Console handler with colored output
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.DEBUG)
    console_handler.setFormatter(ColoredFormatter())
    root_logger.addHandler(console_handler)

    # File handler if specified
    if log_file:
        if deployment_dir:
            log_path = Path(deployment_dir) / log_file
        else:
            log_path = Path(log_file)
        log_path.parent.mkdir(parents=True, exist_ok=True)

        file_handler = RotatingFileHandler(
            log_path,
            maxBytes=max_size_mb * 1024 * 1024,
            backupCount=backup_count,
        )
        file_handler.setLevel(logging.DEBUG)

        if log_format == "json":
            file_handler.setFormatter(JsonFormatter())
        else:
            file_handler.setFormatter(logging.Formatter(
                "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
            ))

        root_logger.addHandler(file_handler)


def get_logger(name: str, **context: Any) -> ContextLogger:
    """
    Get a logger with optional context.

    Args:
        name: Logger name
        **context: Context key-value pairs

    Returns:
        Context logger
    """
    full_name = f"mcc_deploy.{name}"

    if full_name not in _loggers:
        base_logger = logging.getLogger(full_name)
        _loggers[full_name] = ContextLogger(base_logger, context)

    return _loggers[full_name]


class DeploymentLogger:
    """
    High-level deployment logger for tracking phases and steps.

    Provides structured logging for deployment events.
    """

    def __init__(self, name: str = "deployment"):
        """Initialize deployment logger."""
        self.logger = get_logger(name)
        self._current_phase: Optional[str] = None
        self._current_step: Optional[str] = None

    def phase_start(self, phase: str, description: str = "") -> None:
        """Log phase start."""
        self._current_phase = phase
        self.logger.info(
            f"Starting phase: {phase}",
            extra={"phase": phase, "event": "phase_start", "description": description}
        )

    def phase_complete(self, phase: str, duration_seconds: Optional[float] = None) -> None:
        """Log phase completion."""
        self.logger.info(
            f"Completed phase: {phase}",
            extra={"phase": phase, "event": "phase_complete", "duration": duration_seconds}
        )
        self._current_phase = None

    def phase_failed(self, phase: str, error: str) -> None:
        """Log phase failure."""
        self.logger.error(
            f"Failed phase: {phase} - {error}",
            extra={"phase": phase, "event": "phase_failed", "error": error}
        )
        self._current_phase = None

    def step_start(self, step: str, description: str = "") -> None:
        """Log step start."""
        self._current_step = step
        self.logger.info(
            f"  Starting step: {step}",
            extra={
                "phase": self._current_phase,
                "step": step,
                "event": "step_start",
                "description": description,
            }
        )

    def step_complete(self, step: str, result: Optional[Dict[str, Any]] = None) -> None:
        """Log step completion."""
        self.logger.info(
            f"  Completed step: {step}",
            extra={
                "phase": self._current_phase,
                "step": step,
                "event": "step_complete",
                "result": result,
            }
        )
        self._current_step = None

    def step_failed(self, step: str, error: str) -> None:
        """Log step failure."""
        self.logger.error(
            f"  Failed step: {step} - {error}",
            extra={
                "phase": self._current_phase,
                "step": step,
                "event": "step_failed",
                "error": error,
            }
        )
        self._current_step = None

    def step_skipped(self, step: str, reason: str = "") -> None:
        """Log step skip."""
        self.logger.info(
            f"  Skipped step: {step} ({reason})",
            extra={
                "phase": self._current_phase,
                "step": step,
                "event": "step_skipped",
                "reason": reason,
            }
        )

    def progress(self, message: str, **kwargs: Any) -> None:
        """Log progress message."""
        self.logger.info(
            f"    {message}",
            extra={"phase": self._current_phase, "step": self._current_step, **kwargs}
        )

    def warning(self, message: str, **kwargs: Any) -> None:
        """Log warning message."""
        self.logger.warning(
            message,
            extra={"phase": self._current_phase, "step": self._current_step, **kwargs}
        )

    def error(self, message: str, **kwargs: Any) -> None:
        """Log error message."""
        self.logger.error(
            message,
            extra={"phase": self._current_phase, "step": self._current_step, **kwargs}
        )

    def debug(self, message: str, **kwargs: Any) -> None:
        """Log debug message."""
        self.logger.debug(
            message,
            extra={"phase": self._current_phase, "step": self._current_step, **kwargs}
        )

    def command(self, command: str, exit_code: int = 0, output: str = "") -> None:
        """Log command execution."""
        level = logging.DEBUG if exit_code == 0 else logging.WARNING
        self.logger.log(
            level,
            f"    Command: {command[:100]}{'...' if len(command) > 100 else ''}",
            extra={
                "event": "command",
                "command": command,
                "exit_code": exit_code,
                "output_length": len(output),
            }
        )

    def resource_created(self, resource_type: str, name: str, **kwargs: Any) -> None:
        """Log resource creation."""
        self.logger.info(
            f"    Created {resource_type}: {name}",
            extra={
                "event": "resource_created",
                "resource_type": resource_type,
                "resource_name": name,
                **kwargs,
            }
        )

    def resource_waiting(self, resource_type: str, name: str, condition: str, current: str) -> None:
        """Log resource waiting state."""
        self.logger.debug(
            f"    Waiting for {resource_type}/{name}: {condition} (current: {current})",
            extra={
                "event": "resource_waiting",
                "resource_type": resource_type,
                "resource_name": name,
                "condition": condition,
                "current_state": current,
            }
        )

    def resource_ready(self, resource_type: str, name: str, **kwargs: Any) -> None:
        """Log resource ready state."""
        self.logger.info(
            f"    Ready: {resource_type}/{name}",
            extra={
                "event": "resource_ready",
                "resource_type": resource_type,
                "resource_name": name,
                **kwargs,
            }
        )

    def validation_passed(self, check: str) -> None:
        """Log validation passed."""
        self.logger.info(
            f"    Validation passed: {check}",
            extra={"event": "validation_passed", "check": check}
        )

    def validation_failed(self, check: str, reason: str) -> None:
        """Log validation failed."""
        self.logger.error(
            f"    Validation failed: {check} - {reason}",
            extra={"event": "validation_failed", "check": check, "reason": reason}
        )
