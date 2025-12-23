"""
Tests for deployer integration with Jinja2 templates.
"""

import os
import sys
import tempfile
import shutil
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.config import Config
from lib.state import StateManager
from lib.vm_manager import VMManager
from lib.templates import TemplateGenerator
from lib.logger import DeploymentLogger


class TestDeployerTemplateIntegration(unittest.TestCase):
    """Test deployer's template integration."""

    @classmethod
    def setUpClass(cls):
        cls.config = Config(str(Path(__file__).parent.parent / "config.yaml"))
        cls.state = StateManager()
        cls.log = DeploymentLogger("test")
        cls.vm_manager = VMManager(cls.config, cls.state, cls.log)
        cls.templates = TemplateGenerator(cls.config, cls.state, cls.vm_manager, cls.log)

    def setUp(self):
        self.output_dir = tempfile.mkdtemp(prefix="mosk_test_")

    def tearDown(self):
        if os.path.exists(self.output_dir):
            shutil.rmtree(self.output_dir)

    def test_templates_render_to_mosk_dir(self):
        """Templates should render to mosk/ directory structure."""
        self.templates.render_mosk_templates(self.output_dir)

        # Check expected files exist
        expected_files = [
            "01-namespace.yaml",
            "02-metallbconfig.yaml",
            "04-cluster.yaml",
            "05-bmhp-ctl.yaml",
            "05-bmhp-cmp.yaml",
            "06-l2template.yaml",
            "07-subnet.yaml",
        ]

        for filename in expected_files:
            filepath = Path(self.output_dir) / filename
            self.assertTrue(filepath.exists(), f"Expected file not found: {filename}")

    def test_templates_render_bmh_subdir(self):
        """Templates should render BMH files to 03-bmh/ subdirectory."""
        self.templates.render_mosk_templates(self.output_dir)

        bmh_dir = Path(self.output_dir) / "03-bmh"
        self.assertTrue(bmh_dir.exists())

        expected_files = ["01-bmh-control.yaml", "02-bmh-compute.yaml"]
        for filename in expected_files:
            filepath = bmh_dir / filename
            self.assertTrue(filepath.exists(), f"Expected BMH file not found: {filename}")

    def test_templates_render_machines_subdir(self):
        """Templates should render machine files to 08-machines/ subdirectory."""
        self.templates.render_mosk_templates(self.output_dir)

        machines_dir = Path(self.output_dir) / "08-machines"
        self.assertTrue(machines_dir.exists())

        expected_files = ["01-machines-control.yaml", "02-machines-compute.yaml"]
        for filename in expected_files:
            filepath = machines_dir / filename
            self.assertTrue(filepath.exists(), f"Expected machines file not found: {filename}")

    def test_templates_render_osdpl_subdir(self):
        """Templates should render OSDPL files to 10-osdpl/ subdirectory."""
        self.templates.render_mosk_templates(self.output_dir)

        osdpl_dir = Path(self.output_dir) / "10-osdpl"
        self.assertTrue(osdpl_dir.exists())

        expected_files = ["osdpl-secret.yaml", "osdpl.yaml"]
        for filename in expected_files:
            filepath = osdpl_dir / filename
            self.assertTrue(filepath.exists(), f"Expected OSDPL file not found: {filename}")

    def test_template_output_matches_deployer_expectations(self):
        """Template output paths should match what deployer.py expects."""
        self.templates.render_mosk_templates(self.output_dir)

        # These are the exact paths the deployer expects
        deployer_expected_paths = [
            "01-namespace.yaml",
            "02-metallbconfig.yaml",
            "03-bmh/01-bmh-control.yaml",
            "03-bmh/02-bmh-compute.yaml",
            "04-cluster.yaml",
            "05-bmhp-ctl.yaml",
            "05-bmhp-cmp.yaml",
            "06-l2template.yaml",
            "07-subnet.yaml",
            "08-machines/01-machines-control.yaml",
            "08-machines/02-machines-compute.yaml",
            "10-osdpl/osdpl-secret.yaml",
            "10-osdpl/osdpl.yaml",
        ]

        for path in deployer_expected_paths:
            filepath = Path(self.output_dir) / path
            self.assertTrue(filepath.exists(), f"Deployer-expected path not found: {path}")


