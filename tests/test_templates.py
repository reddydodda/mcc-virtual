"""
Tests for MOSK Jinja2 template rendering.

Tests cover:
- Template file existence
- Template rendering
- Output file structure
- Template content validation
- Context building
"""

import os
import sys
import tempfile
import shutil
import unittest
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.config import Config
from lib.state import StateManager
from lib.vm_manager import VMManager
from lib.templates import TemplateGenerator
from lib.logger import DeploymentLogger


class TestTemplateFiles(unittest.TestCase):
    """Test that all required Jinja2 template files exist."""

    def setUp(self):
        self.template_dir = Path(__file__).parent.parent / "templates" / "mosk"

    def test_template_directory_exists(self):
        """Template directory should exist."""
        self.assertTrue(self.template_dir.exists(), f"Template directory not found: {self.template_dir}")

    def test_namespace_template_exists(self):
        """Namespace template should exist."""
        template = self.template_dir / "namespace.yaml.j2"
        self.assertTrue(template.exists(), f"Template not found: {template}")

    def test_metallbconfig_template_exists(self):
        """MetalLB config template should exist."""
        template = self.template_dir / "metallbconfig.yaml.j2"
        self.assertTrue(template.exists(), f"Template not found: {template}")

    def test_bmh_control_template_exists(self):
        """BMH control template should exist."""
        template = self.template_dir / "bmh-control.yaml.j2"
        self.assertTrue(template.exists(), f"Template not found: {template}")

    def test_bmh_compute_template_exists(self):
        """BMH compute template should exist."""
        template = self.template_dir / "bmh-compute.yaml.j2"
        self.assertTrue(template.exists(), f"Template not found: {template}")

    def test_cluster_template_exists(self):
        """Cluster template should exist."""
        template = self.template_dir / "cluster.yaml.j2"
        self.assertTrue(template.exists(), f"Template not found: {template}")

    def test_bmhp_templates_exist(self):
        """BMHP templates should exist."""
        for name in ["bmhp-ctl.yaml.j2", "bmhp-cmp.yaml.j2"]:
            template = self.template_dir / name
            self.assertTrue(template.exists(), f"Template not found: {template}")

    def test_l2template_exists(self):
        """L2 template should exist."""
        template = self.template_dir / "l2template.yaml.j2"
        self.assertTrue(template.exists(), f"Template not found: {template}")

    def test_subnet_template_exists(self):
        """Subnet template should exist."""
        template = self.template_dir / "subnet.yaml.j2"
        self.assertTrue(template.exists(), f"Template not found: {template}")

    def test_machines_templates_exist(self):
        """Machine templates should exist."""
        for name in ["machines-control.yaml.j2", "machines-compute.yaml.j2"]:
            template = self.template_dir / name
            self.assertTrue(template.exists(), f"Template not found: {template}")

    def test_osdpl_templates_exist(self):
        """OSDPL templates should exist."""
        for name in ["osdpl.yaml.j2", "osdpl-secret.yaml.j2"]:
            template = self.template_dir / name
            self.assertTrue(template.exists(), f"Template not found: {template}")

    def test_miraceph_template_exists(self):
        """MiraCeph template should exist."""
        template = self.template_dir / "miraceph.yaml.j2"
        self.assertTrue(template.exists(), f"Template not found: {template}")


