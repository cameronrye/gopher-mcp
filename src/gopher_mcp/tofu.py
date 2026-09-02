"""Trust-on-First-Use (TOFU) certificate validation for Gemini protocol."""

import contextlib
import hmac
import json
import os
import sys
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

import structlog

from .helpers import atomic_write_json, get_home_directory
from .models import TOFUEntry
from .ssrf import normalize_host

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

# Bounded wait for the cross-process store lock. ``flock(LOCK_EX)`` has no
# timeout, so a second instance that wedged while holding the store's ``.lock``
# file would block this one forever with no error at all; poll with LOCK_NB
# instead and fail loudly once the budget is spent.
LOCK_TIMEOUT_SECONDS = 5.0
LOCK_POLL_INTERVAL_SECONDS = 0.05

# How far a certificate's notBefore may sit in the future before first contact
# is refused. Gemini capsules routinely mint a self-signed certificate at
# startup with notBefore = now, so a server clock a few seconds ahead of ours
# would otherwise hard-fail the very first connection -- and keep failing until
# wall time caught up, since nothing gets pinned. Small enough that a
# genuinely premature certificate (the MITM signal this check exists for) is
# still refused.
NOT_BEFORE_SKEW_SECONDS = 300.0

# The directory gopher-mcp keeps its own state in, under whichever per-user
# data location the platform uses.
STATE_DIR_NAME = "gopher-mcp"

# Where the trust store and client identities lived before gopher-mcp had a
# directory of its own. ``~/.gemini`` belongs to Google's Gemini CLI -- it holds
# the ``settings.json`` a user edits to register this very server -- so
# creating it, tightening its mode and dropping generically named state into it
# reached into another product's configuration directory. New installs no
# longer touch it, but a store already there keeps being read and written in
# place, permanently and with no deprecation window: relocating a trust store
# behind the user's back would either lose every pin or make a pinned host look
# unpinned, which is precisely the blind trust-on-first-use the store exists to
# prevent.
LEGACY_STATE_DIR_NAME = ".gemini"


def default_state_directory() -> Path | None:
    """Resolve the per-user data directory gopher-mcp stores state in.

    ``XDG_DATA_HOME`` wins wherever it names an absolute path -- Linux
    packagers, and anyone who has deliberately moved their data directory,
    expect it honoured rather than second-guessed. Otherwise the platform
    convention applies.

    Returns:
        The directory, which is NOT created here, or None when neither an
        absolute ``XDG_DATA_HOME`` nor a home directory could be determined.
    """
    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home and Path(xdg_data_home).is_absolute():
        return Path(xdg_data_home) / STATE_DIR_NAME

    # Read through a variable: mypy folds a direct ``sys.platform ==`` test to
    # the platform it is running on, which under warn_unreachable would make
    # every branch but the host's dead code and leave it unchecked.
    platform_name: str = sys.platform

    if platform_name.startswith("win"):  # pragma: no cover - POSIX-only CI
        app_data = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if app_data:
            return Path(app_data) / STATE_DIR_NAME

    home_dir = get_home_directory()
    if home_dir is None:
        return None
    if platform_name.startswith("win"):  # pragma: no cover - POSIX-only CI
        return home_dir / "AppData" / "Local" / STATE_DIR_NAME
    if platform_name == "darwin":
        return home_dir / "Library" / "Application Support" / STATE_DIR_NAME
    return home_dir / ".local" / "share" / STATE_DIR_NAME


def legacy_state_path(name: str) -> Path | None:
    """Return ``~/.gemini/<name>`` when it is already on disk, else None.

    Only ever reports state that exists: this is the upgrade path for installs
    that pinned certificates or minted client identities before gopher-mcp had
    a directory of its own, never a place to create something new.
    """
    home_dir = get_home_directory()
    if home_dir is None:
        return None
    legacy = home_dir / LEGACY_STATE_DIR_NAME / name
    try:
        return legacy if legacy.exists() else None
    except OSError:  # pragma: no cover - unreadable home; treat as absent
        return None


def canonicalize_fingerprint(fingerprint: str) -> str:
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


