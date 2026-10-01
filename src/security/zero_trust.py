"""APEX-OS Zero-Trust Security Layer.

mTLS certificate management, SPIFFE/SPIRE identity verification,
and mutual authentication.
"""
from __future__ import annotations

import datetime
import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID


# ── Exceptions ─────────────────────────────────────────────────────────


class SPIFFEVerificationError(Exception):
    """Raised when SPIFFE identity verification fails."""


class MutualAuthError(Exception):
    """Raised when mutual authentication fails."""


# ── SPIFFE Identity ────────────────────────────────────────────────────


class SPIFFEIdentity:
    """Represents a parsed SPIFFE ID.

    SPIFFE ID format: spiffe://<trust-domain>/ns/<namespace>/sa/<service-account>[/<path>]
    """

    def __init__(self, spiffe_id: str):
        parsed = urlparse(spiffe_id)

        if parsed.scheme != "spiffe":
            raise SPIFFEVerificationError(
                f"Invalid SPIFFE ID scheme: {parsed.scheme!r}, expected 'spiffe'"
            )

        self.trust_domain = parsed.netloc
        if not self.trust_domain:
            raise SPIFFEVerificationError("SPIFFE ID trust domain cannot be empty")

        parts = parsed.path.strip("/").split("/")
        if len(parts) < 4 or parts[0] != "ns" or parts[2] != "sa":
            raise SPIFFEVerificationError(
                f"Invalid SPIFFE ID format: {spiffe_id!r}. "
                "Expected: spiffe://<trust-domain>/ns/<namespace>/sa/<service-account>"
            )

        self.namespace = parts[1]
        self.service_account = parts[3]
        self.path = "/" + "/".join(parts[4:]) if len(parts) > 4 else ""

    @classmethod
    def parse(cls, spiffe_id: str) -> SPIFFEIdentity:
        """Parse a SPIFFE ID string into components."""
        return cls(spiffe_id)

    @classmethod
    def from_cert(cls, cert: x509.Certificate) -> SPIFFEIdentity:
        """Extract SPIFFE ID from a certificate's SAN extension."""
        try:
            san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        except x509.ExtensionNotFound:
            raise SPIFFEVerificationError(
                "No SPIFFE ID found: certificate has no SubjectAlternativeName extension"
            )

        for name in san.value:
            if isinstance(name, x509.UniformResourceIdentifier):
                if name.value.startswith("spiffe://"):
                    return cls.parse(name.value)

        raise SPIFFEVerificationError(
            "No SPIFFE ID found: certificate SAN contains no spiffe:// URI"
        )

    def is_valid_trust_domain(self, allowed_domains: list[str]) -> bool:
        """Check if this identity's trust domain is in the allowed list."""
        return self.trust_domain in allowed_domains

    def __str__(self) -> str:
        base = f"spiffe://{self.trust_domain}/ns/{self.namespace}/sa/{self.service_account}"
        if self.path:
            base += self.path
        return base


# ── Certificate Manager ────────────────────────────────────────────────