class TestTemplateRendering(unittest.TestCase):
    """Test template rendering functionality."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        cls.config = Config(str(Path(__file__).parent.parent / "config.yaml"))
        cls.state = StateManager()
        cls.log = DeploymentLogger("test")
        cls.vm_manager = VMManager(cls.config, cls.state, cls.log)
        cls.templates = TemplateGenerator(cls.config, cls.state, cls.vm_manager, cls.log)

    def setUp(self):
        """Create temp directory for each test."""
        self.output_dir = tempfile.mkdtemp(prefix="mosk_test_")

    def tearDown(self):
        """Clean up temp directory."""
        if os.path.exists(self.output_dir):
            shutil.rmtree(self.output_dir)

    def test_render_mosk_templates_returns_dict(self):
        """render_mosk_templates should return a dictionary."""
        result = self.templates.render_mosk_templates(self.output_dir)
        self.assertIsInstance(result, dict)

    def test_render_mosk_templates_creates_files(self):
        """render_mosk_templates should create output files."""
        self.templates.render_mosk_templates(self.output_dir)
        files = list(Path(self.output_dir).rglob("*.yaml"))
        self.assertGreater(len(files), 0, "No output files created")

    def test_render_creates_namespace_file(self):
        """Should create 01-namespace.yaml."""
        self.templates.render_mosk_templates(self.output_dir)
        ns_file = Path(self.output_dir) / "01-namespace.yaml"
        self.assertTrue(ns_file.exists(), f"Namespace file not created: {ns_file}")

    def test_render_creates_metallbconfig_file(self):
        """Should create 02-metallbconfig.yaml."""
        self.templates.render_mosk_templates(self.output_dir)
        file = Path(self.output_dir) / "02-metallbconfig.yaml"
        self.assertTrue(file.exists(), f"MetalLB config file not created: {file}")

    def test_render_creates_bmh_directory(self):
        """Should create 03-bmh directory with files."""
        self.templates.render_mosk_templates(self.output_dir)
        bmh_dir = Path(self.output_dir) / "03-bmh"
        self.assertTrue(bmh_dir.exists(), f"BMH directory not created: {bmh_dir}")
        files = list(bmh_dir.glob("*.yaml"))
        self.assertGreaterEqual(len(files), 2, "BMH directory should have at least 2 files")

    def test_render_creates_cluster_file(self):
        """Should create 04-cluster.yaml."""
        self.templates.render_mosk_templates(self.output_dir)
        file = Path(self.output_dir) / "04-cluster.yaml"
        self.assertTrue(file.exists(), f"Cluster file not created: {file}")

    def test_render_creates_bmhp_files(self):
        """Should create BMHP files."""
        self.templates.render_mosk_templates(self.output_dir)
        for name in ["05-bmhp-ctl.yaml", "05-bmhp-cmp.yaml"]:
            file = Path(self.output_dir) / name
            self.assertTrue(file.exists(), f"BMHP file not created: {file}")

    def test_render_creates_l2template_file(self):
        """Should create 06-l2template.yaml."""
        self.templates.render_mosk_templates(self.output_dir)
        file = Path(self.output_dir) / "06-l2template.yaml"
        self.assertTrue(file.exists(), f"L2 template file not created: {file}")

    def test_render_creates_subnet_file(self):
        """Should create 07-subnet.yaml."""
        self.templates.render_mosk_templates(self.output_dir)
        file = Path(self.output_dir) / "07-subnet.yaml"
        self.assertTrue(file.exists(), f"Subnet file not created: {file}")

    def test_render_creates_machines_directory(self):
        """Should create 08-machines directory with files."""
        self.templates.render_mosk_templates(self.output_dir)
        machines_dir = Path(self.output_dir) / "08-machines"
        self.assertTrue(machines_dir.exists(), f"Machines directory not created: {machines_dir}")
        files = list(machines_dir.glob("*.yaml"))
        self.assertGreaterEqual(len(files), 2, "Machines directory should have at least 2 files")

    def test_render_creates_osdpl_directory(self):
        """Should create 10-osdpl directory with files."""
        self.templates.render_mosk_templates(self.output_dir)
        osdpl_dir = Path(self.output_dir) / "10-osdpl"
        self.assertTrue(osdpl_dir.exists(), f"OSDPL directory not created: {osdpl_dir}")
        files = list(osdpl_dir.glob("*.yaml"))
        self.assertEqual(len(files), 2, "OSDPL directory should have exactly 2 files")

    def test_rendered_files_count(self):
        """Should render correct number of template files."""
        result = self.templates.render_mosk_templates(self.output_dir)
        # Base templates: 11 + OSDPL: 2 = 13 (without storage templates)
        self.assertGreaterEqual(len(result), 13, f"Expected at least 13 templates, got {len(result)}")


class TestTemplateContent(unittest.TestCase):
    """Test rendered template content is valid."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        cls.config = Config(str(Path(__file__).parent.parent / "config.yaml"))
        cls.state = StateManager()
        cls.log = DeploymentLogger("test")
        cls.vm_manager = VMManager(cls.config, cls.state, cls.log)
        cls.templates = TemplateGenerator(cls.config, cls.state, cls.vm_manager, cls.log)
        cls.output_dir = tempfile.mkdtemp(prefix="mosk_test_")
        cls.templates.render_mosk_templates(cls.output_dir)

    @classmethod
    def tearDownClass(cls):
        """Clean up temp directory."""
        if os.path.exists(cls.output_dir):
            shutil.rmtree(cls.output_dir)

    def test_namespace_content_valid(self):
        """Namespace file should have valid content."""
        ns_file = Path(self.output_dir) / "01-namespace.yaml"
        content = ns_file.read_text()
        self.assertIn("apiVersion:", content)
        self.assertIn("kind: Namespace", content)
        self.assertIn("name:", content)
        # Should NOT contain template placeholders
        self.assertNotIn("{{", content)
        self.assertNotIn("}}", content)
        self.assertNotIn("SET_NAMESPACE", content)

    def test_namespace_uses_config_value(self):
        """Namespace should use value from config."""
        ns_file = Path(self.output_dir) / "01-namespace.yaml"
        content = ns_file.read_text()
        expected_namespace = self.config.mosk_namespace
        self.assertIn(f"name: {expected_namespace}", content)

    def test_cluster_content_valid(self):
        """Cluster file should have valid content."""
        file = Path(self.output_dir) / "04-cluster.yaml"
        content = file.read_text()
        self.assertIn("apiVersion:", content)
        self.assertIn("kind:", content)
        # Should NOT contain template placeholders
        self.assertNotIn("{{", content)
        self.assertNotIn("}}", content)

    def test_bmh_control_content_valid(self):
        """BMH control file should have valid content."""
        file = Path(self.output_dir) / "03-bmh" / "01-bmh-control.yaml"
        content = file.read_text()
        self.assertIn("apiVersion:", content)
        # Should NOT contain template placeholders
        self.assertNotIn("{{", content)
        self.assertNotIn("}}", content)

    def test_metallbconfig_content_valid(self):
        """MetalLB config should have valid content."""
        file = Path(self.output_dir) / "02-metallbconfig.yaml"
        content = file.read_text()
        self.assertIn("apiVersion:", content)
        # Should NOT contain template placeholders
        self.assertNotIn("{{", content)
        self.assertNotIn("}}", content)

    def test_osdpl_secret_content_valid(self):
        """OSDPL secret should have valid content."""
        file = Path(self.output_dir) / "10-osdpl" / "osdpl-secret.yaml"
        content = file.read_text()
        self.assertIn("apiVersion:", content)
        self.assertIn("kind: Secret", content)
        # Should NOT contain template placeholders
        self.assertNotIn("{{", content)
        self.assertNotIn("}}", content)

    def test_osdpl_content_valid(self):
        """OSDPL should have valid content."""
        file = Path(self.output_dir) / "10-osdpl" / "osdpl.yaml"
        content = file.read_text()
        self.assertIn("apiVersion:", content)
        # Should NOT contain template placeholders
        self.assertNotIn("{{", content)
        self.assertNotIn("}}", content)


