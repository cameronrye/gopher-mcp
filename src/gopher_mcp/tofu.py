"""Trust-on-First-Use (TOFU) certificate validation for Gemini protocol."""

import contextlib
import hmac
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import structlog

from .models import TOFUEntry
from .ssrf import normalize_host
from .utils import atomic_write_json, get_home_directory

logger = structlog.get_logger(__name__)


def _parse_expiry(cert_info: dict[str, Any] | None) -> float | None:
    """Extract a certificate expiry (UNIX timestamp) from cert info.

    Prefers ``not_after_timestamp`` (parsed from the DER by gemini_tls, which
    works under CERT_NONE where getpeercert() is empty), and falls back to the
    getpeercert-style ``notAfter`` string for backward compatibility.
    """
    if not cert_info:
        return None
    if "not_after_timestamp" in cert_info:
        try:
            return float(cert_info["not_after_timestamp"])
        except (TypeError, ValueError):
            return None
    if "notAfter" in cert_info:
        try:
            return (
                datetime.strptime(cert_info["notAfter"], "%b %d %H:%M:%S %Y %Z")
                .replace(tzinfo=UTC)
                .timestamp()
            )
        except ValueError:
            logger.warning(
                "Failed to parse certificate expiry", not_after=cert_info["notAfter"]
            )
            return None
    return None


class TOFUValidationError(Exception):
    """Exception raised for TOFU validation failures."""

    def __init__(self, message: str, entry: TOFUEntry | None = None):
        super().__init__(message)
        self.entry = entry


