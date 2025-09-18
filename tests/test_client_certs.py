"""Tests for client_certs module."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from gopher_mcp.client_certs import (
    ClientCertificateError,
    ClientCertificateManager,
)
from gopher_mcp.models import GeminiCertificateInfo


class TestClientCertificateError:
    """Test ClientCertificateError exception."""

    def test_basic_exception(self):
        """Test basic exception creation."""
        error = ClientCertificateError("Test error")
        assert str(error) == "Test error"
        assert isinstance(error, Exception)


class TestClientCertificateManager:
    """Test ClientCertificateManager class."""

    def test_initialization_default_path(self):
        """Test manager initialization with default path."""
        with (
            patch("gopher_mcp.client_certs.get_home_directory") as mock_home,
            patch("pathlib.Path.mkdir") as mock_mkdir,
            patch.object(ClientCertificateManager, "_load_registry"),
        ):
            mock_home.return_value = Path("/home/user")

            manager = ClientCertificateManager()

            # Use os.path.normpath to handle platform differences
            expected_path = str(Path("/home/user/.gemini/certs"))
            assert str(manager.storage_path) == expected_path
            mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)

    def test_initialization_no_home_directory(self):
        """Test manager initialization when home directory cannot be determined."""
        with (
            patch("gopher_mcp.client_certs.get_home_directory") as mock_home,
            patch.object(ClientCertificateManager, "_load_registry"),
        ):
            mock_home.return_value = None

            with pytest.raises(
                ClientCertificateError, match="Could not determine home directory"
            ):
                ClientCertificateManager()

    def test_initialization_custom_path(self):
        """Test manager initialization with custom path."""
        with (
            patch("pathlib.Path.mkdir") as mock_mkdir,
            patch.object(ClientCertificateManager, "_load_registry"),
        ):
            custom_path = "/custom/cert/path"
            manager = ClientCertificateManager(custom_path)

            # Use Path to normalize the path for platform compatibility
            expected_path = str(Path(custom_path))
            assert str(manager.storage_path) == expected_path
            mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)

    def test_get_cert_key(self):
        """Test certificate key generation."""
        with patch.object(ClientCertificateManager, "_load_registry"):
            manager = ClientCertificateManager("/tmp/test")

            key = manager._get_cert_key("example.com", 1965, "/path")
            assert key == "example.com:1965/path"

    def test_load_registry_no_file(self):
        """Test loading registry when no file exists."""
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = ClientCertificateManager(temp_dir)

            # Should initialize with empty certificates dict
            assert manager._certificates == {}

    def test_load_registry_with_file(self):
        """Test loading registry from existing file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create a test registry file
            registry_path = Path(temp_dir) / "registry.json"
            test_data = {
                "example.com:1965/": {
                    "fingerprint": "sha256:abc123",
                    "subject": "CN=test",
                    "issuer": "CN=test",
                    "not_before": "2023-01-01T00:00:00",
                    "not_after": "2024-01-01T00:00:00",
                    "host": "example.com",
                    "port": 1965,
                    "path": "/",
                }
            }

            with open(registry_path, "w") as f:
                json.dump(test_data, f)

            manager = ClientCertificateManager(temp_dir)

            assert len(manager._certificates) == 1
            assert "example.com:1965/" in manager._certificates
            cert_info = manager._certificates["example.com:1965/"]
            assert cert_info.fingerprint == "sha256:abc123"
            assert cert_info.host == "example.com"

    def test_load_registry_invalid_json(self):
        """Test loading registry with invalid JSON."""
        with tempfile.TemporaryDirectory() as temp_dir:
            # Create an invalid registry file
            registry_path = Path(temp_dir) / "registry.json"
            with open(registry_path, "w") as f:
                f.write("invalid json")

            manager = ClientCertificateManager(temp_dir)

            # Should fall back to empty certificates dict
            assert manager._certificates == {}

    def test_save_registry(self):
        """Test saving registry to file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = ClientCertificateManager(temp_dir)

            # Add a test certificate
            cert_info = GeminiCertificateInfo(
                fingerprint="sha256:abc123",
                subject="CN=test",
                issuer="CN=test",
                not_before="2023-01-01T00:00:00",
                not_after="2024-01-01T00:00:00",
                host="example.com",
                port=1965,
                path="/",
            )
            manager._certificates["example.com:1965/"] = cert_info

            # Save registry
            manager._save_registry()

            # Verify file was created and contains correct data
            registry_path = Path(temp_dir) / "registry.json"
            assert registry_path.exists()

            with open(registry_path, "r") as f:
                data = json.load(f)

            assert "example.com:1965/" in data
            assert data["example.com:1965/"]["fingerprint"] == "sha256:abc123"

    def test_save_registry_error(self):
        """Test save registry error handling."""
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = ClientCertificateManager(temp_dir)

            # Mock atomic_write_json to raise an error
            with patch(
                "gopher_mcp.client_certs.atomic_write_json",
                side_effect=OSError("Permission denied"),
            ):
                with pytest.raises(Exception):
                    manager._save_registry()

    def test_generate_certificate_invalid_host(self):
        """Test certificate generation with invalid host."""
        with patch.object(ClientCertificateManager, "_load_registry"):
            manager = ClientCertificateManager("/tmp/test")

            with pytest.raises(ClientCertificateError, match="Host cannot be empty"):
                manager.generate_certificate("")

    def test_generate_certificate_invalid_port(self):
        """Test certificate generation with invalid port."""
        with patch.object(ClientCertificateManager, "_load_registry"):
            manager = ClientCertificateManager("/tmp/test")

            with pytest.raises(
                ClientCertificateError, match="Port must be between 1 and 65535"
            ):
                manager.generate_certificate("example.com", port=0)

            with pytest.raises(
                ClientCertificateError, match="Port must be between 1 and 65535"
            ):
                manager.generate_certificate("example.com", port=70000)

    def test_generate_certificate_invalid_path(self):
        """Test certificate generation with invalid path."""
        with patch.object(ClientCertificateManager, "_load_registry"):
            manager = ClientCertificateManager("/tmp/test")

            with pytest.raises(
                ClientCertificateError, match="Path must start with '/'"
            ):
                manager.generate_certificate("example.com", path="invalid")

    def test_generate_certificate_invalid_validity(self):
        """Test certificate generation with invalid validity."""
        with patch.object(ClientCertificateManager, "_load_registry"):
            manager = ClientCertificateManager("/tmp/test")

            with pytest.raises(
                ClientCertificateError, match="Validity days must be positive"
            ):
                manager.generate_certificate("example.com", validity_days=0)

    def test_generate_certificate_success(self):
        """Test successful certificate generation."""
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = ClientCertificateManager(temp_dir)

            with patch("time.time", return_value=1234567890):
                cert_path, key_path = manager.generate_certificate(
                    "example.com", port=1965, path="/test", validity_days=30
                )

            # Check that files were created
            assert Path(cert_path).exists()
            assert Path(key_path).exists()

            # Check that certificate was added to registry
            key = manager._get_cert_key("example.com", 1965, "/test")
            assert key in manager._certificates

            cert_info = manager._certificates[key]
            assert cert_info.host == "example.com"
            assert cert_info.port == 1965
            assert cert_info.path == "/test"
            assert cert_info.fingerprint.startswith("sha256:")

    def test_generate_certificate_custom_common_name(self):
        """Test certificate generation with custom common name."""
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = ClientCertificateManager(temp_dir)

            cert_path, key_path = manager.generate_certificate(
                "example.com", common_name="custom-cert-name"
            )

            # Check that files use the custom name
            assert "custom-cert-name.crt" in cert_path
            assert "custom-cert-name.key" in key_path

    def test_extract_common_name(self):
        """Test common name extraction from subject."""
        with patch.object(ClientCertificateManager, "_load_registry"):
            manager = ClientCertificateManager("/tmp/test")

            # Test normal case
            subject = "CN=test-cert,O=Gemini Client"
            cn = manager._extract_common_name(subject)
            assert cn == "test-cert"

            # Test with spaces
            subject = "CN=test cert, O=Gemini Client"
            cn = manager._extract_common_name(subject)
            assert cn == "test cert"

            # Test no CN
            subject = "O=Gemini Client"
            cn = manager._extract_common_name(subject)
            assert cn == "unknown"

    def test_list_certificates(self):
        """Test listing certificates."""
        with patch.object(ClientCertificateManager, "_load_registry"):
            manager = ClientCertificateManager("/tmp/test")

            # Add test certificates
            cert1 = GeminiCertificateInfo(
                fingerprint="sha256:abc123",
                subject="CN=cert1",
                issuer="CN=cert1",
                not_before="2023-01-01T00:00:00",
                not_after="2024-01-01T00:00:00",
                host="example.com",
                port=1965,
                path="/",
            )
            cert2 = GeminiCertificateInfo(
                fingerprint="sha256:def456",
                subject="CN=cert2",
                issuer="CN=cert2",
                not_before="2023-01-01T00:00:00",
                not_after="2024-01-01T00:00:00",
                host="test.com",
                port=1965,
                path="/",
            )

            manager._certificates["example.com:1965/"] = cert1
            manager._certificates["test.com:1965/"] = cert2

            certs = manager.list_certificates()
            assert len(certs) == 2
            assert cert1 in certs
            assert cert2 in certs

    def test_get_certificate_for_scope_exact_match(self):
        """Test getting certificate for exact scope match."""
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = ClientCertificateManager(temp_dir)

            # Generate a certificate
            cert_path, key_path = manager.generate_certificate(
                "example.com", 1965, "/test"
            )

            # Get certificate for same scope
            result = manager.get_certificate_for_scope("example.com", 1965, "/test")
            assert result is not None
            assert result[0] == cert_path
            assert result[1] == key_path

    def test_get_certificate_for_scope_no_match(self):
        """Test getting certificate when no match exists."""
        with patch.object(ClientCertificateManager, "_load_registry"):
            manager = ClientCertificateManager("/tmp/test")

            result = manager.get_certificate_for_scope("example.com", 1965, "/test")
            assert result is None

    def test_get_certificate_for_scope_parent_path_match(self):
        """Test getting certificate for parent path match."""
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = ClientCertificateManager(temp_dir)

            # Generate certificate for root path
            cert_path, key_path = manager.generate_certificate("example.com", 1965, "/")

            # Should match for subpath
            result = manager.get_certificate_for_scope("example.com", 1965, "/subpath")
            assert result is not None
            assert result[0] == cert_path
            assert result[1] == key_path

    def test_get_certificate_for_scope_best_match(self):
        """Test getting certificate with best path match."""
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = ClientCertificateManager(temp_dir)

            # Generate certificates for different paths
            cert_path1, key_path1 = manager.generate_certificate(
                "example.com", 1965, "/"
            )
            cert_path2, key_path2 = manager.generate_certificate(
                "example.com", 1965, "/api"
            )

            # Should match the more specific path
            result = manager.get_certificate_for_scope("example.com", 1965, "/api/v1")
            assert result is not None
            assert result[0] == cert_path2
            assert result[1] == key_path2

    def test_get_certificate_for_scope_missing_files(self):
        """Test getting certificate when files are missing."""
        with patch.object(ClientCertificateManager, "_load_registry"):
            manager = ClientCertificateManager("/tmp/test")

            # Add certificate info but no actual files
            cert_info = GeminiCertificateInfo(
                fingerprint="sha256:abc123",
                subject="CN=test-cert",
                issuer="CN=test-cert",
                not_before="2023-01-01T00:00:00",
                not_after="2024-01-01T00:00:00",
                host="example.com",
                port=1965,
                path="/",
            )
            manager._certificates["example.com:1965/"] = cert_info

            result = manager.get_certificate_for_scope("example.com", 1965, "/")
            assert result is None

    def test_remove_certificate_success(self):
        """Test successful certificate removal."""
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = ClientCertificateManager(temp_dir)

            # Generate a certificate
            cert_path, key_path = manager.generate_certificate(
                "example.com", 1965, "/test"
            )

            # Verify files exist
            assert Path(cert_path).exists()
            assert Path(key_path).exists()

            # Remove certificate
            result = manager.remove_certificate("example.com", 1965, "/test")
            assert result is True

            # Verify files are removed
            assert not Path(cert_path).exists()
            assert not Path(key_path).exists()

            # Verify removed from registry
            key = manager._get_cert_key("example.com", 1965, "/test")
            assert key not in manager._certificates

    def test_remove_certificate_not_found(self):
        """Test removing non-existent certificate."""
        with patch.object(ClientCertificateManager, "_load_registry"):
            manager = ClientCertificateManager("/tmp/test")

            result = manager.remove_certificate("example.com", 1965, "/test")
            assert result is False

    def test_remove_certificate_file_error(self):
        """Test certificate removal with file deletion error."""
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = ClientCertificateManager(temp_dir)

            # Add certificate info
            cert_info = GeminiCertificateInfo(
                fingerprint="sha256:abc123",
                subject="CN=test-cert",
                issuer="CN=test-cert",
                not_before="2023-01-01T00:00:00",
                not_after="2024-01-01T00:00:00",
                host="example.com",
                port=1965,
                path="/",
            )
            key = manager._get_cert_key("example.com", 1965, "/")
            manager._certificates[key] = cert_info

            # Mock file deletion to raise error
            with patch("pathlib.Path.unlink", side_effect=OSError("Permission denied")):
                result = manager.remove_certificate("example.com", 1965, "/")
                # Should still return True and remove from registry
                assert result is True
                assert key not in manager._certificates

    def test_cleanup_expired_certificates(self):
        """Test cleanup of expired certificates."""
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = ClientCertificateManager(temp_dir)

            # Add expired certificate
            expired_cert = GeminiCertificateInfo(
                fingerprint="sha256:abc123",
                subject="CN=expired-cert",
                issuer="CN=expired-cert",
                not_before="2022-01-01T00:00:00",
                not_after="2022-12-31T23:59:59",  # Expired
                host="expired.com",
                port=1965,
                path="/",
            )

            # Add valid certificate
            valid_cert = GeminiCertificateInfo(
                fingerprint="sha256:def456",
                subject="CN=valid-cert",
                issuer="CN=valid-cert",
                not_before="2023-01-01T00:00:00",
                not_after="2025-12-31T23:59:59",  # Valid
                host="valid.com",
                port=1965,
                path="/",
            )

            manager._certificates["expired.com:1965/"] = expired_cert
            manager._certificates["valid.com:1965/"] = valid_cert

            # Mock remove_certificate to track calls
            with patch.object(
                manager, "remove_certificate", return_value=True
            ) as mock_remove:
                count = manager.cleanup_expired()

                assert count == 1
                mock_remove.assert_called_once_with("expired.com", 1965, "/")

    def test_cleanup_expired_invalid_date(self):
        """Test cleanup with invalid date format."""
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = ClientCertificateManager(temp_dir)

            # Add certificate with invalid date
            invalid_cert = GeminiCertificateInfo(
                fingerprint="sha256:abc123",
                subject="CN=invalid-cert",
                issuer="CN=invalid-cert",
                not_before="2023-01-01T00:00:00",
                not_after="invalid-date",  # Invalid format
                host="invalid.com",
                port=1965,
                path="/",
            )

            manager._certificates["invalid.com:1965/"] = invalid_cert

            # Mock remove_certificate to track calls
            with patch.object(
                manager, "remove_certificate", return_value=True
            ) as mock_remove:
                count = manager.cleanup_expired()

                assert count == 1
                mock_remove.assert_called_once_with("invalid.com", 1965, "/")