class TOFUStorageError(Exception):
    """The trust store could not be locked or written.

    Deliberately NOT a :class:`TOFUValidationError`: the certificate itself was
    never in question, we simply could not record or refresh the pin. Raised
    rather than swallowed so a wedged lock holder is visible instead of silently
    turning persistence off (which would re-arm blind trust-on-first-use).

    Deliberately NOT an ``OSError`` either, even though a failed write is where
    most of these come from. An OSError escaping the trust store is caught by
    the robots probe's blanket transport handler upstream, which reports a
    read-only disk or a misdirected GEMINI_TOFU_STORAGE_PATH as an unreachable
    capsule and tells the caller to retry shortly -- retry-forever advice for a
    permanent local fault.
    """


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


class TOFUNotYetValidError(TOFUExpiredError):
    """A certificate was presented before its notBefore, beyond clock skew.

    A subclass of :class:`TOFUExpiredError` so a caller that only knows about
    the expiry case keeps behaving as it did, but distinct so one that cares can
    say what actually happened: reporting "not yet valid" as an expiry inverts
    the diagnosis, and an operator told the certificate expired will go looking
    for a renewal that is not the problem.
    """


class TOFUUnavailableError(TOFUValidationError):
    """No usable certificate was available to apply the TOFU pin.

    Distinct from a fingerprint *mismatch*: there is nothing to compare against
    (the TLS layer yielded no peer certificate fingerprint), so reporting it as
    "certificate changed / does not match" would be misleading. The connection
    is still refused (fail closed) -- the peer simply can't be authenticated.
    """