class TOFUManager:
    """Trust-on-First-Use certificate validation manager."""

    def __init__(self, storage_path: str | None = None):
        """Initialize TOFU manager.

        Args:
            storage_path: Path to TOFU storage file (default: ~/.gemini/tofu.json)
        """
        if storage_path is None:
            home_dir = get_home_directory()
            if home_dir is None:
                raise ValueError("Could not determine home directory")
            gemini_dir = home_dir / ".gemini"
            gemini_dir.mkdir(exist_ok=True)
            # The trust store lives here; keep it owner-only (mkdir mode is
            # subject to umask).
            with contextlib.suppress(OSError):  # non-POSIX or restricted FS
                gemini_dir.chmod(0o700)
            storage_path = str(gemini_dir / "tofu.json")

        self.storage_path = storage_path
        self._entries: dict[str, TOFUEntry] = {}
        self._load_entries()

    def _get_key(self, host: str, port: int) -> str:
        """Get storage key for host:port combination.

        The host is normalized (lowercased, trailing dot / IPv6 brackets
        stripped) so ``Example.com``, ``example.com`` and ``example.com.`` map
        to a single pin -- otherwise a casing/trailing-dot variant would get a
        fresh trust-on-first-use and silently bypass the established pin.
        """
        return f"{normalize_host(host)}:{port}"

    def _load_entries(self) -> None:
        """Load TOFU entries from storage.

        Fails CLOSED: if the store exists but is corrupt/unparseable, we raise
        rather than silently resetting to an empty trust store, which would
        re-arm blind trust-on-first-use for every previously pinned host. A
        missing file is the legitimate first-run case and starts empty.
        """
        if not Path(self.storage_path).exists():
            logger.info("No existing TOFU storage found, starting fresh")
            return

        try:
            with Path(self.storage_path).open(encoding="utf-8") as f:
                data = json.load(f)
            entries = {key: TOFUEntry(**entry_data) for key, entry_data in data.items()}
        except Exception as e:
            logger.error("TOFU storage is corrupt or unreadable", error=str(e))
            raise TOFUValidationError(
                f"TOFU storage at {self.storage_path} is corrupt; refusing to "
                "start with an empty trust store (fix or remove the file)"
            ) from e

        self._entries = entries
        logger.info(
            "TOFU entries loaded",
            count=len(self._entries),
            storage_path=self.storage_path,
        )

    def _save_entries(self) -> None:
        """Save TOFU entries to storage."""
        try:
            # Convert entries to dict for JSON serialization
            data = {}
            for key, entry in self._entries.items():
                data[key] = entry.model_dump()

            # Use atomic write function
            atomic_write_json(self.storage_path, data)

            logger.debug("TOFU entries saved", count=len(self._entries))
        except Exception as e:
            logger.error("Failed to save TOFU entries", error=str(e))
            raise

    def validate_certificate(
        self,
        host: str,
        port: int,
        cert_fingerprint: str,
        cert_info: dict[str, Any] | None = None,
    ) -> tuple[bool, str | None]:
        """Validate certificate using TOFU.

        Args:
            host: Hostname
            port: Port number
            cert_fingerprint: Certificate SHA-256 fingerprint
            cert_info: Additional certificate information

        Returns:
            Tuple of (is_valid, warning_message)

        Raises:
            TOFUValidationError: If validation fails critically
        """
        key = self._get_key(host, port)
        current_time = time.time()

        # Clean fingerprint format (remove sha256: prefix if present)
        if cert_fingerprint.startswith("sha256:"):
            cert_fingerprint = cert_fingerprint[7:]

        existing_entry = self._entries.get(key)

        if existing_entry is None:
            # First time seeing this host:port - trust on first use
            expires = _parse_expiry(cert_info)

            new_entry = TOFUEntry(
                host=host,
                port=port,
                fingerprint=cert_fingerprint,
                first_seen=current_time,
                last_seen=current_time,
                expires=expires,
            )

            self._entries[key] = new_entry
            self._save_entries()

            logger.info(
                "New certificate trusted (TOFU)",
                host=host,
                port=port,
                fingerprint=cert_fingerprint[:16] + "...",
            )

            return True, f"New certificate for {host}:{port} trusted on first use"

        else:
            # Check if certificate has changed (constant-time comparison)
            if not hmac.compare_digest(existing_entry.fingerprint, cert_fingerprint):
                # Certificate has changed - this is a security concern
                warning = (
                    f"Certificate for {host}:{port} has changed!\n"
                    f"Previous: {existing_entry.fingerprint[:16]}...\n"
                    f"Current:  {cert_fingerprint[:16]}...\n"
                    f"First seen: {datetime.fromtimestamp(existing_entry.first_seen)}\n"
                    f"This could indicate a security issue."
                )

                logger.warning(
                    "Certificate fingerprint mismatch",
                    host=host,
                    port=port,
                    old_fingerprint=existing_entry.fingerprint[:16] + "...",
                    new_fingerprint=cert_fingerprint[:16] + "...",
                    first_seen=existing_entry.first_seen,
                )

                raise TOFUValidationError(warning, existing_entry)

            # Certificate matches - update last seen time
            existing_entry.last_seen = current_time
            self._save_entries()

            # Check if certificate is expired
            if existing_entry.is_expired(current_time):
                warning = f"Certificate for {host}:{port} has expired"
                logger.warning("Certificate expired", host=host, port=port)
                return True, warning

            logger.debug(
                "Certificate validated (TOFU)",
                host=host,
                port=port,
                fingerprint=cert_fingerprint[:16] + "...",
            )

            return True, None

    def update_certificate(
        self,
        host: str,
        port: int,
        cert_fingerprint: str,
        cert_info: dict[str, Any] | None = None,
        force: bool = False,
    ) -> None:
        """Update stored certificate for a host.

        Args:
            host: Hostname
            port: Port number
            cert_fingerprint: New certificate fingerprint
            cert_info: Certificate information
            force: Force update even if certificate exists

        Raises:
            TOFUValidationError: If update is not allowed
        """
        key = self._get_key(host, port)
        current_time = time.time()

        # Clean fingerprint format
        if cert_fingerprint.startswith("sha256:"):
            cert_fingerprint = cert_fingerprint[7:]

        existing_entry = self._entries.get(key)

        if existing_entry and not force:
            raise TOFUValidationError(
                f"Certificate for {host}:{port} already exists. Use force=True to override."
            )

        # Parse expiry if available
        expires = _parse_expiry(cert_info)

        # Create or update entry
        if existing_entry:
            existing_entry.fingerprint = cert_fingerprint
            existing_entry.last_seen = current_time
            existing_entry.expires = expires
        else:
            self._entries[key] = TOFUEntry(
                host=host,
                port=port,
                fingerprint=cert_fingerprint,
                first_seen=current_time,
                last_seen=current_time,
                expires=expires,
            )

        self._save_entries()

        logger.info(
            "Certificate updated",
            host=host,
            port=port,
            fingerprint=cert_fingerprint[:16] + "...",
            forced=force,
        )

    def remove_certificate(self, host: str, port: int) -> bool:
        """Remove stored certificate for a host.

        Args:
            host: Hostname
            port: Port number

        Returns:
            True if certificate was removed, False if not found
        """
        key = self._get_key(host, port)

        if key in self._entries:
            del self._entries[key]
            self._save_entries()

            logger.info("Certificate removed", host=host, port=port)
            return True

        return False

    def list_certificates(self) -> list[TOFUEntry]:
        """List all stored certificates.

        Returns:
            List of TOFU entries
        """
        return list(self._entries.values())

    def cleanup_expired(self) -> int:
        """Remove expired certificates.

        Returns:
            Number of certificates removed
        """
        current_time = time.time()
        expired_keys = []

        for key, entry in self._entries.items():
            if entry.is_expired(current_time):
                expired_keys.append(key)

        for key in expired_keys:
            del self._entries[key]

        if expired_keys:
            self._save_entries()
            logger.info("Expired certificates removed", count=len(expired_keys))

        return len(expired_keys)