class TestMiraCephGeneration(unittest.TestCase):
    """Test MiraCeph manifest generation."""

    @classmethod
    def setUpClass(cls):
        cls.config = Config(str(Path(__file__).parent.parent / "config.yaml"))
        cls.state = StateManager()
        cls.log = DeploymentLogger("test")
        cls.vm_manager = VMManager(cls.config, cls.state, cls.log)
        cls.templates = TemplateGenerator(cls.config, cls.state, cls.vm_manager, cls.log)

    def setUp(self):
        self.output_dir = tempfile.mkdtemp(prefix="mosk_test_")

    def tearDown(self):
        if os.path.exists(self.output_dir):
            shutil.rmtree(self.output_dir)

    def test_generate_miraceph_manifest(self):
        """MiraCeph manifest should be generated."""
        output_path = self.templates.generate_miraceph_manifest(self.output_dir)
        self.assertTrue(Path(output_path).exists())

    def test_miraceph_content_valid(self):
        """MiraCeph manifest should have valid content."""
        output_path = self.templates.generate_miraceph_manifest(self.output_dir)
        content = Path(output_path).read_text()

        self.assertIn("apiVersion:", content)
        self.assertNotIn("{{", content)
        self.assertNotIn("}}", content)


class TestStorageModeTemplates(unittest.TestCase):
    """Test storage mode affects template generation."""

    @classmethod
    def setUpClass(cls):
        cls.config = Config(str(Path(__file__).parent.parent / "config.yaml"))
        cls.state = StateManager()
        cls.log = DeploymentLogger("test")
        cls.vm_manager = VMManager(cls.config, cls.state, cls.log)
        cls.templates = TemplateGenerator(cls.config, cls.state, cls.vm_manager, cls.log)

    def setUp(self):
        self.output_dir = tempfile.mkdtemp(prefix="mosk_test_")

    def tearDown(self):
        if os.path.exists(self.output_dir):
            shutil.rmtree(self.output_dir)

    def test_hyperconverged_no_storage_templates(self):
        """Hyperconverged mode should not generate storage node templates."""
        if self.config.is_hyperconverged:
            self.templates.render_mosk_templates(self.output_dir)

            # Storage templates should NOT exist
            storage_bmh = Path(self.output_dir) / "03-bmh" / "03-bmh-storage.yaml"
            storage_bmhp = Path(self.output_dir) / "05-bmhp-storage.yaml"
            storage_machines = Path(self.output_dir) / "08-machines" / "03-machines-storage.yaml"

            self.assertFalse(storage_bmh.exists(), "Storage BMH should not exist in hyperconverged mode")
            self.assertFalse(storage_bmhp.exists(), "Storage BMHP should not exist in hyperconverged mode")
            self.assertFalse(storage_machines.exists(), "Storage machines should not exist in hyperconverged mode")
        else:
            self.skipTest("Config is not hyperconverged, skipping test")

    def test_dedicated_storage_templates(self):
        """Dedicated storage mode should generate storage node templates."""
        if not self.config.is_hyperconverged:
            self.templates.render_mosk_templates(self.output_dir)

            # Storage templates SHOULD exist
            storage_bmh = Path(self.output_dir) / "03-bmh" / "03-bmh-storage.yaml"
            storage_bmhp = Path(self.output_dir) / "05-bmhp-storage.yaml"
            storage_machines = Path(self.output_dir) / "08-machines" / "03-machines-storage.yaml"

            self.assertTrue(storage_bmh.exists(), "Storage BMH should exist in dedicated mode")
            self.assertTrue(storage_bmhp.exists(), "Storage BMHP should exist in dedicated mode")
            self.assertTrue(storage_machines.exists(), "Storage machines should exist in dedicated mode")
        else:
            self.skipTest("Config is hyperconverged, skipping test")


class TestTemplateEngine(unittest.TestCase):
    """Test template engine functionality."""

    @classmethod
    def setUpClass(cls):
        cls.config = Config(str(Path(__file__).parent.parent / "config.yaml"))
        cls.state = StateManager()
        cls.log = DeploymentLogger("test")
        cls.vm_manager = VMManager(cls.config, cls.state, cls.log)
        cls.templates = TemplateGenerator(cls.config, cls.state, cls.vm_manager, cls.log)

    def test_engine_initialized(self):
        """Template engine should be initialized."""
        self.assertIsNotNone(self.templates.engine)

    def test_engine_can_render(self):
        """Template engine should be able to render templates."""
        # This tests the engine's render capability
        context = self.templates.build_mosk_context()
        self.assertIsNotNone(context)
        self.assertIn("mosk_namespace", context)


if __name__ == "__main__":
    unittest.main(verbosity=2)