class TestTemplateContext(unittest.TestCase):
    """Test template context building."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        cls.config = Config(str(Path(__file__).parent.parent / "config.yaml"))
        cls.state = StateManager()
        cls.log = DeploymentLogger("test")
        cls.vm_manager = VMManager(cls.config, cls.state, cls.log)
        cls.templates = TemplateGenerator(cls.config, cls.state, cls.vm_manager, cls.log)

    def test_mosk_context_has_namespace(self):
        """MOSK context should have namespace."""
        context = self.templates.build_mosk_context()
        self.assertIn("mosk_namespace", context)
        self.assertEqual(context["mosk_namespace"], self.config.mosk_namespace)

    def test_mosk_context_has_control_nodes(self):
        """MOSK context should have control nodes."""
        context = self.templates.build_mosk_context()
        self.assertIn("mosk_control_nodes", context)
        self.assertIsInstance(context["mosk_control_nodes"], list)

    def test_mosk_context_has_compute_nodes(self):
        """MOSK context should have compute nodes."""
        context = self.templates.build_mosk_context()
        self.assertIn("mosk_compute_nodes", context)
        self.assertIsInstance(context["mosk_compute_nodes"], list)

    def test_mosk_context_has_network_config(self):
        """MOSK context should have network configuration."""
        context = self.templates.build_mosk_context()
        self.assertIn("mosk_pod_cidr", context)
        self.assertIn("mosk_service_cidr", context)
        self.assertIn("mosk_lcm_cidr", context)

    def test_mosk_context_has_ceph_config(self):
        """MOSK context should have Ceph configuration."""
        context = self.templates.build_mosk_context()
        self.assertIn("ceph_public_network", context)
        self.assertIn("ceph_osd_devices", context)

    def test_mosk_context_has_openstack_config(self):
        """MOSK context should have OpenStack configuration."""
        context = self.templates.build_mosk_context()
        self.assertIn("openstack_version", context)
        self.assertIn("osdpl_public_domain", context)

    def test_mosk_context_has_credentials(self):
        """MOSK context should have BMC credentials."""
        context = self.templates.build_mosk_context()
        self.assertIn("bmc_username", context)
        self.assertIn("bmc_password", context)

    def test_mosk_context_has_storage_mode(self):
        """MOSK context should have storage mode."""
        context = self.templates.build_mosk_context()
        self.assertIn("storage_mode", context)
        self.assertIn("is_hyperconverged", context)


class TestConfigIntegration(unittest.TestCase):
    """Test configuration integration with templates."""

    def test_config_loads_successfully(self):
        """Config should load without errors."""
        config = Config(str(Path(__file__).parent.parent / "config.yaml"))
        self.assertIsNotNone(config)

    def test_config_has_mosk_namespace(self):
        """Config should have MOSK namespace."""
        config = Config(str(Path(__file__).parent.parent / "config.yaml"))
        self.assertIsNotNone(config.mosk_namespace)

    def test_config_has_topology(self):
        """Config should have topology settings."""
        config = Config(str(Path(__file__).parent.parent / "config.yaml"))
        self.assertIsNotNone(config.mosk_control_topology)
        self.assertIsNotNone(config.mosk_compute_topology)

    def test_config_has_network_settings(self):
        """Config should have network settings."""
        config = Config(str(Path(__file__).parent.parent / "config.yaml"))
        self.assertIsNotNone(config.bridges)


class TestYAMLValidity(unittest.TestCase):
    """Test that rendered YAML is valid."""

    @classmethod
    def setUpClass(cls):
        """Set up test fixtures."""
        import yaml
        cls.yaml = yaml
        cls.config = Config(str(Path(__file__).parent.parent / "config.yaml"))
        cls.state = StateManager()
        cls.log = DeploymentLogger("test")
        cls.vm_manager = VMManager(cls.config, cls.state, cls.log)
        cls.templates = TemplateGenerator(cls.config, cls.state, cls.vm_manager, cls.log)
        cls.output_dir = tempfile.mkdtemp(prefix="mosk_test_")
        cls.templates.render_mosk_templates(cls.output_dir)

    @classmethod
    def tearDownClass(cls):
        """Clean up temp directory."""
        if os.path.exists(cls.output_dir):
            shutil.rmtree(cls.output_dir)

    def test_all_yaml_files_are_valid(self):
        """All rendered YAML files should be parseable."""
        yaml_files = list(Path(self.output_dir).rglob("*.yaml"))
        for yaml_file in yaml_files:
            with self.subTest(file=yaml_file.name):
                content = yaml_file.read_text()
                try:
                    # Parse all documents in the file
                    docs = list(self.yaml.safe_load_all(content))
                    self.assertIsNotNone(docs)
                except self.yaml.YAMLError as e:
                    self.fail(f"Invalid YAML in {yaml_file}: {e}")

    def test_yaml_has_kubernetes_structure(self):
        """YAML files should have Kubernetes resource structure."""
        yaml_files = list(Path(self.output_dir).rglob("*.yaml"))
        for yaml_file in yaml_files:
            with self.subTest(file=yaml_file.name):
                content = yaml_file.read_text()
                docs = list(self.yaml.safe_load_all(content))
                for doc in docs:
                    if doc is not None:  # Skip empty documents
                        self.assertIn("apiVersion", doc, f"Missing apiVersion in {yaml_file}")
                        self.assertIn("kind", doc, f"Missing kind in {yaml_file}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
