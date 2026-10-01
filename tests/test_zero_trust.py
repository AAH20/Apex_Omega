"""Unit tests for APEX-OS Zero-Trust Security Layer.

Covers mTLS certificate management, SPIFFE/SPIRE identity verification,
and mutual authentication.
"""
import datetime
import ipaddress
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from src.security.zero_trust import (
    CertificateManager,
    MutualAuthenticator,
    SPIFFEIdentity,
    SPIFFEVerificationError,
    ZeroTrustConfig,
)


# ── Helpers ────────────────────────────────────────────────────────────


def _generate_ca_cert(common_name: str = "Test CA") -> tuple:
    """Generate a self-signed CA certificate and private key."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "APEX-OS Test"),
    ])
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow() - datetime.timedelta(days=1))
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=365))
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=None),
            critical=True,
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_encipherment=False,
                data_encipherment=False,
                content_commitment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )
    return cert, key


def _generate_leaf_cert(
    ca_cert: x509.Certificate,
    ca_key,
    common_name: str = "test.example.com",
    spiffe_id: str | None = None,
    san_dns: list[str] | None = None,
    san_ips: list[str] | None = None,
) -> tuple:
    """Generate a leaf certificate signed by the CA."""
    key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "APEX-OS Test"),
    ])

    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.datetime.utcnow() - datetime.timedelta(days=1))
        .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=90))
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
    )

    # Add SANs
    san_list = []
    if san_dns:
        for dns in san_dns:
            san_list.append(x509.DNSName(dns))
    if san_ips:
        for ip in san_ips:
            san_list.append(x509.IPAddress(ipaddress.ip_address(ip)))
    if san_list:
        builder = builder.add_extension(
            x509.SubjectAlternativeName(san_list),
            critical=False,
        )

    # Add SPIFFE ID as URI SAN if provided
    if spiffe_id:
        builder = builder.add_extension(
            x509.SubjectAlternativeName([x509.UniformResourceIdentifier(spiffe_id)]),
            critical=False,
        )

    cert = builder.sign(ca_key, hashes.SHA256())
    return cert, key


def _cert_to_pem(cert: x509.Certificate) -> bytes:
    return cert.public_bytes(serialization.Encoding.PEM)


def _key_to_pem(key) -> bytes:
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


# ── CertificateManager Tests ───────────────────────────────────────────


class TestCertificateManager:
    """Tests for mTLS certificate lifecycle management."""

    def test_generate_self_signed_cert(self):
        """CertificateManager can generate a self-signed certificate."""
        cm = CertificateManager()
        cert, key = cm.generate_self_signed("test.example.com")

        assert isinstance(cert, x509.Certificate)
        assert cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value == "test.example.com"
        assert cert.not_valid_before < datetime.datetime.utcnow() < cert.not_valid_after

    def test_generate_cert_with_custom_validity(self):
        """CertificateManager respects custom validity period."""
        cm = CertificateManager()
        cert, key = cm.generate_self_signed("test.example.com", validity_days=30)

        validity = cert.not_valid_after - cert.not_valid_before
        assert 29 <= validity.days <= 31

    def test_save_and_load_cert(self, tmp_path):
        """CertificateManager can save and load certificates."""
        cm = CertificateManager()
        cert, key = cm.generate_self_signed("test.example.com")

        cert_path = tmp_path / "cert.pem"
        key_path = tmp_path / "key.pem"

        cm.save_cert(cert, str(cert_path))
        cm.save_key(key, str(key_path))

        assert cert_path.exists()
        assert key_path.exists()

        loaded_cert = cm.load_cert(str(cert_path))
        loaded_key = cm.load_key(str(key_path))

        assert loaded_cert.subject == cert.subject
        assert loaded_key.private_numbers() == key.private_numbers()

    def test_load_cert_file_not_found(self):
        """CertificateManager raises on missing cert file."""
        cm = CertificateManager()
        with pytest.raises(FileNotFoundError):
            cm.load_cert("/nonexistent/cert.pem")

    def test_is_cert_expired(self):
        """CertificateManager detects expired certificates."""
        cm = CertificateManager()
        cert, _ = cm.generate_self_signed("test.example.com", validity_days=1)

        # Not expired yet
        assert not cm.is_expired(cert)

        # Create an expired cert by building one with past dates
        key = ec.generate_private_key(ec.SECP256R1())
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "expired")])
        expired_cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime.utcnow() - datetime.timedelta(days=10))
            .not_valid_after(datetime.datetime.utcnow() - datetime.timedelta(days=1))
            .sign(key, hashes.SHA256())
        )
        assert cm.is_expired(expired_cert)

    def test_is_cert_expiring_soon(self):
        """CertificateManager detects certificates expiring within threshold."""
        cm = CertificateManager()
        cert, _ = cm.generate_self_signed("test.example.com", validity_days=10)

        assert cm.is_expiring_soon(cert, days_threshold=15)
        assert not cm.is_expiring_soon(cert, days_threshold=5)

    def test_cert_fingerprint(self):
        """CertificateManager computes certificate fingerprint."""
        cm = CertificateManager()
        cert, _ = cm.generate_self_signed("test.example.com")

        fp = cm.fingerprint(cert)
        assert isinstance(fp, str)
        assert len(fp) == 64  # SHA-256 hex digest

    def test_cert_serial_number(self):
        """CertificateManager extracts serial number."""
        cm = CertificateManager()
        cert, _ = cm.generate_self_signed("test.example.com")

        serial = cm.get_serial_number(cert)
        assert isinstance(serial, int)
        assert serial > 0


# ── SPIFFEIdentity Tests ───────────────────────────────────────────────


class TestSPIFFEIdentity:
    """Tests for SPIFFE/SPIRE identity verification."""

    def test_parse_valid_spiffe_id(self):
        """SPIFFEIdentity parses a valid SPIFFE ID."""
        sid = SPIFFEIdentity("spiffe://example.org/ns/default/sa/my-service")
        assert sid.trust_domain == "example.org"
        assert sid.namespace == "default"
        assert sid.service_account == "my-service"

    def test_parse_spiffe_id_with_path(self):
        """SPIFFEIdentity parses SPIFFE ID with nested path."""
        sid = SPIFFEIdentity("spiffe://example.org/ns/prod/sa/api/v2")
        assert sid.trust_domain == "example.org"
        assert sid.namespace == "prod"
        assert sid.service_account == "api"
        assert sid.path == "/v2"

    def test_parse_invalid_scheme(self):
        """SPIFFEIdentity rejects non-SPIFFE URIs."""
        with pytest.raises(SPIFFEVerificationError, match="Invalid SPIFFE ID scheme"):
            SPIFFEIdentity("https://example.org/ns/default/sa/svc")

    def test_parse_invalid_format(self):
        """SPIFFEIdentity rejects malformed SPIFFE IDs."""
        with pytest.raises(SPIFFEVerificationError, match="Invalid SPIFFE ID format"):
            SPIFFEIdentity("spiffe://example.org")

    def test_parse_empty_trust_domain(self):
        """SPIFFEIdentity rejects empty trust domain."""
        with pytest.raises(SPIFFEVerificationError, match="trust domain cannot be empty"):
            SPIFFEIdentity("spiffe:///ns/default/sa/svc")

    def test_is_valid_trust_domain(self):
        """SPIFFEIdentity validates trust domain membership."""
        sid = SPIFFEIdentity("spiffe://example.org/ns/default/sa/svc")
        assert sid.is_valid_trust_domain(["example.org", "test.org"])
        assert not sid.is_valid_trust_domain(["other.org"])

    def test_extract_spiffe_id_from_cert(self):
        """SPIFFEIdentity extracts SPIFFE ID from certificate SAN."""
        ca_cert, ca_key = _generate_ca_cert()
        spiffe_uri = "spiffe://example.org/ns/default/sa/my-service"
        leaf_cert, _ = _generate_leaf_cert(ca_cert, ca_key, spiffe_id=spiffe_uri)

        sid = SPIFFEIdentity.from_cert(leaf_cert)
        assert sid.trust_domain == "example.org"
        assert sid.service_account == "my-service"

    def test_extract_spiffe_id_from_cert_no_san(self):
        """SPIFFEIdentity raises when cert has no SPIFFE SAN."""
        ca_cert, ca_key = _generate_ca_cert()
        leaf_cert, _ = _generate_leaf_cert(ca_cert, ca_key)

        with pytest.raises(SPIFFEVerificationError, match="No SPIFFE ID found"):
            SPIFFEIdentity.from_cert(leaf_cert)

    def test_spiffe_id_string_representation(self):
        """SPIFFEIdentity string round-trips correctly."""
        original = "spiffe://example.org/ns/default/sa/my-service"
        sid = SPIFFEIdentity(original)
        assert str(sid) == original


# ── MutualAuthenticator Tests ──────────────────────────────────────────


class TestMutualAuthenticator:
    """Tests for mutual authentication."""

    def test_verify_peer_cert_valid(self):
        """MutualAuthenticator accepts a valid peer certificate."""
        ca_cert, ca_key = _generate_ca_cert()
        leaf_cert, _ = _generate_leaf_cert(
            ca_cert, ca_key,
            spiffe_id="spiffe://example.org/ns/default/sa/client",
        )

        auth = MutualAuthenticator(trust_domain="example.org")
        result = auth.verify_peer(leaf_cert, ca_cert)

        assert result is True

    def test_verify_peer_cert_wrong_trust_domain(self):
        """MutualAuthenticator rejects cert from wrong trust domain."""
        ca_cert, ca_key = _generate_ca_cert()
        leaf_cert, _ = _generate_leaf_cert(
            ca_cert, ca_key,
            spiffe_id="spiffe://evil.org/ns/default/sa/attacker",
        )

        auth = MutualAuthenticator(trust_domain="example.org")
        with pytest.raises(SPIFFEVerificationError, match="trust domain"):
            auth.verify_peer(leaf_cert, ca_cert)

    def test_verify_peer_cert_expired(self):
        """MutualAuthenticator rejects expired certificates."""
        ca_cert, ca_key = _generate_ca_cert()
        # Create expired cert
        key = ec.generate_private_key(ec.SECP256R1())
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "expired")])
        expired_cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(ca_cert.subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime.utcnow() - datetime.timedelta(days=10))
            .not_valid_after(datetime.datetime.utcnow() - datetime.timedelta(days=1))
            .add_extension(
                x509.SubjectAlternativeName([
                    x509.UniformResourceIdentifier("spiffe://example.org/ns/default/sa/svc")
                ]),
                critical=False,
            )
            .sign(ca_key, hashes.SHA256())
        )

        auth = MutualAuthenticator(trust_domain="example.org")
        with pytest.raises(SPIFFEVerificationError, match="expired"):
            auth.verify_peer(expired_cert, ca_cert)

    def test_verify_peer_cert_not_yet_valid(self):
        """MutualAuthenticator rejects not-yet-valid certificates."""
        ca_cert, ca_key = _generate_ca_cert()
        key = ec.generate_private_key(ec.SECP256R1())
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "future")])
        future_cert = (
            x509.CertificateBuilder()
            .subject_name(subject)
            .issuer_name(ca_cert.subject)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(datetime.datetime.utcnow() + datetime.timedelta(days=1))
            .not_valid_after(datetime.datetime.utcnow() + datetime.timedelta(days=10))
            .add_extension(
                x509.SubjectAlternativeName([
                    x509.UniformResourceIdentifier("spiffe://example.org/ns/default/sa/svc")
                ]),
                critical=False,
            )
            .sign(ca_key, hashes.SHA256())
        )

        auth = MutualAuthenticator(trust_domain="example.org")
        with pytest.raises(SPIFFEVerificationError, match="not yet valid"):
            auth.verify_peer(future_cert, ca_cert)

    def test_verify_peer_cert_wrong_ca(self):
        """MutualAuthenticator rejects cert signed by wrong CA."""
        ca_cert1, ca_key1 = _generate_ca_cert("CA 1")
        ca_cert2, ca_key2 = _generate_ca_cert("CA 2")

        leaf_cert, _ = _generate_leaf_cert(
            ca_cert1, ca_key1,
            spiffe_id="spiffe://example.org/ns/default/sa/client",
        )

        auth = MutualAuthenticator(trust_domain="example.org")
        with pytest.raises(SPIFFEVerificationError, match="signature"):
            auth.verify_peer(leaf_cert, ca_cert2)

    def test_mutual_auth_both_sides_valid(self):
        """MutualAuthenticator succeeds when both sides present valid certs."""
        ca_cert, ca_key = _generate_ca_cert()

        client_cert, _ = _generate_leaf_cert(
            ca_cert, ca_key,
            spiffe_id="spiffe://example.org/ns/default/sa/client",
        )
        server_cert, _ = _generate_leaf_cert(
            ca_cert, ca_key,
            spiffe_id="spiffe://example.org/ns/default/sa/server",
        )

        auth = MutualAuthenticator(trust_domain="example.org")
        result = auth.authenticate(client_cert, server_cert, ca_cert)

        assert result is True

    def test_mutual_auth_client_cert_invalid(self):
        """MutualAuthenticator fails when client cert is invalid."""
        ca_cert, ca_key = _generate_ca_cert()

        # Client cert from wrong trust domain
        client_cert, _ = _generate_leaf_cert(
            ca_cert, ca_key,
            spiffe_id="spiffe://evil.org/ns/default/sa/attacker",
        )
        server_cert, _ = _generate_leaf_cert(
            ca_cert, ca_key,
            spiffe_id="spiffe://example.org/ns/default/sa/server",
        )

        auth = MutualAuthenticator(trust_domain="example.org")
        with pytest.raises(SPIFFEVerificationError):
            auth.authenticate(client_cert, server_cert, ca_cert)

    def test_authenticate_with_allowed_service_accounts(self):
        """MutualAuthenticator enforces service account allowlist."""
        ca_cert, ca_key = _generate_ca_cert()

        client_cert, _ = _generate_leaf_cert(
            ca_cert, ca_key,
            spiffe_id="spiffe://example.org/ns/default/sa/allowed-svc",
        )
        server_cert, _ = _generate_leaf_cert(
            ca_cert, ca_key,
            spiffe_id="spiffe://example.org/ns/default/sa/server",
        )

        auth = MutualAuthenticator(
            trust_domain="example.org",
            allowed_service_accounts=["allowed-svc", "server"],
        )
        result = auth.authenticate(client_cert, server_cert, ca_cert)
        assert result is True

    def test_authenticate_with_disallowed_service_account(self):
        """MutualAuthenticator rejects non-allowlisted service account."""
        ca_cert, ca_key = _generate_ca_cert()

        client_cert, _ = _generate_leaf_cert(
            ca_cert, ca_key,
            spiffe_id="spiffe://example.org/ns/default/sa/unauthorized",
        )
        server_cert, _ = _generate_leaf_cert(
            ca_cert, ca_key,
            spiffe_id="spiffe://example.org/ns/default/sa/server",
        )

        auth = MutualAuthenticator(
            trust_domain="example.org",
            allowed_service_accounts=["allowed-svc"],
        )
        with pytest.raises(SPIFFEVerificationError, match="not in allowlist"):
            auth.authenticate(client_cert, server_cert, ca_cert)


# ── ZeroTrustConfig Tests ──────────────────────────────────────────────


class TestZeroTrustConfig:
    """Tests for zero-trust configuration."""

    def test_default_config(self):
        """ZeroTrustConfig has sensible defaults."""
        config = ZeroTrustConfig()
        assert config.trust_domain == "example.org"
        assert config.mtls_required is True
        assert config.cert_validity_days == 90

    def test_custom_config(self):
        """ZeroTrustConfig accepts custom values."""
        config = ZeroTrustConfig(
            trust_domain="mycorp.internal",
            mtls_required=False,
            cert_validity_days=30,
            allowed_service_accounts=["api", "worker"],
        )
        assert config.trust_domain == "mycorp.internal"
        assert config.mtls_required is False
        assert config.cert_validity_days == 30
        assert config.allowed_service_accounts == ["api", "worker"]

    def test_config_from_env(self, monkeypatch):
        """ZeroTrustConfig loads from environment variables."""
        monkeypatch.setenv("APEX_TRUST_DOMAIN", "env.example.org")
        monkeypatch.setenv("APEX_MTLS_REQUIRED", "false")
        monkeypatch.setenv("APEX_CERT_VALIDITY_DAYS", "45")

        config = ZeroTrustConfig.from_env()
        assert config.trust_domain == "env.example.org"
        assert config.mtls_required is False
        assert config.cert_validity_days == 45
