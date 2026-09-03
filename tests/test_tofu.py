"""Tests for tofu module."""

import json
import os
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from gopher_mcp.models import TOFUEntry
from gopher_mcp.tofu import (
    NOT_BEFORE_SKEW_SECONDS,
    TOFUExpiredError,
    TOFUManager,
    TOFUNotYetValidError,
    TOFUStorageError,
    TOFUValidationError,
    _parse_expiry,
    _parse_not_before,
)


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

    def test_initialization_default_path(self, monkeypatch, tmp_path):
        """A fresh install stores its pins under gopher-mcp's own data dir.

        ~/.gemini belongs to Google's Gemini CLI, so nothing is created there
        any more; XDG_DATA_HOME is honoured when it names one.
        """
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        monkeypatch.setattr("gopher_mcp.tofu.get_home_directory", lambda: tmp_path)

        manager = TOFUManager()

        assert manager.storage_path == str(
            tmp_path / "data" / "gopher-mcp" / "tofu.json"
        )
        # The store's own directory is created owner-only...
        state_dir = tmp_path / "data" / "gopher-mcp"
        assert state_dir.is_dir()
        if os.name != "nt":
            # Windows has no POSIX mode bits: a directory reports 0o777 there
            # whatever mode was requested, so asserting 0o700 fails on a
            # correctly-created store. Access control on that platform is the
            # ACL the user's profile directory already carries.
            assert state_dir.stat().st_mode & 0o777 == 0o700
        # ...and the other product's directory is left alone entirely.
        assert not (tmp_path / ".gemini").exists()

    def test_initialization_uses_existing_legacy_store(self, monkeypatch, tmp_path):
        """An install that already pinned hosts under ~/.gemini keeps that store.

        Relocating it would either lose the pins or make a pinned host look
        unpinned, which re-arms blind trust-on-first-use for every one of them.
        """
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
        monkeypatch.setattr("gopher_mcp.tofu.get_home_directory", lambda: tmp_path)
        legacy = tmp_path / ".gemini"
        legacy.mkdir()
        (legacy / "tofu.json").write_text(
            json.dumps(
                {
                    "example.com:1965": {
                        "host": "example.com",
                        "port": 1965,
                        "fingerprint": "ab" * 32,
                        "first_seen": 1.0,
                        "last_seen": 1.0,
                    }
                }
            )
        )

        manager = TOFUManager()

        assert manager.storage_path == str(legacy / "tofu.json")
        assert "example.com:1965" in manager._entries
        # Nothing is created in the new location while the legacy store stands.
        assert not (tmp_path / "data").exists()

    def test_initialization_platform_default_without_xdg(self, monkeypatch, tmp_path):
        """With no XDG_DATA_HOME the platform's own data location is used."""
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        monkeypatch.setattr("gopher_mcp.tofu.get_home_directory", lambda: tmp_path)

        manager = TOFUManager()

        store = Path(manager.storage_path)
        assert store.name == "tofu.json"
        assert store.parent.name == "gopher-mcp"
        # Under the home directory, and never in Gemini CLI's directory.
        assert tmp_path in store.parents
        assert tmp_path / ".gemini" not in store.parents

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
        """A corrupt store fails closed rather than silently resetting."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "tofu.json")

            with open(storage_path, "w") as f:
                f.write("invalid json")

            with pytest.raises(TOFUValidationError, match="corrupt"):
                TOFUManager(storage_path)

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

            with open(storage_path) as f:
                data = json.load(f)

            assert "example.com:1965" in data
            assert data["example.com:1965"]["fingerprint"] == "abc123"

    def test_save_entries_error(self, tmp_path):
        """A failed write surfaces as TOFUStorageError, never as a bare OSError.

        An OSError leaving this module is caught upstream by the robots probe's
        blanket transport handler, which describes a local disk fault as an
        unreachable capsule and advises a retry that can never succeed.
        """
        manager = TOFUManager(str(tmp_path / "tofu.json"))

        with (
            patch(
                "gopher_mcp.tofu.atomic_write_json",
                side_effect=OSError("Permission denied"),
            ),
            pytest.raises(TOFUStorageError) as exc_info,
        ):
            manager._save_entries()

        assert not isinstance(exc_info.value, OSError)
        assert "Permission denied" in str(exc_info.value)

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
                is_valid, _warning = manager.validate_certificate(
                    "example.com", 1965, "abc123", cert_info
                )

            assert is_valid is True

            # Verify entry has no expiry due to parse error
            entry = manager._entries["example.com:1965"]
            assert entry.expires is None

    def test_validate_certificate_first_use_expired_warns(self):
        """A cert already past notAfter on first use is pinned but flagged."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "tofu.json")
            manager = TOFUManager(storage_path)

            cert_info = {"notAfter": "Jan 01 00:00:00 2020 GMT"}
            with patch("time.time", return_value=1893456000):  # year ~2030
                is_valid, warning = manager.validate_certificate(
                    "example.com", 1965, "abc123", cert_info
                )

            assert is_valid is True  # TOFU still pins it
            assert warning is not None
            assert "expired" in warning.lower()

    def test_first_use_not_yet_valid_rejected_by_default(self):
        """A not-yet-valid cert (notBefore in the future) is refused on first
        use EVEN with reject_expired off (the default): a server presenting a
        cert before its validity window has no legitimate reason to and it is a
        strong active-MITM signal, so fail closed rather than pin it."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "tofu.json")
            manager = TOFUManager(storage_path)  # reject_expired defaults False

            cert_info = {"not_before_timestamp": 2000.0}
            with patch("time.time", return_value=1000.0):
                with pytest.raises(TOFUExpiredError, match="not yet valid"):
                    manager.validate_certificate(
                        "example.com", 1965, "abc123", cert_info
                    )

            assert "example.com:1965" not in manager._entries

    def test_first_use_not_yet_valid_rejected_with_reject_expired(self):
        """reject_expired also refuses a not-yet-valid cert (and does not pin)."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "tofu.json")
            manager = TOFUManager(storage_path, reject_expired=True)

            cert_info = {"not_before_timestamp": 2000.0}
            with patch("time.time", return_value=1000.0):
                with pytest.raises(TOFUExpiredError):
                    manager.validate_certificate(
                        "example.com", 1965, "abc123", cert_info
                    )

            assert "example.com:1965" not in manager._entries

    def test_not_yet_valid_refusal_has_its_own_type(self):
        """The refusal must be distinguishable from an expiry.

        Both used to arrive as TOFUExpiredError, so a caller could only report
        "certificate expired" for a certificate that is the opposite of expired
        -- sending an operator after a renewal that is not the problem.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = TOFUManager(str(Path(temp_dir) / "tofu.json"))

            cert_info = {"not_before_timestamp": 2000.0}
            with patch("time.time", return_value=1000.0):
                with pytest.raises(TOFUNotYetValidError) as exc_info:
                    manager.validate_certificate(
                        "example.com", 1965, "abc123", cert_info
                    )

        # Still an expiry error, so a caller that only knows that type keeps
        # behaving exactly as it did.
        assert isinstance(exc_info.value, TOFUExpiredError)
        assert "not yet valid" in str(exc_info.value)

    def test_first_use_tolerates_clock_skew_on_not_before(self):
        """A notBefore inside the skew window pins instead of failing hard.

        Capsules mint a self-signed certificate at startup with notBefore=now,
        so a server clock seconds ahead of ours used to fail first contact
        outright -- and keep failing, because nothing got pinned.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "tofu.json")
            manager = TOFUManager(storage_path)

            cert_info = {"not_before_timestamp": 1000.0 + NOT_BEFORE_SKEW_SECONDS - 1}
            with patch("time.time", return_value=1000.0):
                is_valid, warning = manager.validate_certificate(
                    "example.com", 1965, "abc123", cert_info
                )

            assert is_valid is True
            assert warning is not None and "trusted on first use" in warning
            assert "example.com:1965" in manager._entries

    def test_first_use_still_refuses_beyond_the_skew_window(self):
        """The tolerance is a window, not an amnesty: a genuinely premature
        certificate is the active-MITM signal this check exists for."""
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = TOFUManager(str(Path(temp_dir) / "tofu.json"))

            cert_info = {"not_before_timestamp": 1000.0 + NOT_BEFORE_SKEW_SECONDS + 1}
            with patch("time.time", return_value=1000.0):
                with pytest.raises(TOFUNotYetValidError):
                    manager.validate_certificate(
                        "example.com", 1965, "abc123", cert_info
                    )

            assert "example.com:1965" not in manager._entries

    def test_expired_pin_warns_but_valid_by_default(self):
        """Default policy keeps the Gemini-conventional fail-open on expiry."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "tofu.json")
            manager = TOFUManager(storage_path)
            manager._entries["example.com:1965"] = TOFUEntry(
                host="example.com",
                port=1965,
                fingerprint="abc123",
                first_seen=1.0,
                last_seen=1.0,
                expires=100.0,
            )

            with patch("time.time", return_value=200.0):
                is_valid, warning = manager.validate_certificate(
                    "example.com", 1965, "abc123"
                )

            assert is_valid is True
            assert warning is not None and "expired" in warning.lower()

    def test_expired_pin_fails_closed_when_reject_expired(self):
        """reject_expired opts a deployment into fail-closed on an expired pin,
        raising the distinct TOFUExpiredError (a TOFUValidationError subclass) so
        callers can report it as expiry rather than a fingerprint change."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "tofu.json")
            manager = TOFUManager(storage_path, reject_expired=True)
            manager._entries["example.com:1965"] = TOFUEntry(
                host="example.com",
                port=1965,
                fingerprint="abc123",
                first_seen=1.0,
                last_seen=1.0,
                expires=100.0,
            )

            with patch("time.time", return_value=200.0):
                with pytest.raises(TOFUExpiredError) as exc_info:
                    manager.validate_certificate("example.com", 1965, "abc123")

            assert isinstance(exc_info.value, TOFUValidationError)
            assert "expired" in str(exc_info.value).lower()

    def test_fingerprint_mismatch_warning_renders_first_seen_in_utc(self):
        """The security warning must render first_seen in UTC, not local time."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "tofu.json")
            manager = TOFUManager(storage_path)
            manager._entries["example.com:1965"] = TOFUEntry(
                host="example.com",
                port=1965,
                fingerprint="aa",
                first_seen=1.0,
                last_seen=1.0,
            )

            with pytest.raises(TOFUValidationError) as exc_info:
                manager.validate_certificate("example.com", 1965, "bb")

            assert "1970-01-01 00:00:01+00:00" in str(exc_info.value)

    def test_save_preserves_pins_written_by_another_instance(self):
        """A save must merge with on-disk state, not clobber a pin another
        process/instance wrote after this manager loaded (lost-pin)."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "tofu.json")
            m1 = TOFUManager(storage_path)
            m2 = TOFUManager(storage_path)  # both loaded the same (empty) store

            with patch("time.time", return_value=1000.0):
                m1.validate_certificate("a.example", 1965, "aa")  # m1 pins a
            with patch("time.time", return_value=1001.0):
                m2.validate_certificate("b.example", 1965, "bb")  # m2 must keep a

            reloaded = TOFUManager(storage_path)
            assert "a.example:1965" in reloaded._entries
            assert "b.example:1965" in reloaded._entries

    def test_remove_persists_across_reload_despite_merge(self):
        """Removal must win over the merge-with-disk step, not be resurrected."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "tofu.json")
            manager = TOFUManager(storage_path)
            with patch("time.time", return_value=1000.0):
                manager.validate_certificate("a.example", 1965, "aa")

            assert manager.remove_certificate("a.example", 1965) is True

            reloaded = TOFUManager(storage_path)
            assert "a.example:1965" not in reloaded._entries

    def test_last_seen_save_is_throttled(self):
        """A matching re-validation only touches last_seen; it must not rewrite
        the whole trust store to disk on every request (I/O amplification)."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "tofu.json")
            manager = TOFUManager(storage_path)

            with patch("time.time", return_value=1000):
                manager.validate_certificate("h.example", 1965, "fp")  # first-use save

            with patch.object(manager, "_save_entries") as mock_save:
                with patch("time.time", return_value=1010):  # within throttle window
                    manager.validate_certificate("h.example", 1965, "fp")
                assert mock_save.call_count == 0  # last_seen touch, no disk write

                with patch("time.time", return_value=2000):  # > interval later
                    manager.validate_certificate("h.example", 1965, "fp")
                assert mock_save.call_count == 1  # now flushed

    def test_validate_certificate_sha256_prefix(self):
        """Test validating certificate with sha256: prefix."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "tofu.json")
            manager = TOFUManager(storage_path)

            with patch("time.time", return_value=1234567890):
                is_valid, _warning = manager.validate_certificate(
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

    def test_pin_in_openssl_colon_uppercase_form_matches_wire_digest(self):
        """A cert pinned in colon-separated uppercase form still matches.

        Users copy fingerprints from ``openssl x509 -fingerprint`` or browser
        dialogs (``AB:CD:...``), but every live connection presents the
        canonical lowercase no-colon SHA-256 hexdigest. Without canonicalization
        the constant-time compare never matches and the user's own pin becomes a
        permanent CERTIFICATE_CHANGED denial.
        """
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "tofu.json")
            manager = TOFUManager(storage_path)

            manager.update_certificate("example.com", 1965, "AB:CD:EF:01")

            is_valid, _warning = manager.validate_certificate(
                "example.com", 1965, "abcdef01"
            )
            assert is_valid is True

    def test_validate_first_use_canonicalizes_stored_fingerprint(self):
        """A colon/uppercase fingerprint seen first is stored canonically."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "tofu.json")
            manager = TOFUManager(storage_path)

            with patch("time.time", return_value=1234567890):
                manager.validate_certificate("example.com", 1965, "AB:CD:EF:01")

            assert manager._entries["example.com:1965"].fingerprint == "abcdef01"

    def test_legacy_noncanonical_entry_canonicalized_on_load(self):
        """Hand-edited/legacy entries are canonicalized when loaded."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "tofu.json")
            with open(storage_path, "w") as f:
                json.dump(
                    {
                        "example.com:1965": {
                            "host": "example.com",
                            "port": 1965,
                            "fingerprint": "AB:CD:EF:01",
                            "first_seen": 1.0,
                            "last_seen": 1.0,
                            "expires": None,
                        }
                    },
                    f,
                )

            manager = TOFUManager(storage_path)
            is_valid, _warning = manager.validate_certificate(
                "example.com", 1965, "abcdef01"
            )
            assert is_valid is True

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

    def test_get_key_method(self):
        """Test the _get_key method."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "tofu.json")
            manager = TOFUManager(storage_path)

            # Test key generation
            key = manager._get_key("example.com", 1965)
            assert key == "example.com:1965"

            key2 = manager._get_key("test.org", 443)
            assert key2 == "test.org:443"

    def test_manager_with_invalid_home_directory(self, monkeypatch):
        """Test manager initialization when home directory cannot be determined."""
        monkeypatch.delenv("XDG_DATA_HOME", raising=False)
        with patch("gopher_mcp.tofu.get_home_directory", return_value=None):
            with pytest.raises(ValueError, match="Could not determine home directory"):
                TOFUManager()

    def test_load_entries_with_corrupted_file(self):
        """A corrupt store fails closed (refuses to start with empty pins)."""
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "tofu.json")

            # Create corrupted JSON file
            with open(storage_path, "w") as f:
                f.write("invalid json content")

            with pytest.raises(TOFUValidationError, match="corrupt"):
                TOFUManager(storage_path)


