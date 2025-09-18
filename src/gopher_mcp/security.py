"""Security configuration and policy enforcement for Gemini protocol."""

import ssl
from enum import Enum
from typing import List, Optional, Set, Any
from dataclasses import dataclass, field

import structlog

logger = structlog.get_logger(__name__)


class TLSVersion(Enum):
    """Supported TLS versions."""

    TLS_1_2 = "TLSv1.2"
    TLS_1_3 = "TLSv1.3"


class CertificateValidationMode(Enum):
    """Certificate validation modes."""

    NONE = "none"  # No validation (not recommended)
    TOFU = "tofu"  # Trust-on-First-Use (recommended for Gemini)
    CA = "ca"  # Traditional CA validation
    STRICT = "strict"  # CA validation with strict hostname checking


class SecurityLevel(Enum):
    """Security levels for TLS configuration."""

    LOW = "low"  # Basic security, maximum compatibility
    MEDIUM = "medium"  # Balanced security and compatibility (default)
    HIGH = "high"  # High security, may reduce compatibility
    PARANOID = "paranoid"  # Maximum security, minimal compatibility


@dataclass
class TLSSecurityConfig:
    """Comprehensive TLS security configuration."""

    # TLS version requirements
    min_tls_version: TLSVersion = TLSVersion.TLS_1_2
    max_tls_version: Optional[TLSVersion] = None

    # Certificate validation
    cert_validation_mode: CertificateValidationMode = CertificateValidationMode.TOFU
    verify_hostname: bool = False  # Gemini typically uses TOFU instead

    # Cipher suite configuration
    security_level: SecurityLevel = SecurityLevel.MEDIUM
    custom_cipher_suites: Optional[List[str]] = None

    # Security policies
    require_sni: bool = True
    require_perfect_forward_secrecy: bool = True
    allow_legacy_renegotiation: bool = False

    # Connection security
    connection_timeout: float = 30.0
    handshake_timeout: float = 10.0

    # Certificate policies
    max_cert_chain_length: int = 10
    require_cert_transparency: bool = False

    # Allowed/blocked configurations
    allowed_hosts: Optional[Set[str]] = None
    blocked_hosts: Optional[Set[str]] = None
    allowed_cipher_families: Set[str] = field(
        default_factory=lambda: {"ECDHE", "AES", "GCM", "CHACHA20", "POLY1305"}
    )
    blocked_cipher_families: Set[str] = field(
        default_factory=lambda: {"RC4", "MD5", "SHA1", "DES", "3DES", "NULL", "EXPORT"}
    )

    def __post_init__(self) -> None:
        """Validate configuration after initialization."""
        if self.connection_timeout <= 0:
            raise ValueError("Connection timeout must be positive")

        if self.handshake_timeout <= 0:
            raise ValueError("Handshake timeout must be positive")

        if self.max_cert_chain_length <= 0:
            raise ValueError("Max certificate chain length must be positive")

        if self.allowed_hosts and self.blocked_hosts:
            overlap = self.allowed_hosts & self.blocked_hosts
            if overlap:
                raise ValueError(f"Hosts cannot be both allowed and blocked: {overlap}")


