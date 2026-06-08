"""Trust-on-First-Use (TOFU) certificate validation for Gemini protocol."""

import contextlib
import hmac
import json
import os
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import structlog

from .models import TOFUEntry
from .ssrf import normalize_host
from .utils import atomic_write_json, get_home_directory

# fcntl is POSIX-only. The explicit ``ModuleType | None`` annotation keeps the
# ``is None`` guard reachable under mypy's warn_unreachable (the import always
# succeeds on POSIX, so without it mypy would treat the None branch as dead).
fcntl: ModuleType | None
try:
    import fcntl  # POSIX-only advisory file locking
except ImportError:  # pragma: no cover - non-POSIX (e.g. Windows)
    fcntl = None

logger = structlog.get_logger(__name__)

# Minimum seconds between best-effort last_seen flushes to disk. A new pin or a
# fingerprint change always persists immediately; only the read-path last_seen
# touch is throttled.
SAVE_THROTTLE_SECONDS = 60.0


def _canon_fingerprint(fingerprint: str) -> str:
    """Canonicalize a SHA-256 certificate fingerprint to one comparable form.

    The wire path always produces ``hashlib.sha256(...).hexdigest()`` (lowercase,
    no separators), but users pin certs by pasting the conventional
    ``openssl x509 -fingerprint`` / browser form (``sha256:AB:CD:...`` or
    ``AB:CD:...``). Storing those verbatim makes the constant-time compare never
    match, turning the user's own pin into a permanent CERTIFICATE_CHANGED
    denial. Normalize both stored and presented fingerprints through here so the
    representation can never cause a spurious mismatch.
    """
    fingerprint = fingerprint.strip()
    if fingerprint.lower().startswith("sha256:"):
        fingerprint = fingerprint[7:]
    return fingerprint.replace(":", "").lower()


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


def _parse_not_before(cert_info: dict[str, Any] | None) -> float | None:
    """Extract a certificate's notBefore (UNIX timestamp) from cert info.

    Mirrors :func:`_parse_expiry`; the gemini_tls layer parses the DER under
    CERT_NONE, so ``not_before_timestamp`` is the authoritative source.
    """
    if not cert_info:
        return None
    if "not_before_timestamp" in cert_info:
        try:
            return float(cert_info["not_before_timestamp"])
        except (TypeError, ValueError):
            return None
    if "notBefore" in cert_info:
        try:
            return (
                datetime.strptime(cert_info["notBefore"], "%b %d %H:%M:%S %Y %Z")
                .replace(tzinfo=UTC)
                .timestamp()
            )
        except ValueError:
            logger.warning(
                "Failed to parse certificate notBefore",
                not_before=cert_info["notBefore"],
            )
            return None
    return None


class TOFUValidationError(Exception):
    """Exception raised for TOFU validation failures."""

    def __init__(self, message: str, entry: TOFUEntry | None = None):
        super().__init__(message)
        self.entry = entry


class TOFUExpiredError(TOFUValidationError):
    """A certificate is outside its validity window (expired / not yet valid).

    A *distinct* subclass so callers can report this accurately: the cert still
    matches the pinned fingerprint, so surfacing it as a generic
    "certificate changed / does not match" would wrongly imply a key rotation or
    MITM and send an operator chasing a phantom. Only raised when
    ``reject_expired`` is enabled.
    """


