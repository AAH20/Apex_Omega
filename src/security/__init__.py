"""APEX-OS Zero-Trust Security Layer.

Provides mTLS certificate management, SPIFFE/SPIRE identity verification,
and mutual authentication for service-to-service communication.
"""
from src.security.zero_trust import (
    CertificateManager,
    MutualAuthenticator,
    SPIFFEIdentity,
    SPIFFEVerificationError,
    ZeroTrustConfig,
)

__all__ = [
    "CertificateManager",
    "MutualAuthenticator",
    "SPIFFEIdentity",
    "SPIFFEVerificationError",
    "ZeroTrustConfig",
]
