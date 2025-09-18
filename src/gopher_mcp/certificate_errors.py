"""Certificate validation error handling for Gemini protocol."""

import ssl
import time
from enum import Enum
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

import structlog

logger = structlog.get_logger(__name__)


class CertificateErrorType(Enum):
    """Types of certificate validation errors."""

    # TLS handshake errors
    TLS_HANDSHAKE_FAILED = "tls_handshake_failed"
    TLS_VERSION_NOT_SUPPORTED = "tls_version_not_supported"
    TLS_CIPHER_NOT_SUPPORTED = "tls_cipher_not_supported"
    TLS_SNI_FAILED = "tls_sni_failed"
    TLS_CONNECTION_TIMEOUT = "tls_connection_timeout"

    # Certificate validation errors
    CERTIFICATE_EXPIRED = "certificate_expired"
    CERTIFICATE_NOT_YET_VALID = "certificate_not_yet_valid"
    CERTIFICATE_REVOKED = "certificate_revoked"
    CERTIFICATE_INVALID_SIGNATURE = "certificate_invalid_signature"
    CERTIFICATE_UNTRUSTED_ROOT = "certificate_untrusted_root"
    CERTIFICATE_HOSTNAME_MISMATCH = "certificate_hostname_mismatch"
    CERTIFICATE_CHAIN_INVALID = "certificate_chain_invalid"

    # TOFU-specific errors
    TOFU_CERTIFICATE_CHANGED = "tofu_certificate_changed"
    TOFU_FINGERPRINT_MISMATCH = "tofu_fingerprint_mismatch"
    TOFU_STORAGE_ERROR = "tofu_storage_error"
    TOFU_VALIDATION_FAILED = "tofu_validation_failed"

    # Client certificate errors
    CLIENT_CERT_NOT_FOUND = "client_cert_not_found"
    CLIENT_CERT_EXPIRED = "client_cert_expired"
    CLIENT_CERT_INVALID = "client_cert_invalid"
    CLIENT_CERT_KEY_MISMATCH = "client_cert_key_mismatch"
    CLIENT_CERT_REJECTED = "client_cert_rejected"

    # General errors
    CERTIFICATE_PARSE_ERROR = "certificate_parse_error"
    CERTIFICATE_ENCODING_ERROR = "certificate_encoding_error"
    UNKNOWN_CERTIFICATE_ERROR = "unknown_certificate_error"


