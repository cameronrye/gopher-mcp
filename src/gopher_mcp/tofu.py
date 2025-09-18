"""Trust-on-First-Use (TOFU) certificate validation for Gemini protocol."""

import json
import os
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime

import structlog

from .models import TOFUEntry

logger = structlog.get_logger(__name__)


class TOFUValidationError(Exception):
    """Exception raised for TOFU validation failures."""

    def __init__(self, message: str, entry: Optional[TOFUEntry] = None):
        super().__init__(message)
        self.entry = entry


class TOFUManager:
    """Trust-on-First-Use certificate validation manager."""

    def __init__(self, storage_path: Optional[str] = None):
        """Initialize TOFU manager.

        Args:
            storage_path: Path to TOFU storage file (default: ~/.gemini/tofu.json)
        """
        if storage_path is None:
            home_dir = Path.home()
            gemini_dir = home_dir / ".gemini"
            gemini_dir.mkdir(exist_ok=True)
            storage_path = str(gemini_dir / "tofu.json")

        self.storage_path = storage_path
        self._entries: Dict[str, TOFUEntry] = {}
        self._load_entries()

    def _get_key(self, host: str, port: int) -> str:
        """Get storage key for host:port combination."""
        return f"{host}:{port}"

    def _load_entries(self) -> None:
        """Load TOFU entries from storage."""
        try:
            if os.path.exists(self.storage_path):
                with open(self.storage_path, "r") as f:
                    data = json.load(f)
                    for key, entry_data in data.items():
                        self._entries[key] = TOFUEntry(**entry_data)
                logger.info(
                    "TOFU entries loaded",
                    count=len(self._entries),
                    storage_path=self.storage_path,
                )
            else:
                logger.info("No existing TOFU storage found, starting fresh")
        except Exception as e:
            logger.error("Failed to load TOFU entries", error=str(e))
            self._entries = {}

    def _save_entries(self) -> None:
        """Save TOFU entries to storage."""
        try:
            # Ensure directory exists
            os.makedirs(os.path.dirname(self.storage_path), exist_ok=True)

            # Convert entries to dict for JSON serialization
            data = {}
            for key, entry in self._entries.items():
                data[key] = entry.model_dump()

            # Write to temporary file first, then rename for atomicity
            temp_path = self.storage_path + ".tmp"
            with open(temp_path, "w") as f:
                json.dump(data, f, indent=2)

            os.rename(temp_path, self.storage_path)

            logger.debug("TOFU entries saved", count=len(self._entries))
        except Exception as e:
            logger.error("Failed to save TOFU entries", error=str(e))
            raise

    def validate_certificate(
        self,
        host: str,
        port: int,
        cert_fingerprint: str,
        cert_info: Optional[Dict[str, Any]] = None,
    ) -> Tuple[bool, Optional[str]]:
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
            expires = None
            if cert_info and "notAfter" in cert_info:
                try:
                    # Parse certificate expiry
                    expires = datetime.strptime(
                        cert_info["notAfter"], "%b %d %H:%M:%S %Y %Z"
                    ).timestamp()
                except ValueError:
                    logger.warning(
                        "Failed to parse certificate expiry",
                        not_after=cert_info["notAfter"],
                    )

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
            # Check if certificate has changed
            if existing_entry.fingerprint != cert_fingerprint:
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
        cert_info: Optional[Dict[str, Any]] = None,
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
        expires = None
        if cert_info and "notAfter" in cert_info:
            try:
                expires = datetime.strptime(
                    cert_info["notAfter"], "%b %d %H:%M:%S %Y %Z"
                ).timestamp()
            except ValueError:
                pass

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

    def list_certificates(self) -> List[TOFUEntry]:
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
