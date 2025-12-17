"""
TLS Certificate Generation Module

Generates self-signed CA and server certificates for MCC/MOSK deployment.
"""

import base64
import datetime
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

from .logger import get_logger

logger = get_logger("certs")


@dataclass
class CertificateInfo:
    """Certificate information."""
    ca_cert: str
    ca_key: str
    server_cert: str
    server_key: str
    ca_cert_b64: str
    server_cert_b64: str
    server_key_b64: str


class CertificateGenerator:
    """
    Generates TLS certificates for MCC/MOSK deployment.

    Creates:
    - Root CA certificate
    - Server certificate signed by CA
    - Wildcard certificates for services
    """

    DEFAULT_VALIDITY_DAYS = 3650  # 10 years
    DEFAULT_KEY_SIZE = 4096

    def __init__(
        self,
        output_dir: Optional[str] = None,
        validity_days: int = DEFAULT_VALIDITY_DAYS,
        key_size: int = DEFAULT_KEY_SIZE,
    ):
        """
        Initialize certificate generator.

        Args:
            output_dir: Directory to store certificates
            validity_days: Certificate validity in days
            key_size: RSA key size
        """
        self.output_dir = Path(output_dir) if output_dir else Path.cwd() / "certs"
        self.validity_days = validity_days
        self.key_size = key_size

    def generate_ca(
        self,
        common_name: str = "MCC-MOSK Root CA",
        organization: str = "MCC Virtual Deployment",
        country: str = "US",
        state: str = "California",
        locality: str = "San Francisco",
    ) -> Tuple[str, str]:
        """
        Generate a root CA certificate.

        Args:
            common_name: CA common name
            organization: Organization name
            country: Country code
            state: State/Province
            locality: City

        Returns:
            Tuple of (ca_cert_pem, ca_key_pem)
        """
        self.output_dir.mkdir(parents=True, exist_ok=True)

        ca_key_path = self.output_dir / "ca.key"
        ca_cert_path = self.output_dir / "ca.crt"

        # Generate CA private key with proper error handling
        try:
            result = subprocess.run([
                "openssl", "genrsa",
                "-out", str(ca_key_path),
                str(self.key_size),
            ], check=True, capture_output=True)
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to generate CA private key: {e.stderr.decode() if e.stderr else str(e)}")
            raise

        # Create CA certificate config
        ca_config = f"""
[req]
default_bits = {self.key_size}
prompt = no
default_md = sha256
distinguished_name = dn
x509_extensions = v3_ca

[dn]
C = {country}
ST = {state}
L = {locality}
O = {organization}
CN = {common_name}

[v3_ca]
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always,issuer
basicConstraints = critical, CA:true
keyUsage = critical, digitalSignature, cRLSign, keyCertSign
"""

        with tempfile.NamedTemporaryFile(mode='w', suffix='.cnf', delete=False) as f:
            f.write(ca_config)
            config_path = f.name

        try:
            # Generate CA certificate with proper error handling
            try:
                subprocess.run([
                    "openssl", "req",
                    "-x509", "-new", "-nodes",
                    "-key", str(ca_key_path),
                    "-sha256",
                    "-days", str(self.validity_days),
                    "-out", str(ca_cert_path),
                    "-config", config_path,
                ], check=True, capture_output=True)
            except subprocess.CalledProcessError as e:
                logger.error(f"Failed to generate CA certificate: {e.stderr.decode() if e.stderr else str(e)}")
                raise
        finally:
            os.unlink(config_path)

        ca_cert = ca_cert_path.read_text()
        ca_key = ca_key_path.read_text()

        logger.info(f"Generated CA certificate: {ca_cert_path}")
        return ca_cert, ca_key

    def generate_server_cert(
        self,
        ca_cert_path: str,
        ca_key_path: str,
        common_name: str,
        san_domains: list,
        san_ips: Optional[list] = None,
        organization: str = "MCC Virtual Deployment",
        country: str = "US",
        state: str = "California",
        locality: str = "San Francisco",
    ) -> Tuple[str, str]:
        """
        Generate a server certificate signed by CA.

        Args:
            ca_cert_path: Path to CA certificate
            ca_key_path: Path to CA private key
            common_name: Server common name
            san_domains: List of SAN domains (supports wildcards)
            san_ips: List of SAN IP addresses
            organization: Organization name
            country: Country code
            state: State/Province
            locality: City

        Returns:
            Tuple of (server_cert_pem, server_key_pem)
        """
        server_key_path = self.output_dir / f"{common_name.replace('*', 'wildcard').replace('.', '_')}.key"
        server_csr_path = self.output_dir / f"{common_name.replace('*', 'wildcard').replace('.', '_')}.csr"
        server_cert_path = self.output_dir / f"{common_name.replace('*', 'wildcard').replace('.', '_')}.crt"

        # Build SAN entries
        san_entries = []
        for i, domain in enumerate(san_domains):
            san_entries.append(f"DNS.{i + 1} = {domain}")
        if san_ips:
            for i, ip in enumerate(san_ips):
                san_entries.append(f"IP.{i + 1} = {ip}")

        san_string = "\n".join(san_entries)

        # Create server certificate config
        server_config = f"""
[req]
default_bits = {self.key_size}
prompt = no
default_md = sha256
distinguished_name = dn
req_extensions = req_ext

[dn]
C = {country}
ST = {state}
L = {locality}
O = {organization}
CN = {common_name}

[req_ext]
subjectAltName = @alt_names

[alt_names]
{san_string}

[v3_ext]
authorityKeyIdentifier = keyid,issuer
basicConstraints = CA:FALSE
keyUsage = digitalSignature, nonRepudiation, keyEncipherment, dataEncipherment
extendedKeyUsage = serverAuth, clientAuth
subjectAltName = @alt_names
"""

        with tempfile.NamedTemporaryFile(mode='w', suffix='.cnf', delete=False) as f:
            f.write(server_config)
            config_path = f.name

        try:
            # Generate server private key with proper error handling
            try:
                subprocess.run([
                    "openssl", "genrsa",
                    "-out", str(server_key_path),
                    str(self.key_size),
                ], check=True, capture_output=True)
            except subprocess.CalledProcessError as e:
                logger.error(f"Failed to generate server private key: {e.stderr.decode() if e.stderr else str(e)}")
                raise

            # Generate CSR with proper error handling
            try:
                subprocess.run([
                    "openssl", "req",
                    "-new",
                    "-key", str(server_key_path),
                    "-out", str(server_csr_path),
                    "-config", config_path,
                ], check=True, capture_output=True)
            except subprocess.CalledProcessError as e:
                logger.error(f"Failed to generate CSR: {e.stderr.decode() if e.stderr else str(e)}")
                raise

            # Sign with CA with proper error handling
            try:
                subprocess.run([
                    "openssl", "x509",
                    "-req",
                    "-in", str(server_csr_path),
                    "-CA", ca_cert_path,
                    "-CAkey", ca_key_path,
                    "-CAcreateserial",
                    "-out", str(server_cert_path),
                    "-days", str(self.validity_days),
                    "-sha256",
                    "-extfile", config_path,
                    "-extensions", "v3_ext",
                ], check=True, capture_output=True)
            except subprocess.CalledProcessError as e:
                logger.error(f"Failed to sign server certificate: {e.stderr.decode() if e.stderr else str(e)}")
                raise

        finally:
            os.unlink(config_path)

        # Clean up CSR
        server_csr_path.unlink(missing_ok=True)

        server_cert = server_cert_path.read_text()
        server_key = server_key_path.read_text()

        logger.info(f"Generated server certificate: {server_cert_path}")
        return server_cert, server_key

    def generate_mcc_mosk_certs(
        self,
        domain: str = "it.just.works",
        api_ips: Optional[list] = None,
    ) -> CertificateInfo:
        """
        Generate all certificates needed for MCC/MOSK deployment.

        Args:
            domain: Base domain for services
            api_ips: List of API endpoint IPs

        Returns:
            CertificateInfo with all certificates
        """
        logger.info(f"Generating certificates for domain: {domain}")

        # Generate CA
        ca_cert, ca_key = self.generate_ca()

        ca_cert_path = self.output_dir / "ca.crt"
        ca_key_path = self.output_dir / "ca.key"

        # Generate wildcard server cert
        san_domains = [
            f"*.{domain}",
            domain,
            "*.openstack.svc.cluster.local",
            "*.rook-ceph.svc.cluster.local",
            "localhost",
        ]

        san_ips = ["127.0.0.1"]
        if api_ips:
            san_ips.extend(api_ips)

        server_cert, server_key = self.generate_server_cert(
            ca_cert_path=str(ca_cert_path),
            ca_key_path=str(ca_key_path),
            common_name=f"*.{domain}",
            san_domains=san_domains,
            san_ips=san_ips,
        )

        # Create base64 encoded versions for Kubernetes secrets
        ca_cert_b64 = base64.b64encode(ca_cert.encode()).decode()
        server_cert_b64 = base64.b64encode(server_cert.encode()).decode()
        server_key_b64 = base64.b64encode(server_key.encode()).decode()

        return CertificateInfo(
            ca_cert=ca_cert,
            ca_key=ca_key,
            server_cert=server_cert,
            server_key=server_key,
            ca_cert_b64=ca_cert_b64,
            server_cert_b64=server_cert_b64,
            server_key_b64=server_key_b64,
        )

    def generate_openstack_certs(
        self,
        domain: str = "it.just.works",
        api_ips: Optional[list] = None,
    ) -> CertificateInfo:
        """
        Generate certificates specifically for OpenStack services.

        Args:
            domain: Base domain for services
            api_ips: List of API endpoint IPs

        Returns:
            CertificateInfo with all certificates
        """
        return self.generate_mcc_mosk_certs(domain=domain, api_ips=api_ips)


def generate_certificates(
    output_dir: str,
    domain: str = "it.just.works",
    api_ips: Optional[list] = None,
) -> CertificateInfo:
    """
    Convenience function to generate all needed certificates.

    Args:
        output_dir: Output directory for certificates
        domain: Base domain
        api_ips: API endpoint IPs

    Returns:
        CertificateInfo
    """
    generator = CertificateGenerator(output_dir=output_dir)
    return generator.generate_mcc_mosk_certs(domain=domain, api_ips=api_ips)