class TestTOFUHostKeyNormalization:
    """TOFU pins must key on a normalized host (case / trailing dot)."""

    def test_host_variants_share_one_pin(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = str(Path(temp_dir) / "tofu.json")
            mgr = TOFUManager(path)
            # First use under a mixed-case host.
            mgr.validate_certificate("Example.COM", 1965, "sha256:" + "a" * 64)
            # A case/trailing-dot variant with a DIFFERENT fingerprint must be
            # detected as a mismatch (same pin), not a fresh first-use.
            with pytest.raises(TOFUValidationError):
                mgr.validate_certificate("example.com.", 1965, "sha256:" + "b" * 64)


def _der_cert_info(not_after_days: int) -> dict:
    """Build cert info exactly as ``gemini_tls._parse_peer_cert`` produces it.

    Gemini runs under CERT_NONE, so the live path never sees the getpeercert()
    ``notAfter`` string every other test here uses -- it parses the DER and hands
    TOFU ``not_before_timestamp`` / ``not_after_timestamp`` floats instead.
    """
    import datetime

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    from gopher_mcp.gemini_tls import GeminiTLSClient

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "example.com")])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=400))
        .not_valid_after(now + datetime.timedelta(days=not_after_days))
        .sign(key, hashes.SHA256())
    )
    der = cert.public_bytes(serialization.Encoding.DER)
    return GeminiTLSClient._parse_peer_cert(der), cert.not_valid_after_utc.timestamp()


