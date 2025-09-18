"""Tests for certificate_errors module."""

import ssl
from unittest.mock import patch


from gopher_mcp.certificate_errors import (
    CertificateErrorType,
    CertificateErrorSeverity,
    CertificateError,
    CertificateErrorHandler,
    certificate_error_handler,
)


class TestCertificateErrorType:
    """Test CertificateErrorType enum."""

    def test_tls_handshake_errors(self):
        """Test TLS handshake error types."""
        assert CertificateErrorType.TLS_HANDSHAKE_FAILED.value == "tls_handshake_failed"
        assert (
            CertificateErrorType.TLS_VERSION_NOT_SUPPORTED.value
            == "tls_version_not_supported"
        )
        assert (
            CertificateErrorType.TLS_CIPHER_NOT_SUPPORTED.value
            == "tls_cipher_not_supported"
        )
        assert CertificateErrorType.TLS_SNI_FAILED.value == "tls_sni_failed"
        assert (
            CertificateErrorType.TLS_CONNECTION_TIMEOUT.value
            == "tls_connection_timeout"
        )

    def test_certificate_validation_errors(self):
        """Test certificate validation error types."""
        assert CertificateErrorType.CERTIFICATE_EXPIRED.value == "certificate_expired"
        assert (
            CertificateErrorType.CERTIFICATE_NOT_YET_VALID.value
            == "certificate_not_yet_valid"
        )
        assert CertificateErrorType.CERTIFICATE_REVOKED.value == "certificate_revoked"
        assert (
            CertificateErrorType.CERTIFICATE_INVALID_SIGNATURE.value
            == "certificate_invalid_signature"
        )
        assert (
            CertificateErrorType.CERTIFICATE_UNTRUSTED_ROOT.value
            == "certificate_untrusted_root"
        )
        assert (
            CertificateErrorType.CERTIFICATE_HOSTNAME_MISMATCH.value
            == "certificate_hostname_mismatch"
        )
        assert (
            CertificateErrorType.CERTIFICATE_CHAIN_INVALID.value
            == "certificate_chain_invalid"
        )

    def test_tofu_errors(self):
        """Test TOFU-specific error types."""
        assert (
            CertificateErrorType.TOFU_CERTIFICATE_CHANGED.value
            == "tofu_certificate_changed"
        )
        assert (
            CertificateErrorType.TOFU_FINGERPRINT_MISMATCH.value
            == "tofu_fingerprint_mismatch"
        )
        assert CertificateErrorType.TOFU_STORAGE_ERROR.value == "tofu_storage_error"
        assert (
            CertificateErrorType.TOFU_VALIDATION_FAILED.value
            == "tofu_validation_failed"
        )

    def test_client_certificate_errors(self):
        """Test client certificate error types."""
        assert (
            CertificateErrorType.CLIENT_CERT_NOT_FOUND.value == "client_cert_not_found"
        )
        assert CertificateErrorType.CLIENT_CERT_EXPIRED.value == "client_cert_expired"
        assert CertificateErrorType.CLIENT_CERT_INVALID.value == "client_cert_invalid"
        assert (
            CertificateErrorType.CLIENT_CERT_KEY_MISMATCH.value
            == "client_cert_key_mismatch"
        )
        assert CertificateErrorType.CLIENT_CERT_REJECTED.value == "client_cert_rejected"

    def test_general_errors(self):
        """Test general error types."""
        assert (
            CertificateErrorType.CERTIFICATE_PARSE_ERROR.value
            == "certificate_parse_error"
        )
        assert (
            CertificateErrorType.CERTIFICATE_ENCODING_ERROR.value
            == "certificate_encoding_error"
        )
        assert (
            CertificateErrorType.UNKNOWN_CERTIFICATE_ERROR.value
            == "unknown_certificate_error"
        )


class TestCertificateErrorSeverity:
    """Test CertificateErrorSeverity enum."""

    def test_severity_levels(self):
        """Test severity level values."""
        assert CertificateErrorSeverity.LOW.value == "low"
        assert CertificateErrorSeverity.MEDIUM.value == "medium"
        assert CertificateErrorSeverity.HIGH.value == "high"
        assert CertificateErrorSeverity.CRITICAL.value == "critical"