class CertificateManager:
    """Manages mTLS certificate lifecycle: generation, persistence, inspection."""

    def __init__(self, key_algorithm: str = "rsa", key_size: int = 2048):
        self.key_algorithm = key_algorithm
        self.key_size = key_size

    def _generate_key(self):
        """Generate a private key based on configured algorithm."""
        if self.key_algorithm == "rsa":
            return rsa.generate_private_key(
                public_exponent=65537,
                key_size=self.key_size,
            )
        elif self.key_algorithm == "ec":
            return ec.generate_private_key(ec.SECP256R1())
        else:
            raise ValueError(f"Unsupported key algorithm: {self.key_algorithm}")

    def generate_self_signed(
        self,
        common_name: str,
        validity_days: int = 90,
        organization: str = "APEX-OS",
    ) -> tuple[x509.Certificate, Any]:
        """Generate a self-signed certificate."""
        key = self._generate_key()
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, organization),
        ])

        now = datetime.datetime.utcnow()
        cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(issuer)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now)
            .not_valid_after(now + datetime.timedelta(days=validity_days))
            .add_extension(
                x509.BasicConstraints(ca=False, path_length=None),
                critical=True,
            )
            .add_extension(
                x509.ExtendedKeyUsage([
                    ExtendedKeyUsageOID.SERVER_AUTH,
                    ExtendedKeyUsageOID.CLIENT_AUTH,
                ]),
                critical=False,
            )
            .add_extension(
                x509.SubjectAlternativeName([x509.DNSName(common_name)]),
                critical=False,
            )
            .sign(key, hashes.SHA256())
        )
        return cert, key

    def save_cert(self, cert: x509.Certificate, path: str | Path) -> None:
        """Save a certificate to a PEM file."""
        pem = cert.public_bytes(serialization.Encoding.PEM)
        Path(path).write_bytes(pem)

    def save_key(self, key: Any, path: str | Path) -> None:
        """Save a private key to a PEM file."""
        pem = key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        Path(path).write_bytes(pem)

    def load_cert(self, path: str | Path) -> x509.Certificate:
        """Load a certificate from a PEM file."""
        path_obj = Path(path)
        if not path_obj.exists():
            raise FileNotFoundError(f"Certificate file not found: {path}")
        pem = path_obj.read_bytes()
        return x509.load_pem_x509_certificate(pem)

    def load_key(self, path: str | Path) -> Any:
        """Load a private key from a PEM file."""
        path_obj = Path(path)
        if not path_obj.exists():
            raise FileNotFoundError(f"Key file not found: {path}")
        pem = path_obj.read_bytes()
        return serialization.load_pem_private_key(pem, password=None)

    def is_expired(self, cert: x509.Certificate) -> bool:
        """Check if a certificate is expired."""
        return datetime.datetime.utcnow() >= cert.not_valid_after

    def is_expiring_soon(self, cert: x509.Certificate, days_threshold: int = 14) -> bool:
        """Check if a certificate expires within the given threshold."""
        threshold = datetime.datetime.utcnow() + datetime.timedelta(days=days_threshold)
        return cert.not_valid_after <= threshold

    def fingerprint(self, cert: x509.Certificate) -> str:
        """Compute the SHA-256 fingerprint of a certificate."""
        return cert.fingerprint(hashes.SHA256()).hex()

    def get_serial_number(self, cert: x509.Certificate) -> int:
        """Get the serial number of a certificate."""
        return cert.serial_number

    def is_valid_at(self, cert: x509.Certificate, when: datetime.datetime | None = None) -> bool:
        """Check if a certificate is valid at a given time."""
        if when is None:
            when = datetime.datetime.utcnow()
        return cert.not_valid_before <= when <= cert.not_valid_after


# ── Mutual Authenticator ───────────────────────────────────────────────