class TestTOFUExpiryFromDerCertInfo:
    """The DER-derived ``not_after_timestamp`` is the ONLY expiry format live
    connections produce, so it must actually be read: a typo in that key would
    make ``expires`` always None in production -- silently disabling
    reject_expired and every expiry warning -- with the suite still green."""

    def test_first_use_pins_expiry_from_not_after_timestamp(self):
        cert_info, expected_expiry = _der_cert_info(not_after_days=30)
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = TOFUManager(str(Path(temp_dir) / "tofu.json"))
            is_valid, warning = manager.validate_certificate(
                "example.com", 1965, "sha256:" + "a" * 64, cert_info
            )

        assert is_valid is True
        assert warning is not None and "trusted on first use" in warning
        entry = manager._entries["example.com:1965"]
        assert entry.expires == pytest.approx(expected_expiry)

    def test_reject_expired_uses_der_derived_expiry(self):
        """The same wiring must drive the fail-closed path, not just the field."""
        cert_info, _ = _der_cert_info(not_after_days=-1)  # already expired
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = TOFUManager(
                str(Path(temp_dir) / "tofu.json"), reject_expired=True
            )
            with pytest.raises(TOFUExpiredError, match="already expired"):
                manager.validate_certificate(
                    "example.com", 1965, "sha256:" + "a" * 64, cert_info
                )

        assert "example.com:1965" not in manager._entries