class TestCertificateError:
    """Test CertificateError dataclass."""

    def test_basic_certificate_error(self):
        """Test basic certificate error creation."""
        error = CertificateError(
            error_type=CertificateErrorType.CERTIFICATE_EXPIRED,
            message="Certificate has expired",
            severity=CertificateErrorSeverity.HIGH,
            host="example.com",
            port=1965,
            details={"test": "data"},
            timestamp=1234567890.0,
            recoverable=True,
        )

        assert error.error_type == CertificateErrorType.CERTIFICATE_EXPIRED
        assert error.message == "Certificate has expired"
        assert error.severity == CertificateErrorSeverity.HIGH
        assert error.host == "example.com"
        assert error.port == 1965
        assert error.details == {"test": "data"}
        assert error.timestamp == 1234567890.0
        assert error.recoverable is True
        assert error.recovery_suggestions == []

    def test_certificate_error_with_suggestions(self):
        """Test certificate error with recovery suggestions."""
        suggestions = ["Check certificate", "Contact admin"]
        error = CertificateError(
            error_type=CertificateErrorType.CERTIFICATE_EXPIRED,
            message="Certificate has expired",
            severity=CertificateErrorSeverity.HIGH,
            host="example.com",
            port=1965,
            details={},
            timestamp=1234567890.0,
            recovery_suggestions=suggestions,
        )

        assert error.recovery_suggestions == suggestions

    def test_certificate_error_post_init(self):
        """Test certificate error post-init behavior."""
        error = CertificateError(
            error_type=CertificateErrorType.CERTIFICATE_EXPIRED,
            message="Certificate has expired",
            severity=CertificateErrorSeverity.HIGH,
            host="example.com",
            port=1965,
            details={},
            timestamp=1234567890.0,
        )

        # Should initialize empty recovery_suggestions list
        assert error.recovery_suggestions == []