class TLSSecurityManager:
    """Manager for TLS security configuration and policy enforcement."""

    def __init__(self, config: Optional[TLSSecurityConfig] = None):
        """Initialize security manager.

        Args:
            config: Security configuration (uses defaults if None)
        """
        self.config = config or TLSSecurityConfig()
        self._cipher_suites_cache: Optional[List[str]] = None

    def create_ssl_context(self) -> ssl.SSLContext:
        """Create SSL context with security configuration.

        Returns:
            Configured SSL context

        Raises:
            ValueError: If configuration is invalid
            ssl.SSLError: If SSL context creation fails
        """
        try:
            # Create context based on security level
            if self.config.security_level == SecurityLevel.PARANOID:
                # Most restrictive context
                context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
                context.check_hostname = self.config.verify_hostname
                context.verify_mode = (
                    ssl.CERT_REQUIRED
                    if self.config.cert_validation_mode == CertificateValidationMode.CA
                    else ssl.CERT_NONE
                )
            else:
                # Use default context with secure settings
                context = ssl.create_default_context()
                context.check_hostname = self.config.verify_hostname
                context.verify_mode = self._get_verify_mode()

            # Set TLS version requirements
            context.minimum_version = self._get_ssl_version(self.config.min_tls_version)
            if self.config.max_tls_version:
                context.maximum_version = self._get_ssl_version(
                    self.config.max_tls_version
                )

            # Configure cipher suites
            cipher_suites = self._get_cipher_suites()
            if cipher_suites:
                context.set_ciphers(":".join(cipher_suites))

            # Security options
            context.options |= ssl.OP_NO_SSLv2 | ssl.OP_NO_SSLv3

            if not self.config.allow_legacy_renegotiation:
                context.options |= ssl.OP_NO_RENEGOTIATION

            # Additional security settings for paranoid mode
            if self.config.security_level == SecurityLevel.PARANOID:
                context.options |= ssl.OP_SINGLE_DH_USE | ssl.OP_SINGLE_ECDH_USE
                context.options |= ssl.OP_NO_COMPRESSION

            logger.info(
                "SSL context created",
                min_tls_version=self.config.min_tls_version.value,
                security_level=self.config.security_level.value,
                cert_validation=self.config.cert_validation_mode.value,
                cipher_count=len(cipher_suites) if cipher_suites else 0,
            )

            return context

        except Exception as e:
            logger.error("Failed to create SSL context", error=str(e))
            raise

    def _get_verify_mode(self) -> ssl.VerifyMode:
        """Get SSL verify mode based on configuration."""
        if self.config.cert_validation_mode == CertificateValidationMode.NONE:
            return ssl.CERT_NONE
        elif self.config.cert_validation_mode in (
            CertificateValidationMode.CA,
            CertificateValidationMode.STRICT,
        ):
            return ssl.CERT_REQUIRED
        else:  # TOFU
            return ssl.CERT_NONE  # TOFU handles validation separately

    def _get_ssl_version(self, version: TLSVersion) -> ssl.TLSVersion:
        """Convert TLSVersion enum to ssl.TLSVersion."""
        if version == TLSVersion.TLS_1_2:
            return ssl.TLSVersion.TLSv1_2
        elif version == TLSVersion.TLS_1_3:
            return ssl.TLSVersion.TLSv1_3
        else:
            raise ValueError(f"Unsupported TLS version: {version}")

    def _get_cipher_suites(self) -> List[str]:
        """Get cipher suites based on security configuration."""
        if self._cipher_suites_cache is not None:
            return self._cipher_suites_cache

        if self.config.custom_cipher_suites:
            # Use custom cipher suites
            cipher_suites = self.config.custom_cipher_suites.copy()
        else:
            # Generate cipher suites based on security level
            cipher_suites = self._generate_cipher_suites()

        # Filter out blocked cipher families
        filtered_suites = []
        for suite in cipher_suites:
            if not any(
                blocked in suite for blocked in self.config.blocked_cipher_families
            ):
                if any(
                    allowed in suite for allowed in self.config.allowed_cipher_families
                ):
                    filtered_suites.append(suite)

        self._cipher_suites_cache = filtered_suites
        return filtered_suites

    def _generate_cipher_suites(self) -> List[str]:
        """Generate cipher suites based on security level."""
        if self.config.security_level == SecurityLevel.LOW:
            # Basic security, maximum compatibility
            return [
                "ECDHE-ECDSA-AES256-GCM-SHA384",
                "ECDHE-RSA-AES256-GCM-SHA384",
                "ECDHE-ECDSA-AES128-GCM-SHA256",
                "ECDHE-RSA-AES128-GCM-SHA256",
                "ECDHE-ECDSA-AES256-SHA384",
                "ECDHE-RSA-AES256-SHA384",
                "ECDHE-ECDSA-AES128-SHA256",
                "ECDHE-RSA-AES128-SHA256",
            ]

        elif self.config.security_level == SecurityLevel.MEDIUM:
            # Balanced security and compatibility (default)
            return [
                "ECDHE-ECDSA-AES256-GCM-SHA384",
                "ECDHE-RSA-AES256-GCM-SHA384",
                "ECDHE-ECDSA-CHACHA20-POLY1305",
                "ECDHE-RSA-CHACHA20-POLY1305",
                "ECDHE-ECDSA-AES128-GCM-SHA256",
                "ECDHE-RSA-AES128-GCM-SHA256",
            ]

        elif self.config.security_level == SecurityLevel.HIGH:
            # High security, may reduce compatibility
            return [
                "ECDHE-ECDSA-AES256-GCM-SHA384",
                "ECDHE-ECDSA-CHACHA20-POLY1305",
                "ECDHE-RSA-AES256-GCM-SHA384",
                "ECDHE-RSA-CHACHA20-POLY1305",
            ]

        else:  # PARANOID
            # Maximum security, minimal compatibility
            return [
                "ECDHE-ECDSA-AES256-GCM-SHA384",
                "ECDHE-ECDSA-CHACHA20-POLY1305",
            ]

    def validate_host(self, host: str) -> bool:
        """Validate if host is allowed by security policy.

        Args:
            host: Hostname to validate

        Returns:
            True if host is allowed, False otherwise
        """
        if self.config.blocked_hosts and host in self.config.blocked_hosts:
            logger.warning("Host blocked by security policy", host=host)
            return False

        if self.config.allowed_hosts and host not in self.config.allowed_hosts:
            logger.warning("Host not in allowed list", host=host)
            return False

        return True

    def validate_certificate_chain(self, cert_chain: List[Any]) -> bool:
        """Validate certificate chain against security policy.

        Args:
            cert_chain: Certificate chain to validate

        Returns:
            True if chain is valid, False otherwise
        """
        if len(cert_chain) > self.config.max_cert_chain_length:
            logger.warning(
                "Certificate chain too long",
                length=len(cert_chain),
                max_length=self.config.max_cert_chain_length,
            )
            return False

        return True

    def get_connection_timeout(self) -> float:
        """Get connection timeout from security configuration."""
        return self.config.connection_timeout

    def get_handshake_timeout(self) -> float:
        """Get handshake timeout from security configuration."""
        return self.config.handshake_timeout

    def requires_sni(self) -> bool:
        """Check if SNI is required by security policy."""
        return self.config.require_sni

    def requires_perfect_forward_secrecy(self) -> bool:
        """Check if perfect forward secrecy is required."""
        return self.config.require_perfect_forward_secrecy