class TestTOFUFirstUseExpiredWithReject:
    """reject_expired + FIRST contact + an already-expired cert."""

    def test_first_use_expired_is_refused_and_not_pinned(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "tofu.json")
            manager = TOFUManager(storage_path, reject_expired=True)

            cert_info = {"not_after_timestamp": 1000.0}
            with patch("time.time", return_value=2000.0):
                with pytest.raises(TOFUExpiredError, match="already expired"):
                    manager.validate_certificate(
                        "example.com", 1965, "abc123", cert_info
                    )

            # Refusing must not leave a pin behind: trusting the fingerprint
            # here would silently grant the expired cert permanent acceptance.
            assert "example.com:1965" not in manager._entries
            assert not Path(storage_path).exists()


def _call_bounded(fn, timeout: float = 5.0):
    """Run ``fn`` on a worker thread and return its outcome, or fail on a hang.

    The behaviour under test is that an unavailable store lock RETURNS (raising)
    instead of blocking forever; asserting that inline would hang the whole suite
    if it ever regressed, so bound it here.
    """
    import threading

    outcome: list[object] = []

    def _run() -> None:
        try:
            outcome.append(fn())
        except BaseException as exc:  # returned to the caller, not swallowed
            outcome.append(exc)

    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
    thread.join(timeout)
    assert not thread.is_alive(), "store lock acquisition never returned"
    return outcome[0]