class TestCertificateErrorHandler:
    """Test CertificateErrorHandler class."""

    def test_handler_initialization(self):
        """Test error handler initialization."""
        handler = CertificateErrorHandler()
        assert handler._error_counts == {}
        assert handler._last_errors == {}

    def test_handle_ssl_error_certificate_expired(self):
        """Test handling SSL error for expired certificate."""
        handler = CertificateErrorHandler()
        ssl_error = ssl.SSLError("certificate verify failed: certificate has expired")

        with patch("time.time", return_value=1234567890.0):
            error = handler.handle_ssl_error(ssl_error, "example.com", 1965)

        assert error.error_type == CertificateErrorType.CERTIFICATE_EXPIRED
        assert error.severity == CertificateErrorSeverity.HIGH
        assert error.host == "example.com"
        assert error.port == 1965
        assert error.recoverable is True
        assert (
            "Check if the server certificate has expired" in error.recovery_suggestions
        )
        assert error.timestamp == 1234567890.0

    def test_handle_ssl_error_hostname_mismatch(self):
        """Test handling SSL error for hostname mismatch."""
        handler = CertificateErrorHandler()
        ssl_error = ssl.SSLError(
            "certificate verify failed: hostname 'example.com' doesn't match"
        )

        error = handler.handle_ssl_error(ssl_error, "example.com", 1965)

        assert error.error_type == CertificateErrorType.CERTIFICATE_HOSTNAME_MISMATCH
        assert error.severity == CertificateErrorSeverity.HIGH
        assert error.recoverable is True
        assert (
            "Verify you're connecting to the correct hostname: example.com"
            in error.recovery_suggestions
        )

    def test_handle_ssl_error_untrusted_root(self):
        """Test handling SSL error for untrusted root."""
        handler = CertificateErrorHandler()
        ssl_error = ssl.SSLError("certificate verify failed: self signed certificate")

        error = handler.handle_ssl_error(ssl_error, "example.com", 1965)

        assert error.error_type == CertificateErrorType.CERTIFICATE_UNTRUSTED_ROOT
        assert error.severity == CertificateErrorSeverity.MEDIUM
        assert error.recoverable is True
        assert (
            "This is common in Gemini - consider using TOFU validation"
            in error.recovery_suggestions
        )

    def test_handle_ssl_error_handshake_failed(self):
        """Test handling SSL error for handshake failure."""
        handler = CertificateErrorHandler()
        ssl_error = ssl.SSLError("handshake failure")

        error = handler.handle_ssl_error(ssl_error, "example.com", 1965)

        assert error.error_type == CertificateErrorType.TLS_HANDSHAKE_FAILED
        assert error.severity == CertificateErrorSeverity.HIGH
        assert error.recoverable is True
        assert (
            "TLS handshake failed - check TLS version compatibility"
            in error.recovery_suggestions
        )

    def test_handle_ssl_error_timeout(self):
        """Test handling SSL error for timeout."""
        handler = CertificateErrorHandler()
        ssl_error = ssl.SSLError("The handshake operation timed out")

        error = handler.handle_ssl_error(ssl_error, "example.com", 1965)

        assert error.error_type == CertificateErrorType.TLS_CONNECTION_TIMEOUT
        assert error.severity == CertificateErrorSeverity.MEDIUM
        assert error.recoverable is True
        assert "Connection timed out during TLS handshake" in error.recovery_suggestions

    def test_handle_ssl_error_protocol_version(self):
        """Test handling SSL error for protocol version."""
        handler = CertificateErrorHandler()
        ssl_error = ssl.SSLError("unsupported protocol version")

        error = handler.handle_ssl_error(ssl_error, "example.com", 1965)

        assert error.error_type == CertificateErrorType.TLS_VERSION_NOT_SUPPORTED
        assert error.severity == CertificateErrorSeverity.HIGH
        assert error.recoverable is True
        assert "TLS version not supported by server" in error.recovery_suggestions

    def test_handle_ssl_error_unknown(self):
        """Test handling unknown SSL error."""
        handler = CertificateErrorHandler()
        ssl_error = ssl.SSLError("some unknown error")

        error = handler.handle_ssl_error(ssl_error, "example.com", 1965)

        assert error.error_type == CertificateErrorType.UNKNOWN_CERTIFICATE_ERROR
        assert error.severity == CertificateErrorSeverity.MEDIUM
        assert error.recoverable is False
        assert "Unknown SSL/TLS error occurred" in error.recovery_suggestions

    def test_handle_ssl_error_with_context(self):
        """Test handling SSL error with additional context."""
        handler = CertificateErrorHandler()
        ssl_error = ssl.SSLError("certificate verify failed")
        context = {"client_version": "1.0", "server_info": "test"}

        error = handler.handle_ssl_error(ssl_error, "example.com", 1965, context)

        assert error.details["context"] == context
        assert error.details["ssl_error"] == str(ssl_error)
        assert error.details["ssl_error_type"] == "SSLError"

    def test_handle_tofu_error_certificate_changed(self):
        """Test handling TOFU certificate changed error."""
        handler = CertificateErrorHandler()

        with patch("time.time", return_value=1234567890.0):
            error = handler.handle_tofu_error(
                CertificateErrorType.TOFU_CERTIFICATE_CHANGED,
                "Certificate has changed",
                "example.com",
                1965,
                {"old_fingerprint": "abc123", "new_fingerprint": "def456"},
            )

        assert error.error_type == CertificateErrorType.TOFU_CERTIFICATE_CHANGED
        assert error.severity == CertificateErrorSeverity.CRITICAL
        assert error.recoverable is True
        assert (
            "Certificate has changed since first connection"
            in error.recovery_suggestions
        )
        assert error.details["old_fingerprint"] == "abc123"

    def test_handle_tofu_error_fingerprint_mismatch(self):
        """Test handling TOFU fingerprint mismatch error."""
        handler = CertificateErrorHandler()

        error = handler.handle_tofu_error(
            CertificateErrorType.TOFU_FINGERPRINT_MISMATCH,
            "Fingerprint mismatch",
            "example.com",
            1965,
        )

        assert error.error_type == CertificateErrorType.TOFU_FINGERPRINT_MISMATCH
        assert error.severity == CertificateErrorSeverity.HIGH
        assert error.recoverable is True
        assert (
            "Certificate fingerprint does not match stored value"
            in error.recovery_suggestions
        )

    def test_handle_tofu_error_storage_error(self):
        """Test handling TOFU storage error."""
        handler = CertificateErrorHandler()

        error = handler.handle_tofu_error(
            CertificateErrorType.TOFU_STORAGE_ERROR,
            "Storage error",
            "example.com",
            1965,
        )

        assert error.error_type == CertificateErrorType.TOFU_STORAGE_ERROR
        assert error.severity == CertificateErrorSeverity.MEDIUM
        assert error.recoverable is True
        assert "Error accessing TOFU certificate storage" in error.recovery_suggestions

    def test_handle_tofu_error_validation_failed(self):
        """Test handling TOFU validation failed error."""
        handler = CertificateErrorHandler()

        error = handler.handle_tofu_error(
            CertificateErrorType.TOFU_VALIDATION_FAILED,
            "Validation failed",
            "example.com",
            1965,
        )

        assert error.error_type == CertificateErrorType.TOFU_VALIDATION_FAILED
        assert error.severity == CertificateErrorSeverity.MEDIUM
        assert error.recoverable is True
        assert "TOFU validation failed" in error.recovery_suggestions

    def test_handle_client_certificate_error_not_found(self):
        """Test handling client certificate not found error."""
        handler = CertificateErrorHandler()

        error = handler.handle_client_certificate_error(
            CertificateErrorType.CLIENT_CERT_NOT_FOUND,
            "Certificate not found",
            "example.com",
            1965,
            "/path/to/cert.pem",
        )

        assert error.error_type == CertificateErrorType.CLIENT_CERT_NOT_FOUND
        assert error.severity == CertificateErrorSeverity.MEDIUM
        assert error.recoverable is True
        assert "Client certificate not found" in error.recovery_suggestions
        assert error.details["cert_path"] == "/path/to/cert.pem"

    def test_handle_client_certificate_error_expired(self):
        """Test handling client certificate expired error."""
        handler = CertificateErrorHandler()

        error = handler.handle_client_certificate_error(
            CertificateErrorType.CLIENT_CERT_EXPIRED,
            "Certificate expired",
            "example.com",
            1965,
        )

        assert error.error_type == CertificateErrorType.CLIENT_CERT_EXPIRED
        assert error.severity == CertificateErrorSeverity.MEDIUM
        assert error.recoverable is True
        assert "Client certificate has expired" in error.recovery_suggestions

    def test_handle_client_certificate_error_rejected(self):
        """Test handling client certificate rejected error."""
        handler = CertificateErrorHandler()

        error = handler.handle_client_certificate_error(
            CertificateErrorType.CLIENT_CERT_REJECTED,
            "Certificate rejected",
            "example.com",
            1965,
        )

        assert error.error_type == CertificateErrorType.CLIENT_CERT_REJECTED
        assert error.severity == CertificateErrorSeverity.HIGH
        assert error.recoverable is True
        assert "Server rejected the client certificate" in error.recovery_suggestions

    def test_handle_client_certificate_error_generic(self):
        """Test handling generic client certificate error."""
        handler = CertificateErrorHandler()

        error = handler.handle_client_certificate_error(
            CertificateErrorType.CLIENT_CERT_INVALID,
            "Certificate invalid",
            "example.com",
            1965,
        )

        assert error.error_type == CertificateErrorType.CLIENT_CERT_INVALID
        assert error.severity == CertificateErrorSeverity.MEDIUM
        assert error.recoverable is True
        assert "Client certificate error" in error.recovery_suggestions

    def test_handle_certificate_expiry_expired(self):
        """Test handling certificate expiry for expired certificate."""
        handler = CertificateErrorHandler()
        current_time = 1234567890.0
        not_before = "1234567800"  # Before current time
        not_after = "1234567880"  # Before current time (expired)

        with patch("time.time", return_value=current_time):
            error = handler.handle_certificate_expiry(
                "example.com", 1965, not_before, not_after, current_time
            )

        assert error.error_type == CertificateErrorType.CERTIFICATE_EXPIRED
        assert error.severity == CertificateErrorSeverity.HIGH
        assert error.recoverable is True
        assert "Certificate has expired" in error.recovery_suggestions

    def test_handle_certificate_expiry_not_yet_valid(self):
        """Test handling certificate expiry for not yet valid certificate."""
        handler = CertificateErrorHandler()
        current_time = 1234567890.0
        not_before = "1234567900"  # After current time (not yet valid)
        not_after = "1234567950"  # After current time

        with patch("time.time", return_value=current_time):
            error = handler.handle_certificate_expiry(
                "example.com", 1965, not_before, not_after, current_time
            )

        assert error.error_type == CertificateErrorType.CERTIFICATE_NOT_YET_VALID
        assert error.severity == CertificateErrorSeverity.HIGH
        assert error.recoverable is True
        assert "Certificate is not yet valid" in error.recovery_suggestions

    def test_handle_certificate_expiry_parse_error(self):
        """Test handling certificate expiry with invalid date format."""
        handler = CertificateErrorHandler()

        with patch("time.time", return_value=1234567890.0):
            error = handler.handle_certificate_expiry(
                "example.com", 1965, "invalid_date", "also_invalid"
            )

        assert error.error_type == CertificateErrorType.CERTIFICATE_PARSE_ERROR
        assert error.severity == CertificateErrorSeverity.HIGH
        assert error.recoverable is True
        assert "Certificate date parsing failed" in error.recovery_suggestions

    def test_record_error(self):
        """Test error recording functionality."""
        handler = CertificateErrorHandler()

        error = CertificateError(
            error_type=CertificateErrorType.CERTIFICATE_EXPIRED,
            message="Test error",
            severity=CertificateErrorSeverity.HIGH,
            host="example.com",
            port=1965,
            details={},
            timestamp=1234567890.0,
        )

        # Record the error
        handler._record_error(error)

        # Check error was recorded
        assert "example.com:1965" in handler._error_counts
        assert handler._error_counts["example.com:1965"] == 1
        assert handler._last_errors["example.com:1965"] == error

        # Record another error for same host
        error2 = CertificateError(
            error_type=CertificateErrorType.CERTIFICATE_HOSTNAME_MISMATCH,
            message="Another error",
            severity=CertificateErrorSeverity.MEDIUM,
            host="example.com",
            port=1965,
            details={},
            timestamp=1234567891.0,
        )
        handler._record_error(error2)

        # Check count increased and last error updated
        assert handler._error_counts["example.com:1965"] == 2
        assert handler._last_errors["example.com:1965"] == error2

    def test_get_error_statistics(self):
        """Test error statistics generation."""
        handler = CertificateErrorHandler()

        # Add some errors
        error1 = CertificateError(
            error_type=CertificateErrorType.CERTIFICATE_EXPIRED,
            message="Error 1",
            severity=CertificateErrorSeverity.HIGH,
            host="example.com",
            port=1965,
            details={},
            timestamp=1234567890.0,
        )
        error2 = CertificateError(
            error_type=CertificateErrorType.CERTIFICATE_HOSTNAME_MISMATCH,
            message="Error 2",
            severity=CertificateErrorSeverity.MEDIUM,
            host="test.com",
            port=1965,
            details={},
            timestamp=1234567891.0,
        )

        handler._record_error(error1)
        handler._record_error(error2)

        stats = handler.get_error_statistics()

        assert stats["total_errors"] == 2
        assert stats["unique_hosts"] == 2
        assert "certificate_expired" in stats["error_types"]
        assert "certificate_hostname_mismatch" in stats["error_types"]
        assert "example.com:1965" in stats["hosts_with_errors"]
        assert "test.com:1965" in stats["hosts_with_errors"]

    def test_get_last_error(self):
        """Test getting last error for a host."""
        handler = CertificateErrorHandler()

        # No error initially
        assert handler.get_last_error("example.com", 1965) is None

        # Add an error
        error = CertificateError(
            error_type=CertificateErrorType.CERTIFICATE_EXPIRED,
            message="Test error",
            severity=CertificateErrorSeverity.HIGH,
            host="example.com",
            port=1965,
            details={},
            timestamp=1234567890.0,
        )
        handler._record_error(error)

        # Should return the error
        last_error = handler.get_last_error("example.com", 1965)
        assert last_error == error

        # Different host should return None
        assert handler.get_last_error("other.com", 1965) is None

    def test_clear_errors_specific_host(self):
        """Test clearing errors for specific host."""
        handler = CertificateErrorHandler()

        # Add errors for multiple hosts
        error1 = CertificateError(
            error_type=CertificateErrorType.CERTIFICATE_EXPIRED,
            message="Error 1",
            severity=CertificateErrorSeverity.HIGH,
            host="example.com",
            port=1965,
            details={},
            timestamp=1234567890.0,
        )
        error2 = CertificateError(
            error_type=CertificateErrorType.CERTIFICATE_HOSTNAME_MISMATCH,
            message="Error 2",
            severity=CertificateErrorSeverity.MEDIUM,
            host="test.com",
            port=1965,
            details={},
            timestamp=1234567891.0,
        )

        handler._record_error(error1)
        handler._record_error(error2)

        # Clear errors for specific host
        handler.clear_errors("example.com", 1965)

        # Should only clear that host
        assert "example.com:1965" not in handler._error_counts
        assert "example.com:1965" not in handler._last_errors
        assert "test.com:1965" in handler._error_counts
        assert "test.com:1965" in handler._last_errors

    def test_clear_errors_all(self):
        """Test clearing all errors."""
        handler = CertificateErrorHandler()

        # Add some errors
        error = CertificateError(
            error_type=CertificateErrorType.CERTIFICATE_EXPIRED,
            message="Test error",
            severity=CertificateErrorSeverity.HIGH,
            host="example.com",
            port=1965,
            details={},
            timestamp=1234567890.0,
        )
        handler._record_error(error)

        # Clear all errors
        handler.clear_errors()

        # Should clear everything
        assert handler._error_counts == {}
        assert handler._last_errors == {}


class TestGlobalErrorHandler:
    """Test global error handler instance."""

    def test_global_handler_exists(self):
        """Test that global error handler instance exists."""
        assert certificate_error_handler is not None
        assert isinstance(certificate_error_handler, CertificateErrorHandler)