class TOFUManager:
    """Trust-on-First-Use certificate validation manager."""

    def __init__(
        self, storage_path: str | None = None, *, reject_expired: bool = False
    ):
        """Initialize TOFU manager.

        Args:
            storage_path: Path to TOFU storage file (default: ~/.gemini/tofu.json)
            reject_expired: When True, a certificate outside its validity window
                (already expired, or not yet valid on first use) fails CLOSED
                instead of being accepted with a warning. Defaults to False to
                preserve the conventional Gemini TOFU behaviour where the
                fingerprint pin -- not the validity window -- is the real
                authenticator.
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
        self.reject_expired = reject_expired
        self._entries: dict[str, TOFUEntry] = {}
        # Throttle best-effort last_seen flushes (see validate_certificate).
        self._last_save_time = 0.0
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
            # Canonicalize any legacy / hand-edited fingerprints so a store
            # written before normalization (or edited by a human in colon form)
            # still matches the wire digest.
            for entry in entries.values():
                entry.fingerprint = _canon_fingerprint(entry.fingerprint)
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

    @contextlib.contextmanager
    def _store_lock(self) -> Iterator[None]:
        """Best-effort exclusive cross-process lock around a store mutation.

        Serializes the read-merge-write cycle so two server instances sharing
        the same store file can't lose each other's pins. A no-op where
        ``fcntl`` is unavailable (e.g. Windows): the atomic rename still
        prevents torn files there; only the cross-process merge guarantee is
        relaxed.
        """
        if fcntl is None:  # pragma: no cover - exercised only on non-POSIX
            yield
            return
        lock = fcntl  # local so mypy narrows ModuleType | None -> ModuleType
        lock_path = self.storage_path + ".lock"
        Path(lock_path).parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            lock.flock(fd, lock.LOCK_EX)
            yield
        finally:
            with contextlib.suppress(OSError):
                lock.flock(fd, lock.LOCK_UN)
            os.close(fd)

    def _read_disk_entries(self) -> dict[str, TOFUEntry]:
        """Read the current on-disk entries (canonicalized) for merging.

        Returns ``{}`` if the file is missing or unreadable. Unlike
        :meth:`_load_entries` this does NOT fail closed: a transiently bad file
        must not block persisting our good in-memory state (the next write
        repairs it). Startup fail-closed behaviour is unchanged.
        """
        path = Path(self.storage_path)
        if not path.exists():
            return {}
        try:
            with path.open(encoding="utf-8") as f:
                data = json.load(f)
            entries = {key: TOFUEntry(**val) for key, val in data.items()}
        except Exception as e:
            logger.warning("Ignoring unreadable TOFU store during merge", error=str(e))
            return {}
        for entry in entries.values():
            entry.fingerprint = _canon_fingerprint(entry.fingerprint)
        return entries

    def _save_entries(self, *, removed_keys: set[str] | None = None) -> None:
        """Persist entries, merging with concurrent on-disk changes.

        Holds an exclusive cross-process lock while it re-reads the store,
        unions it with our in-memory entries (ours win for shared keys), drops
        any keys this operation explicitly removed, then atomically writes. This
        keeps a second instance from silently clobbering a pin we just wrote
        (and vice versa). ``removed_keys`` must be passed for deletions so the
        merge doesn't resurrect them from disk.
        """
        try:
            with self._store_lock():
                merged = {**self._read_disk_entries(), **self._entries}
                if removed_keys:
                    for key in removed_keys:
                        merged.pop(key, None)
                self._entries = merged

                data = {key: entry.model_dump() for key, entry in merged.items()}
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

        # Normalize to one canonical form so a colon/uppercase representation
        # can never cause a spurious mismatch against the wire digest.
        cert_fingerprint = _canon_fingerprint(cert_fingerprint)

        existing_entry = self._entries.get(key)

        if existing_entry is None:
            # First time seeing this host:port - trust on first use
            expires = _parse_expiry(cert_info)
            not_before = _parse_not_before(cert_info)

            # A cert outside its validity window on first contact is a strong
            # signal something is off. The fingerprint pin is fixed for the
            # life of the cert (same fingerprint == same cert), so checking the
            # window once, here, covers every subsequent connection.
            window_problem: str | None = None
            if expires is not None and expires < current_time:
                window_problem = "already expired"
            elif not_before is not None and not_before > current_time:
                window_problem = "not yet valid"

            if window_problem and self.reject_expired:
                logger.warning(
                    "Refusing to pin certificate outside its validity window",
                    host=host,
                    port=port,
                    problem=window_problem,
                )
                raise TOFUExpiredError(
                    f"Certificate for {host}:{port} is {window_problem}; refusing "
                    "to trust on first use (reject_expired is enabled)"
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
            self._last_save_time = current_time

            logger.info(
                "New certificate trusted (TOFU)",
                host=host,
                port=port,
                fingerprint=cert_fingerprint[:16] + "...",
            )

            message = f"New certificate for {host}:{port} trusted on first use"
            if window_problem:
                message += f" (warning: certificate is {window_problem})"
                logger.warning(
                    "First-use certificate is outside its validity window",
                    host=host,
                    port=port,
                    problem=window_problem,
                )
            return True, message

        else:
            # Check if certificate has changed (constant-time comparison)
            if not hmac.compare_digest(existing_entry.fingerprint, cert_fingerprint):
                # Certificate has changed - this is a security concern
                warning = (
                    f"Certificate for {host}:{port} has changed!\n"
                    f"Previous: {existing_entry.fingerprint[:16]}...\n"
                    f"Current:  {cert_fingerprint[:16]}...\n"
                    f"First seen: {datetime.fromtimestamp(existing_entry.first_seen, tz=UTC)}\n"
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

            # Certificate matches - update last seen time. This is NOT a
            # security-relevant change, so don't rewrite the whole trust store on
            # every request (I/O amplification under batch/polling load); flush
            # at most once per SAVE_THROTTLE_SECONDS.
            existing_entry.last_seen = current_time
            if current_time - self._last_save_time >= SAVE_THROTTLE_SECONDS:
                self._save_entries()
                self._last_save_time = current_time

            # Check if certificate is expired. By default this is advisory only
            # (the fingerprint pin is the real authenticator under TOFU); a
            # deployment can opt into fail-closed via reject_expired.
            if existing_entry.is_expired(current_time):
                warning = f"Certificate for {host}:{port} has expired"
                logger.warning("Certificate expired", host=host, port=port)
                if self.reject_expired:
                    raise TOFUExpiredError(warning, existing_entry)
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

        # Normalize to one canonical form (see _canon_fingerprint).
        cert_fingerprint = _canon_fingerprint(cert_fingerprint)

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
            # Pass the removed key so the merge-with-disk step doesn't resurrect
            # it from a stale on-disk copy.
            self._save_entries(removed_keys={key})

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
            self._save_entries(removed_keys=set(expired_keys))
            logger.info("Expired certificates removed", count=len(expired_keys))

        return len(expired_keys)
