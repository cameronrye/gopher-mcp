"""Tests for tofu module."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from gopher_mcp.tofu import (
    TOFUValidationError,
    TOFUManager,
)
from gopher_mcp.models import TOFUEntry


class TestTOFUValidationError:
    """Test TOFUValidationError exception."""

    def test_basic_exception(self):
        """Test basic exception creation."""
        error = TOFUValidationError("Test error")
        assert str(error) == "Test error"
        assert error.entry is None
        assert isinstance(error, Exception)

    def test_exception_with_entry(self):
        """Test exception creation with TOFU entry."""
        entry = TOFUEntry(
            host="example.com",
            port=1965,
            fingerprint="abc123",
            first_seen=1234567890,
            last_seen=1234567890,
        )
        error = TOFUValidationError("Test error", entry)
        assert str(error) == "Test error"
        assert error.entry == entry


class TestTOFUManager:
    """Test TOFUManager class."""

    def test_initialization_default_path(self):
        """Test manager initialization with default path."""
        with patch("pathlib.Path.home") as mock_home, patch(
            "pathlib.Path.mkdir"
        ) as mock_mkdir, patch.object(TOFUManager, "_load_entries"):
            mock_home.return_value = Path("/home/user")

            manager = TOFUManager()

            assert manager.storage_path == "/home/user/.gemini/tofu.json"
            mock_mkdir.assert_called_once_with(exist_ok=True)

    def test_initialization_custom_path(self):
        """Test manager initialization with custom path."""
        with patch.object(TOFUManager, "_load_entries"):
            custom_path = "/custom/tofu.json"
            manager = TOFUManager(custom_path)

            assert manager.storage_path == custom_path

    def test_get_key(self):
        """Test storage key generation."""
        with patch.object(TOFUManager, "_load_entries"):
            manager = TOFUManager("/tmp/test.json")

            key = manager._get_key("example.com", 1965)
            assert key == "example.com:1965"

    def test_load_entries_no_file(self):
        """Test loading entries when no file exists."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "tofu.json")
            manager = TOFUManager(storage_path)

            assert manager._entries == {}

    def test_load_entries_with_file(self):
        """Test loading entries from existing file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "tofu.json")

            # Create test data
            test_data = {
                "example.com:1965": {
                    "host": "example.com",
                    "port": 1965,
                    "fingerprint": "abc123",
                    "first_seen": 1234567890,
                    "last_seen": 1234567890,
                    "expires": None,
                }
            }

            with open(storage_path, "w") as f:
                json.dump(test_data, f)

            manager = TOFUManager(storage_path)

            assert len(manager._entries) == 1
            assert "example.com:1965" in manager._entries
            entry = manager._entries["example.com:1965"]
            assert entry.host == "example.com"
            assert entry.fingerprint == "abc123"

    def test_load_entries_invalid_json(self):
        """Test loading entries with invalid JSON."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "tofu.json")

            with open(storage_path, "w") as f:
                f.write("invalid json")

            manager = TOFUManager(storage_path)

            assert manager._entries == {}

    def test_save_entries(self):
        """Test saving entries to file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "tofu.json")
            manager = TOFUManager(storage_path)

            # Add test entry
            entry = TOFUEntry(
                host="example.com",
                port=1965,
                fingerprint="abc123",
                first_seen=1234567890,
                last_seen=1234567890,
            )
            manager._entries["example.com:1965"] = entry

            manager._save_entries()

            # Verify file was created
            assert Path(storage_path).exists()

            with open(storage_path, "r") as f:
                data = json.load(f)

            assert "example.com:1965" in data
            assert data["example.com:1965"]["fingerprint"] == "abc123"

    def test_save_entries_error(self):
        """Test save entries error handling."""
        with patch.object(TOFUManager, "_load_entries"):
            manager = TOFUManager("/invalid/path/tofu.json")

            with pytest.raises(Exception):
                manager._save_entries()

    def test_validate_certificate_first_time(self):
        """Test validating certificate for first time (TOFU)."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "tofu.json")
            manager = TOFUManager(storage_path)

            with patch("time.time", return_value=1234567890):
                is_valid, warning = manager.validate_certificate(
                    "example.com", 1965, "abc123"
                )

            assert is_valid is True
            assert "trusted on first use" in warning

            # Verify entry was stored
            key = "example.com:1965"
            assert key in manager._entries
            entry = manager._entries[key]
            assert entry.fingerprint == "abc123"
            assert entry.first_seen == 1234567890
            assert entry.last_seen == 1234567890

    def test_validate_certificate_first_time_with_expiry(self):
        """Test validating certificate for first time with expiry info."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "tofu.json")
            manager = TOFUManager(storage_path)

            cert_info = {"notAfter": "Dec 31 23:59:59 2024 GMT"}

            with patch("time.time", return_value=1234567890):
                is_valid, warning = manager.validate_certificate(
                    "example.com", 1965, "abc123", cert_info
                )

            assert is_valid is True
            assert "trusted on first use" in warning

            # Verify entry has expiry
            entry = manager._entries["example.com:1965"]
            assert entry.expires is not None

    def test_validate_certificate_first_time_invalid_expiry(self):
        """Test validating certificate with invalid expiry format."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "tofu.json")
            manager = TOFUManager(storage_path)

            cert_info = {"notAfter": "invalid date format"}

            with patch("time.time", return_value=1234567890):
                is_valid, warning = manager.validate_certificate(
                    "example.com", 1965, "abc123", cert_info
                )

            assert is_valid is True

            # Verify entry has no expiry due to parse error
            entry = manager._entries["example.com:1965"]
            assert entry.expires is None

    def test_validate_certificate_sha256_prefix(self):
        """Test validating certificate with sha256: prefix."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "tofu.json")
            manager = TOFUManager(storage_path)

            with patch("time.time", return_value=1234567890):
                is_valid, warning = manager.validate_certificate(
                    "example.com", 1965, "sha256:abc123"
                )

            assert is_valid is True

            # Verify prefix was removed
            entry = manager._entries["example.com:1965"]
            assert entry.fingerprint == "abc123"

    def test_validate_certificate_existing_match(self):
        """Test validating certificate that matches existing entry."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "tofu.json")
            manager = TOFUManager(storage_path)

            # Add existing entry
            entry = TOFUEntry(
                host="example.com",
                port=1965,
                fingerprint="abc123",
                first_seen=1234567890,
                last_seen=1234567890,
            )
            manager._entries["example.com:1965"] = entry

            with patch("time.time", return_value=1234567900):
                is_valid, warning = manager.validate_certificate(
                    "example.com", 1965, "abc123"
                )

            assert is_valid is True
            assert warning is None

            # Verify last_seen was updated
            assert entry.last_seen == 1234567900

    def test_validate_certificate_fingerprint_mismatch(self):
        """Test validating certificate with fingerprint mismatch."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "tofu.json")
            manager = TOFUManager(storage_path)

            # Add existing entry
            entry = TOFUEntry(
                host="example.com",
                port=1965,
                fingerprint="abc123",
                first_seen=1234567890,
                last_seen=1234567890,
            )
            manager._entries["example.com:1965"] = entry

            with pytest.raises(TOFUValidationError) as exc_info:
                manager.validate_certificate("example.com", 1965, "def456")

            assert "Certificate for example.com:1965 has changed" in str(exc_info.value)
            assert exc_info.value.entry == entry

    def test_validate_certificate_expired(self):
        """Test validating expired certificate."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "tofu.json")
            manager = TOFUManager(storage_path)

            # Add existing entry with expiry in the past
            entry = TOFUEntry(
                host="example.com",
                port=1965,
                fingerprint="abc123",
                first_seen=1234567890,
                last_seen=1234567890,
                expires=1234567800,  # Expired
            )
            manager._entries["example.com:1965"] = entry

            with patch("time.time", return_value=1234567900):
                is_valid, warning = manager.validate_certificate(
                    "example.com", 1965, "abc123"
                )

            assert is_valid is True
            assert "has expired" in warning

    def test_update_certificate_new(self):
        """Test updating certificate for new host."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "tofu.json")
            manager = TOFUManager(storage_path)

            with patch("time.time", return_value=1234567890):
                manager.update_certificate("example.com", 1965, "abc123")

            # Verify entry was created
            key = "example.com:1965"
            assert key in manager._entries
            entry = manager._entries[key]
            assert entry.fingerprint == "abc123"
            assert entry.first_seen == 1234567890

    def test_update_certificate_existing_without_force(self):
        """Test updating existing certificate without force."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "tofu.json")
            manager = TOFUManager(storage_path)

            # Add existing entry
            entry = TOFUEntry(
                host="example.com",
                port=1965,
                fingerprint="abc123",
                first_seen=1234567890,
                last_seen=1234567890,
            )
            manager._entries["example.com:1965"] = entry

            with pytest.raises(TOFUValidationError) as exc_info:
                manager.update_certificate("example.com", 1965, "def456")

            assert "already exists" in str(exc_info.value)
            assert "force=True" in str(exc_info.value)

    def test_update_certificate_existing_with_force(self):
        """Test updating existing certificate with force."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "tofu.json")
            manager = TOFUManager(storage_path)

            # Add existing entry
            entry = TOFUEntry(
                host="example.com",
                port=1965,
                fingerprint="abc123",
                first_seen=1234567890,
                last_seen=1234567890,
            )
            manager._entries["example.com:1965"] = entry

            with patch("time.time", return_value=1234567900):
                manager.update_certificate("example.com", 1965, "def456", force=True)

            # Verify entry was updated
            assert entry.fingerprint == "def456"
            assert entry.last_seen == 1234567900
            assert entry.first_seen == 1234567890  # Should not change

    def test_update_certificate_with_expiry(self):
        """Test updating certificate with expiry info."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "tofu.json")
            manager = TOFUManager(storage_path)

            cert_info = {"notAfter": "Dec 31 23:59:59 2024 GMT"}

            with patch("time.time", return_value=1234567890):
                manager.update_certificate("example.com", 1965, "abc123", cert_info)

            # Verify entry has expiry
            entry = manager._entries["example.com:1965"]
            assert entry.expires is not None

    def test_update_certificate_sha256_prefix(self):
        """Test updating certificate with sha256: prefix."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "tofu.json")
            manager = TOFUManager(storage_path)

            with patch("time.time", return_value=1234567890):
                manager.update_certificate("example.com", 1965, "sha256:abc123")

            # Verify prefix was removed
            entry = manager._entries["example.com:1965"]
            assert entry.fingerprint == "abc123"

    def test_remove_certificate_exists(self):
        """Test removing existing certificate."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "tofu.json")
            manager = TOFUManager(storage_path)

            # Add entry
            entry = TOFUEntry(
                host="example.com",
                port=1965,
                fingerprint="abc123",
                first_seen=1234567890,
                last_seen=1234567890,
            )
            manager._entries["example.com:1965"] = entry

            result = manager.remove_certificate("example.com", 1965)

            assert result is True
            assert "example.com:1965" not in manager._entries

    def test_remove_certificate_not_exists(self):
        """Test removing non-existent certificate."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "tofu.json")
            manager = TOFUManager(storage_path)

            result = manager.remove_certificate("example.com", 1965)

            assert result is False

    def test_list_certificates(self):
        """Test listing all certificates."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "tofu.json")
            manager = TOFUManager(storage_path)

            # Add test entries
            entry1 = TOFUEntry(
                host="example.com",
                port=1965,
                fingerprint="abc123",
                first_seen=1234567890,
                last_seen=1234567890,
            )
            entry2 = TOFUEntry(
                host="test.com",
                port=1965,
                fingerprint="def456",
                first_seen=1234567890,
                last_seen=1234567890,
            )

            manager._entries["example.com:1965"] = entry1
            manager._entries["test.com:1965"] = entry2

            certificates = manager.list_certificates()

            assert len(certificates) == 2
            assert entry1 in certificates
            assert entry2 in certificates

    def test_cleanup_expired(self):
        """Test cleaning up expired certificates."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "tofu.json")
            manager = TOFUManager(storage_path)

            # Add expired entry
            expired_entry = TOFUEntry(
                host="expired.com",
                port=1965,
                fingerprint="abc123",
                first_seen=1234567890,
                last_seen=1234567890,
                expires=1234567800,  # Expired
            )

            # Add valid entry
            valid_entry = TOFUEntry(
                host="valid.com",
                port=1965,
                fingerprint="def456",
                first_seen=1234567890,
                last_seen=1234567890,
                expires=1234567999,  # Not expired
            )

            # Add entry without expiry
            no_expiry_entry = TOFUEntry(
                host="noexpiry.com",
                port=1965,
                fingerprint="ghi789",
                first_seen=1234567890,
                last_seen=1234567890,
            )

            manager._entries["expired.com:1965"] = expired_entry
            manager._entries["valid.com:1965"] = valid_entry
            manager._entries["noexpiry.com:1965"] = no_expiry_entry

            with patch("time.time", return_value=1234567900):
                count = manager.cleanup_expired()

            assert count == 1
            assert "expired.com:1965" not in manager._entries
            assert "valid.com:1965" in manager._entries
            assert "noexpiry.com:1965" in manager._entries

    def test_cleanup_expired_no_expired(self):
        """Test cleanup when no certificates are expired."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "tofu.json")
            manager = TOFUManager(storage_path)

            # Add valid entry
            entry = TOFUEntry(
                host="valid.com",
                port=1965,
                fingerprint="abc123",
                first_seen=1234567890,
                last_seen=1234567890,
                expires=1234567999,  # Not expired
            )
            manager._entries["valid.com:1965"] = entry

            with patch("time.time", return_value=1234567900):
                count = manager.cleanup_expired()

            assert count == 0
            assert "valid.com:1965" in manager._entries