class CertificateErrorSeverity(Enum):
    """Severity levels for certificate errors."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


@dataclass
class CertificateError:
    """Represents a certificate validation error."""

    error_type: CertificateErrorType
    message: str
    severity: CertificateErrorSeverity
    host: str
    port: int
    details: Dict[str, Any]
    timestamp: float
    recoverable: bool = False
    recovery_suggestions: Optional[List[str]] = None

    def __post_init__(self) -> None:
        """Initialize recovery suggestions if not provided."""
        if self.recovery_suggestions is None:
            self.recovery_suggestions = []


class CertificateErrorHandler:
    """Handles certificate validation errors and provides recovery suggestions."""

    def __init__(self) -> None:
        """Initialize error handler."""
        self._error_counts: Dict[str, int] = {}
        self._last_errors: Dict[str, CertificateError] = {}

    def handle_ssl_error(
        self,
        error: ssl.SSLError,
        host: str,
        port: int,
        context: Optional[Dict[str, Any]] = None,
    ) -> CertificateError:
        """Handle SSL/TLS errors and convert to CertificateError.

        Args:
            error: SSL error from Python ssl module
            host: Target hostname
            port: Target port
            context: Additional context information

        Returns:
            CertificateError with appropriate type and recovery suggestions
        """
        context = context or {}
        error_str = str(error).lower()

        # Determine error type based on SSL error
        if "certificate verify failed" in error_str:
            if "certificate has expired" in error_str:
                error_type = CertificateErrorType.CERTIFICATE_EXPIRED
                severity = CertificateErrorSeverity.HIGH
                recoverable = True
                suggestions = [
                    "Check if the server certificate has expired",
                    "Contact the server administrator",
                    "Verify system clock is correct",
                    "Consider using TOFU mode if appropriate",
                ]
            elif "hostname" in error_str or "name" in error_str:
                error_type = CertificateErrorType.CERTIFICATE_HOSTNAME_MISMATCH
                severity = CertificateErrorSeverity.HIGH
                recoverable = True
                suggestions = [
                    f"Verify you're connecting to the correct hostname: {host}",
                    "Check for typos in the hostname",
                    "Verify DNS resolution is correct",
                    "Check if the server uses a different certificate name",
                ]
            elif "self signed" in error_str or "untrusted" in error_str:
                error_type = CertificateErrorType.CERTIFICATE_UNTRUSTED_ROOT
                severity = CertificateErrorSeverity.MEDIUM
                recoverable = True
                suggestions = [
                    "This is common in Gemini - consider using TOFU validation",
                    "Verify the certificate fingerprint manually",
                    "Check if this is the expected self-signed certificate",
                    "Contact the server administrator for certificate details",
                ]
            else:
                error_type = CertificateErrorType.CERTIFICATE_INVALID_SIGNATURE
                severity = CertificateErrorSeverity.HIGH
                recoverable = False
                suggestions = [
                    "Certificate signature validation failed",
                    "This may indicate a security issue",
                    "Do not proceed without verification",
                    "Contact the server administrator",
                ]

        elif "timeout" in error_str or "timed out" in error_str:
            error_type = CertificateErrorType.TLS_CONNECTION_TIMEOUT
            severity = CertificateErrorSeverity.MEDIUM
            recoverable = True
            suggestions = [
                "Connection timed out during TLS handshake",
                "Check network connectivity",
                "Try increasing connection timeout",
                "Verify the server is responding",
            ]

        elif "handshake failure" in error_str or "handshake" in error_str:
            error_type = CertificateErrorType.TLS_HANDSHAKE_FAILED
            severity = CertificateErrorSeverity.HIGH
            recoverable = True
            suggestions = [
                "TLS handshake failed - check TLS version compatibility",
                "Verify cipher suite compatibility",
                "Check if client certificate is required",
                "Try with different TLS configuration",
            ]

        elif "protocol" in error_str or "version" in error_str:
            error_type = CertificateErrorType.TLS_VERSION_NOT_SUPPORTED
            severity = CertificateErrorSeverity.HIGH
            recoverable = True
            suggestions = [
                "TLS version not supported by server",
                "Try with TLS 1.2 or 1.3",
                "Check server TLS configuration",
                "Update TLS client configuration",
            ]

        else:
            error_type = CertificateErrorType.UNKNOWN_CERTIFICATE_ERROR
            severity = CertificateErrorSeverity.MEDIUM
            recoverable = False
            suggestions = [
                "Unknown SSL/TLS error occurred",
                "Check server logs for more details",
                "Verify network connectivity",
                "Contact support if issue persists",
            ]

        cert_error = CertificateError(
            error_type=error_type,
            message=f"SSL/TLS error: {str(error)}",
            severity=severity,
            host=host,
            port=port,
            details={
                "ssl_error": str(error),
                "ssl_error_type": type(error).__name__,
                "context": context,
            },
            timestamp=time.time(),
            recoverable=recoverable,
            recovery_suggestions=suggestions,
        )

        self._record_error(cert_error)
        return cert_error

    def handle_tofu_error(
        self,
        error_type: CertificateErrorType,
        message: str,
        host: str,
        port: int,
        details: Optional[Dict[str, Any]] = None,
    ) -> CertificateError:
        """Handle TOFU-specific errors.

        Args:
            error_type: Type of TOFU error
            message: Error message
            host: Target hostname
            port: Target port
            details: Additional error details

        Returns:
            CertificateError with TOFU-specific recovery suggestions
        """
        details = details or {}

        if error_type == CertificateErrorType.TOFU_CERTIFICATE_CHANGED:
            severity = CertificateErrorSeverity.CRITICAL
            recoverable = True
            suggestions = [
                "Certificate has changed since first connection",
                "This could indicate a security issue or server update",
                "Verify the change is legitimate with the server administrator",
                "Check the new certificate fingerprint manually",
                "Only accept if you trust the new certificate",
            ]

        elif error_type == CertificateErrorType.TOFU_FINGERPRINT_MISMATCH:
            severity = CertificateErrorSeverity.HIGH
            recoverable = True
            suggestions = [
                "Certificate fingerprint does not match stored value",
                "Verify the certificate fingerprint manually",
                "Check if the server certificate was updated",
                "Contact the server administrator for verification",
            ]

        elif error_type == CertificateErrorType.TOFU_STORAGE_ERROR:
            severity = CertificateErrorSeverity.MEDIUM
            recoverable = True
            suggestions = [
                "Error accessing TOFU certificate storage",
                "Check file permissions for certificate store",
                "Verify disk space availability",
                "Check certificate store path configuration",
            ]

        else:
            severity = CertificateErrorSeverity.MEDIUM
            recoverable = True
            suggestions = [
                "TOFU validation failed",
                "Check TOFU configuration",
                "Verify certificate storage is accessible",
                "Try clearing TOFU cache if appropriate",
            ]

        cert_error = CertificateError(
            error_type=error_type,
            message=message,
            severity=severity,
            host=host,
            port=port,
            details=details,
            timestamp=time.time(),
            recoverable=recoverable,
            recovery_suggestions=suggestions,
        )

        self._record_error(cert_error)
        return cert_error

    def handle_client_certificate_error(
        self,
        error_type: CertificateErrorType,
        message: str,
        host: str,
        port: int,
        cert_path: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> CertificateError:
        """Handle client certificate errors.

        Args:
            error_type: Type of client certificate error
            message: Error message
            host: Target hostname
            port: Target port
            cert_path: Path to client certificate
            details: Additional error details

        Returns:
            CertificateError with client certificate recovery suggestions
        """
        details = details or {}
        if cert_path:
            details["cert_path"] = cert_path

        if error_type == CertificateErrorType.CLIENT_CERT_NOT_FOUND:
            severity = CertificateErrorSeverity.MEDIUM
            recoverable = True
            suggestions = [
                "Client certificate not found",
                "Check certificate file path",
                "Generate a new client certificate if needed",
                "Verify certificate file permissions",
            ]

        elif error_type == CertificateErrorType.CLIENT_CERT_EXPIRED:
            severity = CertificateErrorSeverity.MEDIUM
            recoverable = True
            suggestions = [
                "Client certificate has expired",
                "Generate a new client certificate",
                "Check certificate validity period",
                "Update certificate before expiry",
            ]

        elif error_type == CertificateErrorType.CLIENT_CERT_REJECTED:
            severity = CertificateErrorSeverity.HIGH
            recoverable = True
            suggestions = [
                "Server rejected the client certificate",
                "Verify certificate is valid for this server",
                "Check certificate scope and permissions",
                "Contact server administrator for certificate requirements",
            ]

        else:
            severity = CertificateErrorSeverity.MEDIUM
            recoverable = True
            suggestions = [
                "Client certificate error",
                "Check certificate file format",
                "Verify certificate and key match",
                "Generate a new certificate if needed",
            ]

        cert_error = CertificateError(
            error_type=error_type,
            message=message,
            severity=severity,
            host=host,
            port=port,
            details=details,
            timestamp=time.time(),
            recoverable=recoverable,
            recovery_suggestions=suggestions,
        )

        self._record_error(cert_error)
        return cert_error

    def handle_certificate_expiry(
        self,
        host: str,
        port: int,
        not_before: str,
        not_after: str,
        current_time: Optional[float] = None,
    ) -> CertificateError:
        """Handle certificate expiry errors.

        Args:
            host: Target hostname
            port: Target port
            not_before: Certificate validity start
            not_after: Certificate validity end
            current_time: Current timestamp (defaults to now)

        Returns:
            CertificateError for expiry issue
        """
        current_time = current_time or time.time()

        try:
            # Parse certificate dates (assuming ISO format or timestamp)
            if not_before.isdigit():
                not_before_ts = float(not_before)
            else:
                # Try to parse as timestamp, if that fails, raise error
                raise ValueError(f"Invalid date format: {not_before}")

            if not_after.isdigit():
                not_after_ts = float(not_after)
                # Check if certificate has expired
                if current_time > not_after_ts:
                    # Certificate has expired - create error immediately
                    cert_error = CertificateError(
                        error_type=CertificateErrorType.CERTIFICATE_EXPIRED,
                        message=f"Certificate expired (expired on {not_after})",
                        severity=CertificateErrorSeverity.HIGH,
                        host=host,
                        port=port,
                        details={
                            "not_before": not_before,
                            "not_after": not_after,
                            "current_time": current_time,
                        },
                        timestamp=time.time(),
                        recoverable=True,
                        recovery_suggestions=[
                            "Certificate has expired",
                            "Contact server administrator for certificate renewal",
                            "Check if server has updated certificate",
                            "Verify system clock is correct",
                        ],
                    )
                    self._record_error(cert_error)
                    return cert_error
            else:
                # Try to parse as timestamp, if that fails, raise error
                raise ValueError(f"Invalid date format: {not_after}")

            if current_time < not_before_ts:
                error_type = CertificateErrorType.CERTIFICATE_NOT_YET_VALID
                message = f"Certificate not yet valid (valid from {not_before})"
                suggestions = [
                    "Certificate is not yet valid",
                    "Check system clock is correct",
                    "Wait until certificate becomes valid",
                    "Contact server administrator if clock is correct",
                ]
            else:
                error_type = CertificateErrorType.CERTIFICATE_EXPIRED
                message = f"Certificate expired (expired on {not_after})"
                suggestions = [
                    "Certificate has expired",
                    "Contact server administrator for certificate renewal",
                    "Check if server has updated certificate",
                    "Verify system clock is correct",
                ]

        except (ValueError, TypeError):
            error_type = CertificateErrorType.CERTIFICATE_PARSE_ERROR
            message = "Could not parse certificate validity dates"
            suggestions = [
                "Certificate date parsing failed",
                "Certificate may be malformed",
                "Contact server administrator",
                "Check certificate format",
            ]

        cert_error = CertificateError(
            error_type=error_type,
            message=message,
            severity=CertificateErrorSeverity.HIGH,
            host=host,
            port=port,
            details={
                "not_before": not_before,
                "not_after": not_after,
                "current_time": current_time,
            },
            timestamp=time.time(),
            recoverable=True,
            recovery_suggestions=suggestions,
        )

        self._record_error(cert_error)
        return cert_error

    def _record_error(self, error: CertificateError) -> None:
        """Record error for tracking and analysis.

        Args:
            error: Certificate error to record
        """
        host_key = f"{error.host}:{error.port}"

        # Update error count
        self._error_counts[host_key] = self._error_counts.get(host_key, 0) + 1

        # Store last error
        self._last_errors[host_key] = error

        # Log error
        logger.error(
            "Certificate validation error",
            error_type=error.error_type.value,
            severity=error.severity.value,
            host=error.host,
            port=error.port,
            message=error.message,
            recoverable=error.recoverable,
            error_count=self._error_counts[host_key],
        )

    def get_error_statistics(self) -> Dict[str, Any]:
        """Get error statistics for monitoring.

        Returns:
            Dictionary with error statistics
        """
        total_errors = sum(self._error_counts.values())
        error_types: Dict[str, int] = {}

        for error in self._last_errors.values():
            error_type = error.error_type.value
            error_types[error_type] = error_types.get(error_type, 0) + 1

        return {
            "total_errors": total_errors,
            "unique_hosts": len(self._error_counts),
            "error_types": error_types,
            "hosts_with_errors": list(self._error_counts.keys()),
        }

    def get_last_error(self, host: str, port: int) -> Optional[CertificateError]:
        """Get the last error for a specific host.

        Args:
            host: Target hostname
            port: Target port

        Returns:
            Last CertificateError for the host or None
        """
        host_key = f"{host}:{port}"
        return self._last_errors.get(host_key)

    def clear_errors(
        self, host: Optional[str] = None, port: Optional[int] = None
    ) -> None:
        """Clear error records.

        Args:
            host: Specific host to clear (clears all if None)
            port: Specific port to clear (clears all if None)
        """
        if host and port:
            host_key = f"{host}:{port}"
            self._error_counts.pop(host_key, None)
            self._last_errors.pop(host_key, None)
        else:
            self._error_counts.clear()
            self._last_errors.clear()


# Global error handler instance
certificate_error_handler = CertificateErrorHandler()
