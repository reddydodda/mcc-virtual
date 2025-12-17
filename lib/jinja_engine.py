"""
Jinja2 Template Engine Module

Provides Jinja2-based template rendering for MCC/MOSK manifests.
"""

import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    from jinja2 import Environment, FileSystemLoader, StrictUndefined
    JINJA2_AVAILABLE = True
except ImportError:
    JINJA2_AVAILABLE = False

import yaml

from .logger import get_logger

logger = get_logger("jinja_engine")


class Jinja2Engine:
    """
    Jinja2 template engine for generating Kubernetes manifests.

    Provides:
    - Template rendering with variable substitution
    - Custom filters for YAML and Kubernetes
    - Multi-document YAML support
    """

    def __init__(self, template_dir: str):
        """
        Initialize Jinja2 engine.

        Args:
            template_dir: Directory containing templates
        """
        if not JINJA2_AVAILABLE:
            raise ImportError(
                "Jinja2 is required for template rendering. "
                "Install with: pip install jinja2"
            )

        self.template_dir = Path(template_dir)

        # Create Jinja2 environment
        self.env = Environment(
            loader=FileSystemLoader(str(self.template_dir)),
            undefined=StrictUndefined,
            trim_blocks=True,
            lstrip_blocks=True,
            keep_trailing_newline=True,
        )

        # Add custom filters
        self._add_custom_filters()

    def _add_custom_filters(self) -> None:
        """Add custom Jinja2 filters."""

        def to_yaml(value: Any, indent: int = 0) -> str:
            """Convert value to YAML string."""
            yaml_str = yaml.dump(value, default_flow_style=False, allow_unicode=True)
            if indent > 0:
                lines = yaml_str.split('\n')
                indented = '\n'.join(' ' * indent + line if line else line for line in lines)
                return indented
            return yaml_str

        def to_yaml_inline(value: Any) -> str:
            """Convert value to inline YAML."""
            return yaml.dump(value, default_flow_style=True).strip()

        def b64encode(value: str) -> str:
            """Base64 encode a string."""
            import base64
            return base64.b64encode(value.encode()).decode()

        def quote(value: str) -> str:
            """Quote a string for YAML."""
            return f'"{value}"'

        def indent_lines(value: str, spaces: int = 2) -> str:
            """Indent all lines in a string."""
            lines = value.split('\n')
            return '\n'.join(' ' * spaces + line if line.strip() else line for line in lines)

        def mac_address(prefix: str, index: int) -> str:
            """Generate a MAC address from prefix and index."""
            suffix = f"{index:02d}" if index < 10 else f"{index}{index}" if index < 10 else f"{index:02d}"
            return f"{prefix}:{suffix}"

        self.env.filters['to_yaml'] = to_yaml
        self.env.filters['to_yaml_inline'] = to_yaml_inline
        self.env.filters['b64encode'] = b64encode
        self.env.filters['quote'] = quote
        self.env.filters['indent_lines'] = indent_lines
        self.env.filters['mac_address'] = mac_address

    def render(self, template_name: str, variables: Dict[str, Any]) -> str:
        """
        Render a template with variables.

        Args:
            template_name: Template file name
            variables: Template variables

        Returns:
            Rendered template string
        """
        template = self.env.get_template(template_name)
        return template.render(**variables)

    def render_string(self, template_string: str, variables: Dict[str, Any]) -> str:
        """
        Render a template string with variables.

        Args:
            template_string: Template string
            variables: Template variables

        Returns:
            Rendered string
        """
        template = self.env.from_string(template_string)
        return template.render(**variables)

    def render_to_file(
        self,
        template_name: str,
        output_path: str,
        variables: Dict[str, Any],
    ) -> str:
        """
        Render a template and write to file.

        Args:
            template_name: Template file name
            output_path: Output file path
            variables: Template variables

        Returns:
            Output file path
        """
        content = self.render(template_name, variables)

        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content)

        logger.debug(f"Rendered template {template_name} to {output_path}")
        return str(output)

    def render_all(
        self,
        output_dir: str,
        variables: Dict[str, Any],
        pattern: str = "*.j2",
    ) -> List[str]:
        """
        Render all templates matching pattern.

        Args:
            output_dir: Output directory
            variables: Template variables
            pattern: Glob pattern for templates

        Returns:
            List of output file paths
        """
        output_files = []

        for template_path in self.template_dir.rglob(pattern):
            # Calculate relative path
            rel_path = template_path.relative_to(self.template_dir)
            # Remove .j2 extension
            output_name = str(rel_path).replace('.j2', '')
            output_path = Path(output_dir) / output_name

            template_name = str(rel_path)
            self.render_to_file(template_name, str(output_path), variables)
            output_files.append(str(output_path))

        return output_files


class SimpleTemplateEngine:
    """
    Simple template engine for environments without Jinja2.

    Uses basic string replacement for ${variable} and {{ variable }} patterns.
    """

    def __init__(self, template_dir: Optional[str] = None):
        """
        Initialize simple template engine.

        Args:
            template_dir: Directory containing templates
        """
        self.template_dir = Path(template_dir) if template_dir else None

    def render_string(self, template_string: str, variables: Dict[str, Any]) -> str:
        """
        Render a template string with simple variable substitution.

        Args:
            template_string: Template string
            variables: Variables to substitute

        Returns:
            Rendered string
        """
        result = template_string

        # Replace {{ variable }} patterns
        for key, value in variables.items():
            patterns = [
                f"{{{{ {key} }}}}",
                f"{{{{  {key}  }}}}",
                f"${{{key}}}",
                f"SET_{key.upper()}",
            ]
            for pattern in patterns:
                result = result.replace(pattern, str(value))

        return result

    def render(self, template_path: str, variables: Dict[str, Any]) -> str:
        """
        Render a template file.

        Args:
            template_path: Path to template file
            variables: Variables to substitute

        Returns:
            Rendered string
        """
        if self.template_dir:
            full_path = self.template_dir / template_path
        else:
            full_path = Path(template_path)

        template_string = full_path.read_text()
        return self.render_string(template_string, variables)

    def render_to_file(
        self,
        template_path: str,
        output_path: str,
        variables: Dict[str, Any],
    ) -> str:
        """
        Render a template and write to file.

        Args:
            template_path: Path to template
            output_path: Output file path
            variables: Variables to substitute

        Returns:
            Output file path
        """
        content = self.render(template_path, variables)

        output = Path(output_path)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(content)

        logger.debug(f"Rendered template {template_path} to {output_path}")
        return str(output)


def get_template_engine(template_dir: str) -> Any:
    """
    Get the best available template engine.

    Args:
        template_dir: Template directory

    Returns:
        Template engine instance
    """
    if JINJA2_AVAILABLE:
        return Jinja2Engine(template_dir)
    else:
        logger.warning("Jinja2 not available, using simple template engine")
        return SimpleTemplateEngine(template_dir)


def check_jinja2_available() -> bool:
    """Check if Jinja2 is available."""
    return JINJA2_AVAILABLE
