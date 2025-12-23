"""
Tests for configuration loading and validation.
"""

import os
import sys
import unittest
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from lib.config import Config


class TestConfigLoading(unittest.TestCase):
    """Test configuration file loading."""

    def setUp(self):
        self.config_path = Path(__file__).parent.parent / "config.yaml"

    def test_config_file_exists(self):
        """Config file should exist."""
        self.assertTrue(self.config_path.exists(), f"Config file not found: {self.config_path}")

    def test_config_loads_without_error(self):
        """Config should load without errors."""
        config = Config(str(self.config_path))
        self.assertIsNotNone(config)

    def test_config_has_deployment_name(self):
        """Config should have deployment name."""
        config = Config(str(self.config_path))
        self.assertIsNotNone(config.deployment_name)
        self.assertIsInstance(config.deployment_name, str)

    def test_config_has_environment(self):
        """Config should have environment."""
        config = Config(str(self.config_path))
        self.assertIsNotNone(config.environment)


class TestMCCConfig(unittest.TestCase):
    """Test MCC configuration."""

    @classmethod
    def setUpClass(cls):
        cls.config = Config(str(Path(__file__).parent.parent / "config.yaml"))

    def test_mcc_topology_exists(self):
        """MCC topology should exist."""
        self.assertIsNotNone(self.config.mcc_topology)

    def test_mcc_topology_has_count(self):
        """MCC topology should have node count."""
        self.assertIsNotNone(self.config.mcc_topology.count)
        self.assertGreater(self.config.mcc_topology.count, 0)

    def test_mcc_topology_has_resources(self):
        """MCC topology should have resource settings."""
        self.assertIsNotNone(self.config.mcc_topology.resources)
        self.assertIsNotNone(self.config.mcc_topology.resources.vcpus)
        self.assertIsNotNone(self.config.mcc_topology.resources.ram_mb)

    def test_mcc_cluster_name(self):
        """MCC cluster name should be set."""
        self.assertIsNotNone(self.config.mcc_cluster_name)


class TestMOSKConfig(unittest.TestCase):
    """Test MOSK configuration."""

    @classmethod
    def setUpClass(cls):
        cls.config = Config(str(Path(__file__).parent.parent / "config.yaml"))

    def test_mosk_namespace(self):
        """MOSK namespace should be set."""
        self.assertIsNotNone(self.config.mosk_namespace)
        self.assertIsInstance(self.config.mosk_namespace, str)

    def test_mosk_control_topology(self):
        """MOSK control topology should exist."""
        self.assertIsNotNone(self.config.mosk_control_topology)
        self.assertIsNotNone(self.config.mosk_control_topology.count)

    def test_mosk_compute_topology(self):
        """MOSK compute topology should exist."""
        self.assertIsNotNone(self.config.mosk_compute_topology)
        self.assertIsNotNone(self.config.mosk_compute_topology.count)

    def test_mosk_dedicated_control_plane(self):
        """MOSK dedicated control plane setting should exist."""
        # This can be True or False
        self.assertIsNotNone(self.config.mosk_dedicated_control_plane)

    def test_storage_mode(self):
        """Storage mode should be set."""
        self.assertIsNotNone(self.config.storage_mode)
        self.assertIn(self.config.storage_mode, ["hyperconverged", "dedicated"])

    def test_is_hyperconverged(self):
        """is_hyperconverged should be consistent with storage_mode."""
        if self.config.storage_mode == "hyperconverged":
            self.assertTrue(self.config.is_hyperconverged)
        else:
            self.assertFalse(self.config.is_hyperconverged)


class TestNetworkConfig(unittest.TestCase):
    """Test network configuration."""

    @classmethod
    def setUpClass(cls):
        cls.config = Config(str(Path(__file__).parent.parent / "config.yaml"))

    def test_bridges_exist(self):
        """Network bridges should exist."""
        self.assertIsNotNone(self.config.bridges)

    def test_dns_servers(self):
        """DNS servers should be configured."""
        self.assertIsNotNone(self.config.dns_servers)
        self.assertIsInstance(self.config.dns_servers, list)


class TestCredentialsConfig(unittest.TestCase):
    """Test credentials configuration."""

    @classmethod
    def setUpClass(cls):
        cls.config = Config(str(Path(__file__).parent.parent / "config.yaml"))

    def test_bmc_username(self):
        """BMC username should be set."""
        self.assertIsNotNone(self.config.bmc_username)

    def test_bmc_password(self):
        """BMC password should be set."""
        self.assertIsNotNone(self.config.bmc_password)

    def test_root_password(self):
        """Root password should be set."""
        self.assertIsNotNone(self.config.root_password)


class TestCephConfig(unittest.TestCase):
    """Test Ceph configuration."""

    @classmethod
    def setUpClass(cls):
        cls.config = Config(str(Path(__file__).parent.parent / "config.yaml"))

    def test_ceph_osd_devices(self):
        """Ceph OSD devices should be configured."""
        self.assertIsNotNone(self.config.ceph_osd_devices)
        self.assertIsInstance(self.config.ceph_osd_devices, list)

    def test_ceph_pools(self):
        """Ceph pools should be configured."""
        self.assertIsNotNone(self.config.ceph_pools)


class TestTimeoutConfig(unittest.TestCase):
    """Test timeout configuration."""

    @classmethod
    def setUpClass(cls):
        cls.config = Config(str(Path(__file__).parent.parent / "config.yaml"))

    def test_timeout_bmh_provisioned(self):
        """BMH provisioned timeout should be set."""
        self.assertIsNotNone(self.config.timeout_bmh_provisioned)
        self.assertGreater(self.config.timeout_bmh_provisioned, 0)

    def test_timeout_machine_ready(self):
        """Machine ready timeout should be set."""
        self.assertIsNotNone(self.config.timeout_machine_ready)
        self.assertGreater(self.config.timeout_machine_ready, 0)

    def test_timeout_cluster_ready(self):
        """Cluster ready timeout should be set."""
        self.assertIsNotNone(self.config.timeout_cluster_ready)
        self.assertGreater(self.config.timeout_cluster_ready, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