class MutualAuthenticator:
    """Performs mutual authentication using mTLS certificates and SPIFFE identities."""

    def __init__(
        self,
        trust_domain: str,
        allowed_service_accounts: list[str] | None = None,
        mtls_required: bool = True,
    ):
        self.trust_domain = trust_domain
        self.allowed_service_accounts = allowed_service_accounts or []
        self.mtls_required = mtls_required

    def verify_peer(
        self,
        peer_cert: x509.Certificate,
        ca_cert: x509.Certificate,
    ) -> bool:
        """Verify a peer certificate against the trust chain."""
        now = datetime.datetime.utcnow()

        # Check temporal validity
        if now < peer_cert.not_valid_before:
            raise SPIFFEVerificationError(
                f"Peer certificate is not yet valid (valid from {peer_cert.not_valid_before})"
            )
        if now >= peer_cert.not_valid_after:
            raise SPIFFEVerificationError(
                f"Peer certificate has expired (expired at {peer_cert.not_valid_after})"
            )

        # Verify the certificate was signed by the trusted CA
        try:
            ca_public_key = ca_cert.public_key()
            from cryptography.hazmat.primitives.asymmetric import padding

            # Get the signature algorithm to determine padding
            sig_alg = peer_cert.signature_algorithm_oid

            # Map signature algorithms to padding
            if "rsa" in sig_alg._name.lower():
                # Try PKCS1v15 first (most common for RSA certs)
                try:
                    ca_public_key.verify(
                        peer_cert.signature,
                        peer_cert.tbs_certificate_bytes,
                        padding.PKCS1v15(),
                        peer_cert.signature_hash_algorithm,
                    )
                except Exception:
                    # Try PSS as fallback
                    ca_public_key.verify(
                        peer_cert.signature,
                        peer_cert.tbs_certificate_bytes,
                        padding.PSS(
                            mgf=padding.MGF1(peer_cert.signature_hash_algorithm),
                            salt_length=padding.PSS.DIGEST_LENGTH,
                        ),
                        peer_cert.signature_hash_algorithm,
                    )
            elif "ecdsa" in sig_alg._name.lower():
                ca_public_key.verify(
                    peer_cert.signature,
                    peer_cert.tbs_certificate_bytes,
                    ec.ECDSA(peer_cert.signature_hash_algorithm),
                )
            else:
                raise SPIFFEVerificationError(
                    f"Unsupported signature algorithm: {sig_alg._name}"
                )
        except SPIFFEVerificationError:
            raise
        except Exception as e:
            raise SPIFFEVerificationError(
                f"Peer certificate signature verification failed: {e}"
            )

        # Extract and verify SPIFFE identity
        try:
            spiffe_id = SPIFFEIdentity.from_cert(peer_cert)
        except SPIFFEVerificationError:
            raise

        if spiffe_id.trust_domain != self.trust_domain:
            raise SPIFFEVerificationError(
                f"Peer trust domain {spiffe_id.trust_domain!r} does not match "
                f"expected {self.trust_domain!r}"
            )

        # Check service account allowlist
        if self.allowed_service_accounts:
            if spiffe_id.service_account not in self.allowed_service_accounts:
                raise SPIFFEVerificationError(
                    f"Service account {spiffe_id.service_account!r} not in allowlist"
                )

        return True

    def authenticate(
        self,
        client_cert: x509.Certificate,
        server_cert: x509.Certificate,
        ca_cert: x509.Certificate,
    ) -> bool:
        """Perform mutual authentication between client and server."""
        self.verify_peer(client_cert, ca_cert)
        self.verify_peer(server_cert, ca_cert)
        return True


# ── Configuration ───────────────────────────────────────────────────────


@dataclass
class ZeroTrustConfig:
    """Configuration for the zero-trust security layer."""

    trust_domain: str = "example.org"
    mtls_required: bool = True
    cert_validity_days: int = 90
    allowed_service_accounts: list[str] = field(default_factory=list)
    ca_cert_path: str | None = None
    cert_path: str | None = None
    key_path: str | None = None

    @classmethod
    def from_env(cls) -> ZeroTrustConfig:
        """Load configuration from environment variables."""
        trust_domain = os.environ.get("APEX_TRUST_DOMAIN", "example.org")
        mtls_required = os.environ.get("APEX_MTLS_REQUIRED", "true").lower() != "false"
        cert_validity_days = int(os.environ.get("APEX_CERT_VALIDITY_DAYS", "90"))

        allowed_accounts = os.environ.get("APEX_ALLOWED_SERVICE_ACCOUNTS", "")
        accounts_list = [a.strip() for a in allowed_accounts.split(",") if a.strip()] if allowed_accounts else []

        return cls(
            trust_domain=trust_domain,
            mtls_required=mtls_required,
            cert_validity_days=cert_validity_days,
            allowed_service_accounts=accounts_list,
            ca_cert_path=os.environ.get("APEX_CA_CERT_PATH"),
            cert_path=os.environ.get("APEX_CERT_PATH"),
            key_path=os.environ.get("APEX_KEY_PATH"),
        )
