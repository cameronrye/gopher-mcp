"""Tests for fingerprints module."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from gopher_mcp.fingerprints import (
    HashAlgorithm,
    CertificateFingerprint,
    FingerprintValidator,
    FingerprintStore,
)


class TestHashAlgorithm:
    """Test HashAlgorithm enum."""

    def test_algorithm_values(self):
        """Test hash algorithm enum values."""
        assert HashAlgorithm.SHA256.value == "sha256"
        assert HashAlgorithm.SHA1.value == "sha1"
        assert HashAlgorithm.MD5.value == "md5"


class TestCertificateFingerprint:
    """Test CertificateFingerprint class."""

    def test_basic_fingerprint_creation(self):
        """Test basic fingerprint creation."""
        sha256 = "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
        fingerprint = CertificateFingerprint(sha256=sha256)

        assert fingerprint.sha256 == sha256
        assert fingerprint.sha1 is None
        assert fingerprint.md5 is None

    def test_fingerprint_with_all_algorithms(self):
        """Test fingerprint with all hash algorithms."""
        sha256 = "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
        sha1 = "1234567890abcdef12345678"
        md5 = "1234567890abcdef12345678"

        fingerprint = CertificateFingerprint(sha256=sha256, sha1=sha1, md5=md5)

        assert fingerprint.sha256 == sha256
        assert fingerprint.sha1 == sha1
        assert fingerprint.md5 == md5

    def test_normalize_fingerprint_with_prefixes(self):
        """Test fingerprint normalization with prefixes."""
        sha256_with_prefix = (
            "sha256:ABCDEF1234567890abcdef1234567890abcdef1234567890abcdef1234567890"
        )
        fingerprint = CertificateFingerprint(sha256=sha256_with_prefix)

        expected = "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"
        assert fingerprint.sha256 == expected

    def test_normalize_fingerprint_with_colons(self):
        """Test fingerprint normalization with colons."""
        sha256_with_colons = "AB:CD:EF:12:34:56:78:90:ab:cd:ef:12:34:56:78:90:ab:cd:ef:12:34:56:78:90:ab:cd:ef:12:34:56:78:90"
        fingerprint = CertificateFingerprint(sha256=sha256_with_colons)

        expected = "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"
        assert fingerprint.sha256 == expected

    def test_normalize_fingerprint_with_spaces(self):
        """Test fingerprint normalization with spaces."""
        sha256_with_spaces = "AB CD EF 12 34 56 78 90 ab cd ef 12 34 56 78 90 ab cd ef 12 34 56 78 90 ab cd ef 12 34 56 78 90"
        fingerprint = CertificateFingerprint(sha256=sha256_with_spaces)

        expected = "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"
        assert fingerprint.sha256 == expected

    def test_from_certificate(self):
        """Test creating fingerprint from certificate DER bytes."""
        cert_der = b"fake certificate data"

        fingerprint = CertificateFingerprint.from_certificate(cert_der)

        # Should have all three hash algorithms
        assert fingerprint.sha256 is not None
        assert fingerprint.sha1 is not None
        assert fingerprint.md5 is not None
        assert len(fingerprint.sha256) == 64
        assert len(fingerprint.sha1) == 40
        assert len(fingerprint.md5) == 32

    def test_get_fingerprint_sha256(self):
        """Test getting SHA256 fingerprint."""
        sha256 = "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
        fingerprint = CertificateFingerprint(sha256=sha256)

        result = fingerprint.get_fingerprint(HashAlgorithm.SHA256)
        assert result == sha256

    def test_get_fingerprint_sha1(self):
        """Test getting SHA1 fingerprint."""
        sha256 = "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
        sha1 = "1234567890abcdef12345678"
        fingerprint = CertificateFingerprint(sha256=sha256, sha1=sha1)

        result = fingerprint.get_fingerprint(HashAlgorithm.SHA1)
        assert result == sha1

    def test_get_fingerprint_md5(self):
        """Test getting MD5 fingerprint."""
        sha256 = "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
        md5 = "1234567890abcdef12345678"
        fingerprint = CertificateFingerprint(sha256=sha256, md5=md5)

        result = fingerprint.get_fingerprint(HashAlgorithm.MD5)
        assert result == md5

    def test_get_fingerprint_none(self):
        """Test getting fingerprint when not available."""
        sha256 = "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
        fingerprint = CertificateFingerprint(sha256=sha256)

        result = fingerprint.get_fingerprint(HashAlgorithm.SHA1)
        assert result is None

    def test_matches_string_sha256(self):
        """Test matching against string fingerprint (SHA256)."""
        sha256 = "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
        fingerprint = CertificateFingerprint(sha256=sha256)

        assert fingerprint.matches(sha256)
        assert fingerprint.matches(sha256.upper())
        assert fingerprint.matches(f"sha256:{sha256}")
        assert not fingerprint.matches("different_fingerprint")

    def test_matches_string_sha1(self):
        """Test matching against string fingerprint (SHA1)."""
        sha256 = "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
        sha1 = "1234567890abcdef12345678"
        fingerprint = CertificateFingerprint(sha256=sha256, sha1=sha1)

        assert fingerprint.matches(sha1)
        assert fingerprint.matches(sha1.upper())
        assert fingerprint.matches(f"sha1:{sha1}")

    def test_matches_fingerprint_object_sha256(self):
        """Test matching against another CertificateFingerprint object (SHA256)."""
        sha256 = "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
        fingerprint1 = CertificateFingerprint(sha256=sha256)
        fingerprint2 = CertificateFingerprint(sha256=sha256)

        assert fingerprint1.matches(fingerprint2)

    def test_matches_fingerprint_object_sha1(self):
        """Test matching against another CertificateFingerprint object (SHA1)."""
        sha256_1 = "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
        sha256_2 = "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"
        sha1 = "1234567890abcdef12345678"

        fingerprint1 = CertificateFingerprint(sha256=sha256_1, sha1=sha1)
        fingerprint2 = CertificateFingerprint(sha256=sha256_2, sha1=sha1)

        assert fingerprint1.matches(fingerprint2)

    def test_matches_fingerprint_object_md5(self):
        """Test matching against another CertificateFingerprint object (MD5)."""
        sha256_1 = "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
        sha256_2 = "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"
        md5 = "1234567890abcdef12345678"

        fingerprint1 = CertificateFingerprint(sha256=sha256_1, md5=md5)
        fingerprint2 = CertificateFingerprint(sha256=sha256_2, md5=md5)

        assert fingerprint1.matches(fingerprint2)

    def test_matches_fingerprint_object_no_match(self):
        """Test no match between different CertificateFingerprint objects."""
        sha256_1 = "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
        sha256_2 = "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"

        fingerprint1 = CertificateFingerprint(sha256=sha256_1)
        fingerprint2 = CertificateFingerprint(sha256=sha256_2)

        assert not fingerprint1.matches(fingerprint2)

    def test_to_dict(self):
        """Test converting fingerprint to dictionary."""
        sha256 = "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
        sha1 = "1234567890abcdef12345678"
        fingerprint = CertificateFingerprint(sha256=sha256, sha1=sha1)

        result = fingerprint.to_dict()

        assert result["sha256"] == sha256
        assert result["sha1"] == sha1
        assert "md5" not in result

    def test_to_dict_all_algorithms(self):
        """Test converting fingerprint with all algorithms to dictionary."""
        sha256 = "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
        sha1 = "1234567890abcdef12345678"
        md5 = "1234567890abcdef12345678"
        fingerprint = CertificateFingerprint(sha256=sha256, sha1=sha1, md5=md5)

        result = fingerprint.to_dict()

        assert result["sha256"] == sha256
        assert result["sha1"] == sha1
        assert result["md5"] == md5

    def test_from_dict(self):
        """Test creating fingerprint from dictionary."""
        data = {
            "sha256": "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
            "sha1": "1234567890abcdef12345678",
        }

        fingerprint = CertificateFingerprint.from_dict(data)

        assert fingerprint.sha256 == data["sha256"]
        assert fingerprint.sha1 == data["sha1"]
        assert fingerprint.md5 is None

    def test_from_dict_all_algorithms(self):
        """Test creating fingerprint from dictionary with all algorithms."""
        data = {
            "sha256": "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef",
            "sha1": "1234567890abcdef12345678",
            "md5": "1234567890abcdef12345678",
        }

        fingerprint = CertificateFingerprint.from_dict(data)

        assert fingerprint.sha256 == data["sha256"]
        assert fingerprint.sha1 == data["sha1"]
        assert fingerprint.md5 == data["md5"]


class TestFingerprintValidator:
    """Test FingerprintValidator class."""

    def test_is_valid_fingerprint_sha256_valid(self):
        """Test valid SHA256 fingerprint validation."""
        valid_sha256 = (
            "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"
        )

        assert FingerprintValidator.is_valid_fingerprint(
            valid_sha256, HashAlgorithm.SHA256
        )

    def test_is_valid_fingerprint_sha256_invalid_length(self):
        """Test invalid SHA256 fingerprint validation (wrong length)."""
        invalid_sha256 = "1234567890abcdef"  # Too short

        assert not FingerprintValidator.is_valid_fingerprint(
            invalid_sha256, HashAlgorithm.SHA256
        )

    def test_is_valid_fingerprint_sha256_invalid_chars(self):
        """Test invalid SHA256 fingerprint validation (invalid characters)."""
        invalid_sha256 = "1234567890abcdefg234567890abcdef1234567890abcdef1234567890abcdef"  # 'g' is invalid

        assert not FingerprintValidator.is_valid_fingerprint(
            invalid_sha256, HashAlgorithm.SHA256
        )

    def test_is_valid_fingerprint_sha1_valid(self):
        """Test valid SHA1 fingerprint validation."""
        valid_sha1 = "1234567890abcdef1234567890abcdef12345678"

        assert FingerprintValidator.is_valid_fingerprint(valid_sha1, HashAlgorithm.SHA1)

    def test_is_valid_fingerprint_md5_valid(self):
        """Test valid MD5 fingerprint validation."""
        valid_md5 = "1234567890abcdef1234567890abcdef"

        assert FingerprintValidator.is_valid_fingerprint(valid_md5, HashAlgorithm.MD5)

    def test_detect_algorithm_sha256(self):
        """Test detecting SHA256 algorithm."""
        sha256 = "1234567890abcdef1234567890abcdef1234567890abcdef1234567890abcdef"

        result = FingerprintValidator.detect_algorithm(sha256)
        assert result == HashAlgorithm.SHA256

    def test_detect_algorithm_sha1(self):
        """Test detecting SHA1 algorithm."""
        sha1 = "1234567890abcdef1234567890abcdef12345678"

        result = FingerprintValidator.detect_algorithm(sha1)
        assert result == HashAlgorithm.SHA1

    def test_detect_algorithm_md5(self):
        """Test detecting MD5 algorithm."""
        md5 = "1234567890abcdef1234567890abcdef"

        result = FingerprintValidator.detect_algorithm(md5)
        assert result == HashAlgorithm.MD5

    def test_detect_algorithm_unknown(self):
        """Test detecting unknown algorithm."""
        unknown = "123456"  # Too short for any known algorithm

        result = FingerprintValidator.detect_algorithm(unknown)
        assert result is None

    def test_format_fingerprint_no_colons(self):
        """Test formatting fingerprint without colons."""
        fingerprint = "abcdef1234567890"

        result = FingerprintValidator.format_fingerprint(fingerprint, with_colons=False)
        assert result == "ABCDEF1234567890"

    def test_format_fingerprint_with_colons(self):
        """Test formatting fingerprint with colons."""
        fingerprint = "abcdef1234567890"

        result = FingerprintValidator.format_fingerprint(fingerprint, with_colons=True)
        assert result == "ab:cd:ef:12:34:56:78:90"


class TestFingerprintStore:
    """Test FingerprintStore class."""

    def test_initialization_default_path(self):
        """Test store initialization with default path."""
        with (
            patch("gopher_mcp.fingerprints.get_home_directory") as mock_home,
            patch("pathlib.Path.mkdir") as mock_mkdir,
            patch.object(FingerprintStore, "_load_fingerprints"),
        ):
            mock_home.return_value = Path("/home/user")

            store = FingerprintStore()

            # Use Path to normalize the path for platform compatibility
            expected_path = str(Path("/home/user/.gemini/fingerprints.json"))
            assert store.storage_path == expected_path
            mock_mkdir.assert_called_once_with(exist_ok=True)

    def test_initialization_custom_path(self):
        """Test store initialization with custom path."""
        with patch.object(FingerprintStore, "_load_fingerprints"):
            custom_path = "/custom/fingerprints.json"
            store = FingerprintStore(custom_path)

            assert store.storage_path == custom_path

    def test_get_key(self):
        """Test storage key generation."""
        with patch.object(FingerprintStore, "_load_fingerprints"):
            store = FingerprintStore("/tmp/test.json")

            key = store._get_key("example.com", 1965)
            assert key == "example.com:1965"

    def test_load_fingerprints_no_file(self):
        """Test loading fingerprints when no file exists."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "fingerprints.json")
            store = FingerprintStore(storage_path)

            assert store._fingerprints == {}

    def test_load_fingerprints_with_file(self):
        """Test loading fingerprints from existing file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "fingerprints.json")

            # Create test data
            test_data = {
                "example.com:1965": {
                    "host": "example.com",
                    "port": 1965,
                    "fingerprint": {"sha256": "abc123"},
                    "stored_at": 1234567890,
                    "metadata": {},
                }
            }

            with open(storage_path, "w") as f:
                json.dump(test_data, f)

            store = FingerprintStore(storage_path)

            assert len(store._fingerprints) == 1
            assert "example.com:1965" in store._fingerprints

    def test_load_fingerprints_invalid_json(self):
        """Test loading fingerprints with invalid JSON."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "fingerprints.json")

            with open(storage_path, "w") as f:
                f.write("invalid json")

            store = FingerprintStore(storage_path)

            assert store._fingerprints == {}

    def test_save_fingerprints(self):
        """Test saving fingerprints to file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "fingerprints.json")
            store = FingerprintStore(storage_path)

            # Add test data
            store._fingerprints["test:1965"] = {
                "host": "test",
                "port": 1965,
                "fingerprint": {"sha256": "abc123"},
                "stored_at": 1234567890,
                "metadata": {},
            }

            store._save_fingerprints()

            # Verify file was created
            assert Path(storage_path).exists()

            with open(storage_path, "r") as f:
                data = json.load(f)

            assert "test:1965" in data

    def test_save_fingerprints_error(self):
        """Test save fingerprints error handling."""
        with patch.object(FingerprintStore, "_load_fingerprints"):
            store = FingerprintStore("/invalid/path/fingerprints.json")

            # Mock atomic_write_json to raise an error
            with patch(
                "gopher_mcp.fingerprints.atomic_write_json",
                side_effect=OSError("Permission denied"),
            ):
                with pytest.raises(Exception):
                    store._save_fingerprints()

    def test_store_fingerprint(self):
        """Test storing a fingerprint."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "fingerprints.json")
            store = FingerprintStore(storage_path)

            fingerprint = CertificateFingerprint(sha256="abc123")
            metadata = {"test": "data"}

            with patch("time.time", return_value=1234567890):
                store.store_fingerprint("example.com", 1965, fingerprint, metadata)

            # Verify stored
            key = "example.com:1965"
            assert key in store._fingerprints
            entry = store._fingerprints[key]
            assert entry["host"] == "example.com"
            assert entry["port"] == 1965
            assert entry["fingerprint"]["sha256"] == "abc123"
            assert entry["stored_at"] == 1234567890
            assert entry["metadata"] == metadata

    def test_get_fingerprint_exists(self):
        """Test getting existing fingerprint."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "fingerprints.json")
            store = FingerprintStore(storage_path)

            # Store a fingerprint first
            fingerprint = CertificateFingerprint(sha256="abc123")
            store.store_fingerprint("example.com", 1965, fingerprint)

            # Get it back
            result = store.get_fingerprint("example.com", 1965)
            assert result is not None
            assert result.sha256 == "abc123"

    def test_get_fingerprint_not_exists(self):
        """Test getting non-existent fingerprint."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "fingerprints.json")
            store = FingerprintStore(storage_path)

            result = store.get_fingerprint("example.com", 1965)
            assert result is None

    def test_search_fingerprints_by_fingerprint(self):
        """Test searching fingerprints by fingerprint value."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "fingerprints.json")
            store = FingerprintStore(storage_path)

            # Store test fingerprints
            fp1 = CertificateFingerprint(sha256="abc123")
            fp2 = CertificateFingerprint(sha256="def456")
            store.store_fingerprint("example.com", 1965, fp1)
            store.store_fingerprint("test.com", 1965, fp2)

            # Search by fingerprint
            results = store.search_fingerprints(fingerprint="abc123")
            assert len(results) == 1
            assert results[0]["host"] == "example.com"

    def test_search_fingerprints_by_host_pattern(self):
        """Test searching fingerprints by host pattern."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "fingerprints.json")
            store = FingerprintStore(storage_path)

            # Store test fingerprints
            fp1 = CertificateFingerprint(sha256="abc123")
            fp2 = CertificateFingerprint(sha256="def456")
            store.store_fingerprint("example.com", 1965, fp1)
            store.store_fingerprint("test.com", 1965, fp2)

            # Search by host pattern
            results = store.search_fingerprints(host_pattern="*.com")
            assert len(results) == 2

            results = store.search_fingerprints(host_pattern="example.*")
            assert len(results) == 1
            assert results[0]["host"] == "example.com"

    def test_search_fingerprints_by_algorithm(self):
        """Test searching fingerprints by algorithm."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "fingerprints.json")
            store = FingerprintStore(storage_path)

            # Store fingerprints with different algorithms
            fp1 = CertificateFingerprint(sha256="abc123", sha1="def456")
            fp2 = CertificateFingerprint(sha256="ghi789")  # No SHA1
            store.store_fingerprint("example.com", 1965, fp1)
            store.store_fingerprint("test.com", 1965, fp2)

            # Search by algorithm
            results = store.search_fingerprints(algorithm=HashAlgorithm.SHA1)
            assert len(results) == 1
            assert results[0]["host"] == "example.com"

    def test_remove_fingerprint_exists(self):
        """Test removing existing fingerprint."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "fingerprints.json")
            store = FingerprintStore(storage_path)

            # Store a fingerprint
            fingerprint = CertificateFingerprint(sha256="abc123")
            store.store_fingerprint("example.com", 1965, fingerprint)

            # Remove it
            result = store.remove_fingerprint("example.com", 1965)
            assert result is True

            # Verify removed
            assert "example.com:1965" not in store._fingerprints

    def test_remove_fingerprint_not_exists(self):
        """Test removing non-existent fingerprint."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "fingerprints.json")
            store = FingerprintStore(storage_path)

            result = store.remove_fingerprint("example.com", 1965)
            assert result is False

    def test_export_fingerprints(self):
        """Test exporting fingerprints to file."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "fingerprints.json")
            export_path = str(Path(temp_dir) / "export.json")
            store = FingerprintStore(storage_path)

            # Store a fingerprint
            fingerprint = CertificateFingerprint(sha256="abc123")
            store.store_fingerprint("example.com", 1965, fingerprint)

            # Export
            store.export_fingerprints(export_path)

            # Verify export file
            assert Path(export_path).exists()
            with open(export_path, "r") as f:
                data = json.load(f)
            assert "example.com:1965" in data

    def test_import_fingerprints_merge(self):
        """Test importing fingerprints with merge."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "fingerprints.json")
            import_path = str(Path(temp_dir) / "import.json")
            store = FingerprintStore(storage_path)

            # Store existing fingerprint
            fp1 = CertificateFingerprint(sha256="abc123")
            store.store_fingerprint("existing.com", 1965, fp1)

            # Create import data
            import_data = {
                "new.com:1965": {
                    "host": "new.com",
                    "port": 1965,
                    "fingerprint": {"sha256": "def456"},
                    "stored_at": 1234567890,
                    "metadata": {},
                }
            }

            with open(import_path, "w") as f:
                json.dump(import_data, f)

            # Import with merge
            count = store.import_fingerprints(import_path, merge=True)

            assert count == 1
            assert "existing.com:1965" in store._fingerprints
            assert "new.com:1965" in store._fingerprints

    def test_import_fingerprints_no_merge(self):
        """Test importing fingerprints without merge."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "fingerprints.json")
            import_path = str(Path(temp_dir) / "import.json")
            store = FingerprintStore(storage_path)

            # Store existing fingerprint
            fp1 = CertificateFingerprint(sha256="abc123")
            store.store_fingerprint("existing.com", 1965, fp1)

            # Create import data
            import_data = {
                "new.com:1965": {
                    "host": "new.com",
                    "port": 1965,
                    "fingerprint": {"sha256": "def456"},
                    "stored_at": 1234567890,
                    "metadata": {},
                }
            }

            with open(import_path, "w") as f:
                json.dump(import_data, f)

            # Import without merge
            count = store.import_fingerprints(import_path, merge=False)

            assert count == 1
            assert "existing.com:1965" not in store._fingerprints
            assert "new.com:1965" in store._fingerprints

    def test_import_fingerprints_duplicate_with_merge(self):
        """Test importing duplicate fingerprints with merge."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "fingerprints.json")
            import_path = str(Path(temp_dir) / "import.json")
            store = FingerprintStore(storage_path)

            # Store existing fingerprint
            fp1 = CertificateFingerprint(sha256="abc123")
            store.store_fingerprint("example.com", 1965, fp1)

            # Create import data with same key
            import_data = {
                "example.com:1965": {
                    "host": "example.com",
                    "port": 1965,
                    "fingerprint": {"sha256": "def456"},
                    "stored_at": 1234567890,
                    "metadata": {},
                }
            }

            with open(import_path, "w") as f:
                json.dump(import_data, f)

            # Import with merge (should not overwrite existing)
            count = store.import_fingerprints(import_path, merge=True)

            assert count == 0  # No new fingerprints imported
            # Original should still be there
            fp = store.get_fingerprint("example.com", 1965)
            assert fp.sha256 == "abc123"

    def test_get_statistics(self):
        """Test getting fingerprint statistics."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "fingerprints.json")
            store = FingerprintStore(storage_path)

            # Store fingerprints with different algorithms
            fp1 = CertificateFingerprint(sha256="abc123", sha1="def456", md5="ghi789")
            fp2 = CertificateFingerprint(sha256="jkl012", sha1="mno345")
            fp3 = CertificateFingerprint(sha256="pqr678")

            store.store_fingerprint("example.com", 1965, fp1)
            store.store_fingerprint("example.com", 443, fp2)
            store.store_fingerprint("test.com", 1965, fp3)

            stats = store.get_statistics()

            assert stats["total_fingerprints"] == 3
            assert stats["unique_hosts"] == 2
            assert stats["algorithms"]["sha256"] == 3
            assert stats["algorithms"]["sha1"] == 2
            assert stats["algorithms"]["md5"] == 1
            assert stats["storage_path"] == storage_path
