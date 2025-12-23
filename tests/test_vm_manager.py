"""
Tests for VM Manager functionality.
"""

import sys
import unittest
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.config import Config
from lib.state import StateManager
from lib.vm_manager import VMManager
from lib.logger import DeploymentLogger


class TestVMManager(unittest.TestCase):
    """Test VM Manager initialization and methods."""

    @classmethod
    def setUpClass(cls):
        cls.config = Config(str(Path(__file__).parent.parent / "config.yaml"))
        cls.state = StateManager()
        cls.log = DeploymentLogger("test")
        cls.vm_manager = VMManager(cls.config, cls.state, cls.log)

    def test_vm_manager_initialization(self):
        """VM Manager should initialize without errors."""
        self.assertIsNotNone(self.vm_manager)

    def test_get_mcc_vm_info(self):
        """Should return MCC VM info."""
        vms = self.vm_manager.get_vm_info(role="mcc")
        self.assertIsInstance(vms, list)
        self.assertGreater(len(vms), 0, "Should have at least one MCC VM")

    def test_get_mosk_control_vm_info(self):
        """Should return MOSK control VM info."""
        vms = self.vm_manager.get_vm_info(role="mosk-ctl")
        self.assertIsInstance(vms, list)

    def test_get_mosk_compute_vm_info(self):
        """Should return MOSK compute VM info."""
        vms = self.vm_manager.get_vm_info(role="mosk-cmp")
        self.assertIsInstance(vms, list)

    def test_vm_info_has_required_fields(self):
        """VM info should have required fields."""
        vms = self.vm_manager.get_vm_info(role="mcc")
        for vm in vms:
            self.assertIn("index", vm)
            self.assertIn("name", vm)
            self.assertIn("mac_address", vm)
            self.assertIn("vbmc_port", vm)

    def test_vm_names_are_unique(self):
        """All VM names should be unique."""
        all_vms = []
        for role in ["mcc", "mosk-ctl", "mosk-cmp"]:
            all_vms.extend(self.vm_manager.get_vm_info(role=role))

        names = [vm["name"] for vm in all_vms]
        self.assertEqual(len(names), len(set(names)), "VM names should be unique")

    def test_vbmc_ports_are_unique(self):
        """All vBMC ports should be unique."""
        all_vms = []
        for role in ["mcc", "mosk-ctl", "mosk-cmp"]:
            all_vms.extend(self.vm_manager.get_vm_info(role=role))

        ports = [vm["vbmc_port"] for vm in all_vms]
        self.assertEqual(len(ports), len(set(ports)), "vBMC ports should be unique")

    def test_mac_addresses_are_unique(self):
        """All MAC addresses should be unique."""
        all_vms = []
        for role in ["mcc", "mosk-ctl", "mosk-cmp"]:
            all_vms.extend(self.vm_manager.get_vm_info(role=role))

        macs = [vm["mac_address"] for vm in all_vms]
        self.assertEqual(len(macs), len(set(macs)), "MAC addresses should be unique")

    def test_mac_address_format(self):
        """MAC addresses should be in valid format."""
        import re
        mac_pattern = re.compile(r'^([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}$')

        all_vms = []
        for role in ["mcc", "mosk-ctl", "mosk-cmp"]:
            all_vms.extend(self.vm_manager.get_vm_info(role=role))

        for vm in all_vms:
            mac = vm["mac_address"]
            self.assertIsNotNone(mac_pattern.match(mac), f"Invalid MAC format: {mac}")


class TestVMCounts(unittest.TestCase):
    """Test VM count calculations."""

    @classmethod
    def setUpClass(cls):
        cls.config = Config(str(Path(__file__).parent.parent / "config.yaml"))
        cls.state = StateManager()
        cls.log = DeploymentLogger("test")
        cls.vm_manager = VMManager(cls.config, cls.state, cls.log)

    def test_mcc_vm_count_matches_config(self):
        """MCC VM count should match config."""
        vms = self.vm_manager.get_vm_info(role="mcc")
        expected = self.config.mcc_topology.count
        self.assertEqual(len(vms), expected)

    def test_mosk_control_vm_count_matches_config(self):
        """MOSK control VM count should match config."""
        vms = self.vm_manager.get_vm_info(role="mosk-ctl")
        expected = self.config.mosk_control_topology.count
        self.assertEqual(len(vms), expected)

    def test_mosk_compute_vm_count_matches_config(self):
        """MOSK compute VM count should match config."""
        vms = self.vm_manager.get_vm_info(role="mosk-cmp")
        expected = self.config.mosk_compute_topology.count
        self.assertEqual(len(vms), expected)


if __name__ == "__main__":
    unittest.main(verbosity=2)