class TOFUManager:
    """Trust-on-First-Use certificate validation manager."""

    def __init__(
        self, storage_path: str | None = None, *, reject_expired: bool = False
    ):
        """Initialize TOFU manager.

        Args:
            storage_path: Path to TOFU storage file. Defaults to
                ``tofu.json`` under :func:`default_state_directory`, or to an
                existing legacy ``~/.gemini/tofu.json`` when one is present.
            reject_expired: When True, a certificate outside its validity window
                (already expired, or not yet valid on first use) fails CLOSED
                instead of being accepted with a warning. Defaults to False to
                preserve the conventional Gemini TOFU behaviour where the
                fingerprint pin -- not the validity window -- is the real
                authenticator.
        """
        if storage_path is None:
            storage_path = str(self._default_storage_path())

        self.storage_path = storage_path
        self.reject_expired = reject_expired
        self._entries: dict[str, TOFUEntry] = {}
        # Throttle best-effort last_seen flushes (see validate_certificate).
        self._last_save_time = 0.0
        # The Gemini client runs validate_certificate under asyncio.to_thread
        # (the load-merge-write cycle blocks), so two requests can now be inside
        # this manager at once. Reentrant because the mutators call _save_entries.
        self._lock = threading.RLock()
        self._load_entries()

    @staticmethod
    def _default_storage_path() -> Path:
        """Pick the trust store location for an install that named none.

        An existing ``~/.gemini/tofu.json`` keeps being used exactly where it
        is -- silently moving pins would lose them or, worse, make a pinned
        host look unpinned. Anything else lands in gopher-mcp's own data
        directory, which is created owner-only here (mkdir's mode is subject to
        umask, and the file records who we trust).

        Raises:
            ValueError: If no storage location can be determined.
            TOFUStorageError: If the state directory cannot be created.
        """
        legacy = legacy_state_path("tofu.json")
        if legacy is not None:
            return legacy

        state_dir = default_state_directory()
        if state_dir is None:
            raise ValueError("Could not determine home directory")
        try:
            state_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise TOFUStorageError(
                f"Could not create the TOFU trust store directory at {state_dir}: {e}"
            ) from e
        with contextlib.suppress(OSError):  # non-POSIX or restricted FS
            state_dir.chmod(0o700)
        return state_dir / "tofu.json"

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
                entry.fingerprint = canonicalize_fingerprint(entry.fingerprint)
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

        Raises:
            TOFUStorageError: If the lock is still held after
                ``LOCK_TIMEOUT_SECONDS``.
        """
        if fcntl is None:  # pragma: no cover - exercised only on non-POSIX
            yield
            return
        lock = fcntl  # local so mypy narrows ModuleType | None -> ModuleType
        lock_path = self.storage_path + ".lock"
        Path(lock_path).parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(lock_path, os.O_CREAT | os.O_RDWR, 0o600)
        try:
            deadline = time.monotonic() + LOCK_TIMEOUT_SECONDS
            while True:
                try:
                    lock.flock(fd, lock.LOCK_EX | lock.LOCK_NB)
                    break
                except OSError as e:
                    if time.monotonic() >= deadline:
                        raise TOFUStorageError(
                            f"Could not lock the TOFU trust store at {lock_path} "
                            f"within {LOCK_TIMEOUT_SECONDS} seconds; another "
                            f"process may be holding it"
                        ) from e
                    time.sleep(LOCK_POLL_INTERVAL_SECONDS)
            try:
                yield
            finally:
                with contextlib.suppress(OSError):
                    lock.flock(fd, lock.LOCK_UN)
        finally:
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
            entry.fingerprint = canonicalize_fingerprint(entry.fingerprint)
        return entries

    def _save_entries(self, *, removed_keys: set[str] | None = None) -> None:
        """Persist entries, merging with concurrent on-disk changes.

        Holds an exclusive cross-process lock while it re-reads the store,
        unions it with our in-memory entries (ours win for shared keys), drops
        any keys this operation explicitly removed, then atomically writes. This
        keeps a second instance from silently clobbering a pin we just wrote
        (and vice versa). ``removed_keys`` must be passed for deletions so the
        merge doesn't resurrect them from disk.

        Raises:
            TOFUStorageError: If the store could not be locked or written.
        """
        try:
            with self._lock, self._store_lock():
                merged = {**self._read_disk_entries(), **self._entries}
                if removed_keys:
                    for key in removed_keys:
                        merged.pop(key, None)
                self._entries = merged

                data = {key: entry.model_dump() for key, entry in merged.items()}
                atomic_write_json(self.storage_path, data)

            logger.debug("TOFU entries saved", count=len(self._entries))
        except TOFUStorageError:
            raise
        except OSError as e:
            # A read-only store, a full disk or a GEMINI_TOFU_STORAGE_PATH
            # pointing somewhere unwritable is a storage failure, not a
            # transport one -- see TOFUStorageError on why letting the raw
            # OSError out reported it to the caller as an unreachable capsule.
            logger.error(
                "Failed to save TOFU entries",
                error=str(e),
                storage_path=self.storage_path,
            )
            raise TOFUStorageError(
                f"Could not write the TOFU trust store at {self.storage_path}: {e}"
            ) from e
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
        # Serialized: the Gemini client runs this under asyncio.to_thread, so
        # two requests could otherwise interleave the read-modify-write of
        # ``_entries`` and the store merge behind it.
        with self._lock:
            return self._validate_certificate_locked(
                host, port, cert_fingerprint, cert_info
            )

    def _validate_certificate_locked(
        self,
        host: str,
        port: int,
        cert_fingerprint: str,
        cert_info: dict[str, Any] | None = None,
    ) -> tuple[bool, str | None]:
        """Body of :meth:`validate_certificate`; caller must hold ``_lock``."""
        key = self._get_key(host, port)
        current_time = time.time()

        # Normalize to one canonical form so a colon/uppercase representation
        # can never cause a spurious mismatch against the wire digest.
        cert_fingerprint = canonicalize_fingerprint(cert_fingerprint)

        existing_entry = self._entries.get(key)

        if existing_entry is None:
            # First time seeing this host:port - trust on first use
            expires = _parse_expiry(cert_info)
            not_before = _parse_not_before(cert_info)

            # A cert outside its validity window on first contact is a strong
            # signal something is off. The fingerprint pin is fixed for the
            # life of the cert (same fingerprint == same cert), so checking the
            # window once, here, covers every subsequent connection.
            #
            # A NOT-YET-VALID cert is refused unconditionally: a server has no
            # legitimate reason to present a cert before its notBefore, so this
            # is a strong active-MITM signal. The clock skew set aside there is
            # NOT rhetorical -- capsules mint their certificate at startup with
            # notBefore = now, so the comparison allows NOT_BEFORE_SKEW_SECONDS
            # of disagreement between the two clocks before failing. An ALREADY-
            # EXPIRED cert is only refused when reject_expired is set, since
            # briefly-lapsed certs are a known part of the Gemini ecosystem;
            # otherwise it is pinned with a warning.
            if (
                not_before is not None
                and not_before > current_time + NOT_BEFORE_SKEW_SECONDS
            ):
                logger.warning(
                    "Refusing to pin a not-yet-valid certificate",
                    host=host,
                    port=port,
                    not_before=not_before,
                )
                raise TOFUNotYetValidError(
                    f"Certificate for {host}:{port} is not yet valid (notBefore "
                    "is in the future); refusing to trust on first use"
                )

            window_problem: str | None = None
            if expires is not None and expires < current_time:
                window_problem = "already expired"
                if self.reject_expired:
                    logger.warning(
                        "Refusing to pin an expired certificate",
                        host=host,
                        port=port,
                    )
                    raise TOFUExpiredError(
                        f"Certificate for {host}:{port} is already expired; "
                        "refusing to trust on first use (reject_expired is "
                        "enabled)"
                    )

            new_entry = TOFUEntry(
                host=host,
                port=port,
                fingerprint=cert_fingerprint,
                first_seen=current_time,
                last_seen=current_time,
                expires=expires,
            )

            # Leave nothing behind if the pin cannot be recorded. The caller is
            # told the store is unavailable and fails closed -- but an entry
            # that survived only in memory would serve the very next retry as
            # "already trusted" on a pin written nowhere, and after a restart
            # the host is trusted on first use all over again. That is exactly
            # the window the fail-closed error exists to deny. Dropping it
            # instead sends the next request back through this branch, which
            # re-attempts the write.
            self._entries[key] = new_entry
            try:
                self._save_entries()
            except Exception:
                self._entries.pop(key, None)
                raise
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
                # Name the store and the entry: self-signed Gemini certificates
                # are routinely reissued at expiry, and without a stated
                # remedy a legitimate rotation bricks the host until someone
                # finds the JSON on disk and hand-edits it. Only the fingerprint
                # PREFIXES and the operator's own configured path appear here,
                # and the client replaces this text with a sanitized message
                # before it reaches a caller.
                warning = (
                    f"Certificate for {host}:{port} has changed!\n"
                    f"Previous: {existing_entry.fingerprint[:16]}...\n"
                    f"Current:  {cert_fingerprint[:16]}...\n"
                    f"First seen: {datetime.fromtimestamp(existing_entry.first_seen, tz=UTC)}\n"
                    f"This could indicate a security issue.\n"
                    f"If the rotation is expected, drop the pin with the "
                    f"gemini_trust_update tool (action='remove', host='{host}', "
                    f"port={port}, and the fingerprint gemini_trust_list "
                    f'reports) and reconnect; the "{key}" entry in the trust '
                    f"store at {self.storage_path} can also be removed by hand."
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
                # Best effort: last_seen is bookkeeping, not trust state, so a
                # store we cannot write right now must not fail an otherwise
                # valid request. This cannot mask an unrecorded pin: a new pin
                # (above) fails closed AND is dropped from memory, so it never
                # reaches this branch to be swallowed -- it re-enters the
                # first-use path and retries the write on the next request.
                # ``_last_save_time`` advances either way on purpose, so an
                # unwritable store costs one bounded lock wait per throttle
                # interval rather than one per request.
                try:
                    self._save_entries()
                except TOFUStorageError as e:
                    logger.warning(
                        "Could not refresh TOFU last_seen",
                        host=host,
                        port=port,
                        error=str(e),
                    )
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
        with self._lock:
            key = self._get_key(host, port)
            current_time = time.time()

            # Normalize to one canonical form (see canonicalize_fingerprint).
            cert_fingerprint = canonicalize_fingerprint(cert_fingerprint)

            existing_entry = self._entries.get(key)

            if existing_entry and not force:
                raise TOFUValidationError(
                    f"Certificate for {host}:{port} already exists. Use force=True to override."
                )

            # Parse expiry if available
            expires = _parse_expiry(cert_info)

            # Create or update entry. A copy of what was there is kept so a
            # failed persist can be undone: the caller is told the pin was not
            # changed, and an in-memory pin that contradicts that would decide
            # every request until the process restarts.
            previous = existing_entry.model_copy() if existing_entry else None
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

            try:
                self._save_entries()
            except Exception:
                if previous is None:
                    self._entries.pop(key, None)
                else:
                    self._entries[key] = previous
                raise

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
        with self._lock:
            key = self._get_key(host, port)

            if key not in self._entries:
                return False

            removed = self._entries.pop(key)
            # Pass the removed key so the merge-with-disk step doesn't resurrect
            # it from a stale on-disk copy. Put it back if the write fails: the
            # caller is told the pin still stands, and dropping it from memory
            # anyway would let the next fetch trust-on-first-use whatever that
            # host now presents.
            try:
                self._save_entries(removed_keys={key})
            except Exception:
                self._entries[key] = removed
                raise

        logger.info("Certificate removed", host=host, port=port)
        return True

    def list_certificates(self) -> list[TOFUEntry]:
        """List all stored certificates.

        Returns:
            List of TOFU entries
        """
        with self._lock:
            return list(self._entries.values())