class TestTOFUStoreLocking:
    """The cross-process store lock must be bounded and explicit."""

    def test_wedged_lock_holder_raises_instead_of_hanging(self):
        """flock(LOCK_EX) has no timeout, so a wedged holder used to block the
        caller -- and, before the call moved off the loop, the whole event loop,
        freezing every tool call in the process -- forever and without an error."""
        import os

        fcntl = pytest.importorskip("fcntl")

        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "tofu.json")
            manager = TOFUManager(storage_path)

            fd = os.open(storage_path + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                with patch("gopher_mcp.tofu.LOCK_TIMEOUT_SECONDS", 0.1):
                    outcome = _call_bounded(
                        lambda: manager.validate_certificate(
                            "example.com", 1965, "abc123"
                        )
                    )
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)

        assert isinstance(outcome, TOFUStorageError)
        assert "Could not lock" in str(outcome)

    def test_last_seen_flush_survives_a_locked_store(self):
        """A refresh of the read-path last_seen is bookkeeping, not trust state:
        an unlockable store must not fail an otherwise valid request."""
        import os

        fcntl = pytest.importorskip("fcntl")

        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "tofu.json")
            manager = TOFUManager(storage_path)
            manager.validate_certificate("example.com", 1965, "abc123")
            manager._last_save_time = 0.0  # force the throttled flush

            fd = os.open(storage_path + ".lock", os.O_CREAT | os.O_RDWR, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX)
            try:
                with patch("gopher_mcp.tofu.LOCK_TIMEOUT_SECONDS", 0.1):
                    outcome = _call_bounded(
                        lambda: manager.validate_certificate(
                            "example.com", 1965, "abc123"
                        )
                    )
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)

        assert outcome == (True, None)


class TestTOFUMismatchRemediation:
    """A legitimate certificate rotation must come with a way out."""

    def test_mismatch_message_names_the_store_and_the_remedy(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            storage_path = str(Path(temp_dir) / "tofu.json")
            manager = TOFUManager(storage_path)
            manager.validate_certificate("example.com", 1965, "sha256:" + "a" * 64)

            with pytest.raises(TOFUValidationError) as exc_info:
                manager.validate_certificate("example.com", 1965, "sha256:" + "b" * 64)

        message = str(exc_info.value)
        assert storage_path in message
        assert "example.com:1965" in message
        # The supported remedy is the tool, with hand-editing as the fallback.
        assert "gemini_trust_update" in message
        assert "gemini_trust_list" in message
        # Only fingerprint PREFIXES may appear -- never a full digest.
        assert "a" * 64 not in message
        assert "b" * 64 not in message


class TestTOFUStoreWriteFailures:
    """A store that cannot be written must say so -- and record nothing."""

    @staticmethod
    def _store_that_refuses_writes():
        """Make the store's write fail, on every platform.

        A read-only directory is the real-world cause, but it cannot be the
        mechanism here: Windows ignores the mode bits ``chmod`` sets on a
        directory, so the write succeeded there and this whole class asserted
        nothing on a third of the matrix while reporting green. Failing the
        write itself exercises exactly the branch under test -- an OSError out
        of the persist step -- and does so identically everywhere.

        Scoped with ``patch`` rather than ``monkeypatch``: these tests go on to
        assert that the store works again once the fault clears, and
        ``monkeypatch`` only undoes at teardown, so the fault would still be in
        place for that half of the test.
        """
        return patch(
            "gopher_mcp.tofu.atomic_write_json",
            side_effect=PermissionError(13, "Permission denied"),
        )

    @staticmethod
    def _manager(tmp_path: Path) -> TOFUManager:
        store_dir = tmp_path / "store"
        store_dir.mkdir()
        return TOFUManager(str(store_dir / "tofu.json"))

    def test_unwritable_store_raises_storage_error_not_oserror(self, tmp_path):
        """The raw OSError used to escape as far as the robots probe's blanket
        transport handler, which reported a read-only disk as an unreachable
        capsule and told the caller to retry shortly -- forever."""
        manager = self._manager(tmp_path)
        with self._store_that_refuses_writes():
            with pytest.raises(TOFUStorageError) as exc_info:
                manager.validate_certificate("example.com", 1965, "ab" * 32)

        assert not isinstance(exc_info.value, OSError)
        assert "trust store" in str(exc_info.value)

    def test_pin_that_cannot_be_persisted_is_not_trusted_in_memory(self, tmp_path):
        """The retry after a failed pin must fail closed too.

        The pin used to survive in memory, so the very next request was served
        as "already trusted" on trust recorded nowhere -- and after a restart
        the host was trusted on first use all over again, which is exactly the
        window the fail-closed error exists to deny.
        """
        manager = self._manager(tmp_path)
        with self._store_that_refuses_writes():
            with pytest.raises(TOFUStorageError):
                manager.validate_certificate("example.com", 1965, "ab" * 32)

            assert "example.com:1965" not in manager._entries

            with pytest.raises(TOFUStorageError):
                manager.validate_certificate("example.com", 1965, "ab" * 32)

        # And once the store is usable again the pin is genuinely recorded,
        # rather than being throttled out for another SAVE_THROTTLE_SECONDS.
        is_valid, warning = manager.validate_certificate("example.com", 1965, "ab" * 32)
        assert is_valid is True
        assert warning is not None and "trusted on first use" in warning
        on_disk = json.loads(Path(manager.storage_path).read_text())
        assert on_disk["example.com:1965"]["fingerprint"] == "ab" * 32

    def test_failed_pin_change_leaves_the_previous_pin_in_place(self, tmp_path):
        """A rejected gemini_trust_update must not change trust in memory either."""
        manager = self._manager(tmp_path)
        manager._entries["example.com:1965"] = TOFUEntry(
            host="example.com",
            port=1965,
            fingerprint="aa" * 32,
            first_seen=1.0,
            last_seen=1.0,
        )
        with self._store_that_refuses_writes():
            with pytest.raises(TOFUStorageError):
                manager.update_certificate("example.com", 1965, "bb" * 32, force=True)

        assert manager._entries["example.com:1965"].fingerprint == "aa" * 32

    def test_failed_pin_removal_keeps_the_pin(self, tmp_path):
        """A removal reported as failed must leave the host still pinned.

        Dropping it from memory anyway would let the next fetch trust-on-first-
        use whatever that host now presents, which is the opposite of what the
        error told the operator.
        """
        manager = self._manager(tmp_path)
        manager._entries["example.com:1965"] = TOFUEntry(
            host="example.com",
            port=1965,
            fingerprint="aa" * 32,
            first_seen=1.0,
            last_seen=1.0,
        )
        with self._store_that_refuses_writes():
            with pytest.raises(TOFUStorageError):
                manager.remove_certificate("example.com", 1965)

        assert "example.com:1965" in manager._entries


class TestCertInfoParsingFallbacks:
    """``cert_info`` comes off the wire, so both expiry fields must degrade to
    "unknown" rather than raising.

    A live connection supplies the DER-derived ``not_after_timestamp`` /
    ``not_before_timestamp``; the ``notAfter`` / ``notBefore`` *strings* are the
    getpeercert()-shaped fallback kept for compatibility. Every one of these
    arms returns None on bad input on purpose: an unreadable expiry must leave
    the pin unstamped, never break the handshake.
    """

    def test_a_non_numeric_not_after_timestamp_reads_as_unknown(self):
        assert _parse_expiry({"not_after_timestamp": "soon"}) is None

    def test_a_non_numeric_not_before_timestamp_reads_as_unknown(self):
        assert _parse_not_before({"not_before_timestamp": "yesterday"}) is None

    def test_the_not_before_string_fallback_is_parsed(self):
        """The getpeercert() spelling, for a peer whose DER we never parsed."""
        parsed = _parse_not_before({"notBefore": "Jan  1 00:00:00 2020 GMT"})
        assert parsed == datetime(2020, 1, 1, tzinfo=UTC).timestamp()

    def test_an_unparseable_not_before_string_reads_as_unknown(self):
        assert _parse_not_before({"notBefore": "whenever"}) is None

    def test_a_not_yet_valid_certificate_is_refused_from_the_string_form(self):
        """The fallback must reach the fail-closed check, not just parse: a
        certificate dated in the future is refused however its notBefore was
        spelled."""
        future = datetime.now(UTC) + timedelta(days=30)
        cert_info = {"notBefore": future.strftime("%b %d %H:%M:%S %Y GMT")}
        with tempfile.TemporaryDirectory() as temp_dir:
            manager = TOFUManager(str(Path(temp_dir) / "tofu.json"))
            with pytest.raises(TOFUNotYetValidError):
                manager.validate_certificate("example.com", 1965, "ab" * 32, cert_info)


class TestUnreadableStoreDoesNotLoseInMemoryPins:
    """``_read_disk_entries`` deliberately does NOT fail closed.

    It exists only to merge concurrent on-disk changes before an atomic write.
    Failing closed there would let a transiently corrupt file block persisting
    good in-memory state forever; instead the bad file is ignored and the next
    write repairs it. (Startup, in ``_load_entries``, still fails closed -- that
    is the arm where trusting a damaged store would matter.)
    """

    def test_a_corrupt_store_is_ignored_and_rewritten(self, tmp_path):
        store = tmp_path / "tofu.json"
        manager = TOFUManager(str(store))
        manager.update_certificate("first.example", 1965, "aa" * 32, force=True)
        assert json.loads(store.read_text())["first.example:1965"]

        # Something outside this process mangles the file between our writes.
        store.write_text("{not json at all")

        manager.update_certificate("second.example", 1965, "bb" * 32, force=True)

        on_disk = json.loads(store.read_text())
        # Both pins survive: the unreadable disk copy contributed nothing to the
        # merge, and our own entries were written over it.
        assert on_disk["first.example:1965"]["fingerprint"] == "aa" * 32
        assert on_disk["second.example:1965"]["fingerprint"] == "bb" * 32

    def test_an_entry_the_file_cannot_model_is_ignored_too(self, tmp_path):
        """Valid JSON whose values are not TOFU entries takes the same arm --
        the ``TOFUEntry(**val)`` construction is inside the guarded block."""
        store = tmp_path / "tofu.json"
        manager = TOFUManager(str(store))
        manager.update_certificate("first.example", 1965, "aa" * 32, force=True)

        store.write_text(json.dumps({"first.example:1965": {"nonsense": True}}))
        manager.update_certificate("second.example", 1965, "bb" * 32, force=True)

        on_disk = json.loads(store.read_text())
        assert on_disk["first.example:1965"]["fingerprint"] == "aa" * 32
        assert on_disk["second.example:1965"]["fingerprint"] == "bb" * 32
