"""Client certificate management for Gemini protocol."""

import contextlib
import hashlib
import json
import os
import secrets
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import structlog
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from .models import GeminiCertificateInfo
from .tofu import default_state_directory, legacy_state_path
from .utils import atomic_write_json

logger = structlog.get_logger(__name__)


def _path_in_scope(path: str, scope: str) -> bool:
    """Return True if ``path`` falls within a certificate's ``scope`` path.

    Uses path-segment boundaries rather than a raw textual prefix: a cert
    scoped to ``/api`` covers ``/api`` and ``/api/v1`` but NOT siblings like
    ``/api_admin`` or ``/apixyz`` (which a naive ``startswith`` would wrongly
    match, leaking the client identity outside its declared scope). A scope
    already ending in ``/`` (notably the root ``/``) matches any path beneath
    it.
    """
    if path == scope:
        return True
    if scope.endswith("/"):
        return path.startswith(scope)
    return path.startswith(scope + "/")


class ClientCertificateError(Exception):
    """Exception raised for client certificate errors."""

    pass


class ClientCertificateStorageError(ClientCertificateError):
    """The certificate store could not be created, read or written.

    Distinct from a certificate problem: nothing was wrong with the identity,
    the store underneath it was simply unusable. Deliberately not an
    ``OSError`` -- one escaping this module is caught by a transport handler
    upstream and reported as an unreachable capsule, turning a read-only disk
    or a misdirected GEMINI_CLIENT_CERTS_STORAGE_PATH into retry-forever advice
    for a permanent local fault.
    """


class ClientCertificateKeyRetainedError(ClientCertificateError):
    """Raised when a removal completed but the private key file survived.

    The registry entry is gone -- the identity is no longer attached to any
    request -- yet the key itself is still at rest in the store, so a caller
    must not report the identity as destroyed.
    """


class ClientCertificateManager:
    """Manager for Gemini client certificates."""

    def __init__(self, storage_path: str | None = None):
        """Initialize client certificate manager.

        Args:
            storage_path: Path to certificate storage directory. Defaults to
                ``certs`` under gopher-mcp's own per-user data directory, or to
                an existing legacy ``~/.gemini/certs`` when one is present.

        Raises:
            ClientCertificateError: If no storage location can be determined.
            ClientCertificateStorageError: If the store cannot be created.
        """
        if storage_path is None:
            # An existing ~/.gemini/certs keeps being used exactly where it is:
            # the private keys in it are unrecoverable, so relocating them
            # behind the user's back would silently detach every identity from
            # the scope it authenticates.
            legacy = legacy_state_path("certs")
            if legacy is not None:
                storage_path = str(legacy)
            else:
                state_dir = default_state_directory()
                if state_dir is None:
                    raise ClientCertificateError("Could not determine home directory")
                storage_path = str(state_dir / "certs")

        self.storage_path = Path(storage_path)
        try:
            self.storage_path.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            raise ClientCertificateStorageError(
                f"Could not create the client certificate store at "
                f"{self.storage_path}: {e}"
            ) from e
        # Harden directory permissions (mkdir mode is subject to umask).
        with contextlib.suppress(OSError):  # non-POSIX or restricted FS
            self.storage_path.chmod(0o700)

        # Certificate registry file
        self.registry_path = self.storage_path / "registry.json"
        self._certificates: dict[str, GeminiCertificateInfo] = {}
        self._load_registry()

    def _get_cert_key(self, host: str, port: int, path: str) -> str:
        """Get storage key for certificate scope.

        Normalize the host (lowercase, strip IPv6 brackets and a trailing dot)
        so a case/trailing-dot variant resolves to the same stored identity,
        matching the TOFU and SSRF/allowlist host handling.
        """
        from .ssrf import normalize_host

        return f"{normalize_host(host)}:{port}{path}"

    def _load_registry(self) -> None:
        """Load certificate registry from storage.

        Fails CLOSED: a present-but-corrupt registry raises rather than silently
        resetting to empty. Silently emptying would orphan existing key files
        and drop the client identities the user relies on (a later save would
        then overwrite the registry). A missing file is the normal first run.
        """
        if not self.registry_path.exists():
            logger.info("No existing certificate registry found")
            return

        try:
            with self.registry_path.open() as f:
                data = json.load(f)
            certs = {
                key: GeminiCertificateInfo(**cert_data)
                for key, cert_data in data.items()
            }
        except Exception as e:
            logger.error("Client certificate registry is corrupt", error=str(e))
            raise ClientCertificateError(
                f"Certificate registry at {self.registry_path} is corrupt; refusing "
                "to start with an empty registry (fix or remove the file)"
            ) from e

        self._certificates = certs
        logger.info(
            "Client certificate registry loaded",
            count=len(self._certificates),
            storage_path=str(self.storage_path),
        )

    def _save_registry(self) -> None:
        """Save certificate registry to storage.

        Raises:
            ClientCertificateStorageError: If the registry could not be written.
        """
        try:
            # Convert certificates to dict for JSON serialization
            data = {}
            for key, cert in self._certificates.items():
                data[key] = cert.model_dump()

            # Use atomic write function
            atomic_write_json(str(self.registry_path), data)

            logger.debug("Certificate registry saved", count=len(self._certificates))
        except OSError as e:
            # A store that cannot be written is a storage failure, not a
            # transport one -- see ClientCertificateStorageError.
            logger.error(
                "Failed to save certificate registry",
                error=str(e),
                storage_path=str(self.storage_path),
            )
            raise ClientCertificateStorageError(
                f"Could not write the client certificate registry at "
                f"{self.registry_path}: {e}"
            ) from e
        except Exception as e:
            logger.error("Failed to save certificate registry", error=str(e))
            raise

    def generate_certificate(
        self,
        host: str,
        port: int = 1965,
        path: str = "/",
        common_name: str | None = None,
        validity_days: int = 365,
        key_size: int = 2048,
    ) -> tuple[str, str]:
        """Generate a new client certificate for a scope.

        Args:
            host: Hostname
            port: Port number
            path: Path scope
            common_name: Certificate common name (default: generated)
            validity_days: Certificate validity in days
            key_size: RSA key size in bits

        Returns:
            Tuple of (cert_path, key_path)

        Raises:
            ClientCertificateError: If generation fails
        """
        try:
            # Validate parameters
            if not host or not host.strip():
                raise ClientCertificateError("Host cannot be empty")
            if port <= 0 or port > 65535:
                raise ClientCertificateError("Port must be between 1 and 65535")
            if not path.startswith("/"):
                raise ClientCertificateError("Path must start with '/'")
            if validity_days <= 0:
                raise ClientCertificateError("Validity days must be positive")

            # Generate common name if not provided
            if common_name is None:
                timestamp = int(time.time())
                common_name = f"gemini-client-{host}-{timestamp}"

            # Generate private key
            private_key = rsa.generate_private_key(
                public_exponent=65537,
                key_size=key_size,
            )

            # Create certificate
            subject = issuer = x509.Name(
                [
                    x509.NameAttribute(NameOID.COMMON_NAME, common_name),
                    x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Gemini Client"),
                ]
            )

            cert = (
                x509.CertificateBuilder()
                .subject_name(subject)
                .issuer_name(issuer)
                .public_key(private_key.public_key())
                .serial_number(x509.random_serial_number())
                .not_valid_before(datetime.now(UTC))
                .not_valid_after(datetime.now(UTC) + timedelta(days=validity_days))
                .add_extension(
                    x509.SubjectAlternativeName(
                        [
                            x509.DNSName(host),
                        ]
                    ),
                    critical=False,
                )
                .add_extension(
                    x509.KeyUsage(
                        digital_signature=True,
                        key_encipherment=True,
                        key_agreement=False,
                        key_cert_sign=False,
                        crl_sign=False,
                        content_commitment=False,
                        data_encipherment=False,
                        encipher_only=False,
                        decipher_only=False,
                    ),
                    critical=True,
                )
                .add_extension(
                    x509.ExtendedKeyUsage(
                        [
                            x509.oid.ExtendedKeyUsageOID.CLIENT_AUTH,
                        ]
                    ),
                    critical=True,
                )
                .sign(private_key, hashes.SHA256())
            )

            # Name the files after a fresh random token rather than after the
            # subject. A subject-derived name is not unique -- two identities
            # for one host share it whenever their common names agree -- and
            # the second write would then destroy the first key while both
            # registry entries still pointed at the surviving file. O_EXCL
            # makes any residual collision a failure rather than a silent
            # overwrite of key material.
            key_id = secrets.token_hex(16)
            cert_path = self.storage_path / f"{key_id}.crt"
            key_path = self.storage_path / f"{key_id}.key"

            # Write certificate
            with cert_path.open("xb") as f:
                f.write(cert.public_bytes(serialization.Encoding.PEM))

            # Write the private key with owner-only permissions from creation.
            # Using os.open avoids the brief world-readable TOCTOU window that
            # exists when writing first and chmod-ing afterwards.
            key_bytes = private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
            fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(key_bytes)

            # Calculate fingerprint
            fingerprint = hashlib.sha256(
                cert.public_bytes(serialization.Encoding.DER)
            ).hexdigest()

            # Create certificate info
            cert_info = GeminiCertificateInfo(
                fingerprint=f"sha256:{fingerprint}",
                subject=cert.subject.rfc4514_string(),
                issuer=cert.issuer.rfc4514_string(),
                not_before=cert.not_valid_before_utc.isoformat(),
                not_after=cert.not_valid_after_utc.isoformat(),
                host=host,
                port=port,
                path=path,
                key_id=key_id,
            )

            # Store in registry, and leave nothing behind if persisting fails:
            # an entry that survives only in memory is an identity the caller
            # was told did not exist, still attached to every in-scope request
            # until the process restarts.
            key = self._get_cert_key(host, port, path)
            replaced = self._certificates.get(key)
            self._certificates[key] = cert_info
            try:
                self._save_registry()
            except Exception:
                if replaced is None:
                    self._certificates.pop(key, None)
                else:
                    self._certificates[key] = replaced
                for orphan in (cert_path, key_path):
                    with contextlib.suppress(OSError):
                        orphan.unlink()
                raise

            logger.info(
                "Client certificate generated",
                host=host,
                port=port,
                path=path,
                common_name=common_name,
                fingerprint=fingerprint[:16] + "...",
                cert_path=str(cert_path),
            )

            return str(cert_path), str(key_path)

        except ClientCertificateStorageError:
            # Already says the store, not the certificate, was the problem;
            # flattening it into a generic ClientCertificateError would lose
            # the only distinction a caller can act on.
            logger.error("Failed to generate client certificate: store unusable")
            raise
        except OSError as e:
            # Writing the certificate or its key failed (read-only store, full
            # disk, denied path). Same reasoning as _save_registry: report it as
            # storage, and never as a bare OSError.
            logger.error("Failed to generate client certificate", error=str(e))
            raise ClientCertificateStorageError(
                f"Certificate generation failed: the certificate store at "
                f"{self.storage_path} could not be written: {e}"
            ) from e
        except Exception as e:
            logger.error("Failed to generate client certificate", error=str(e))
            raise ClientCertificateError(f"Certificate generation failed: {e}") from e

    def _certificate_paths(self, cert_info: GeminiCertificateInfo) -> tuple[Path, Path]:
        """Locate the stored key pair for a registry entry.

        Entries carry their own opaque ``key_id``. Those written before that
        field existed are named after the certificate's common name, so the
        subject stays the fallback locator for them -- and only for them.
        """
        stem = cert_info.key_id or self._extract_common_name(cert_info.subject)
        return self.storage_path / f"{stem}.crt", self.storage_path / f"{stem}.key"

    def _files_present(self, cert_info: GeminiCertificateInfo) -> bool:
        """Report whether both halves of a registry entry are on disk."""
        cert_path, key_path = self._certificate_paths(cert_info)
        return cert_path.exists() and key_path.exists()

    def get_certificate_info_for_scope(
        self, host: str, port: int = 1965, path: str = "/"
    ) -> GeminiCertificateInfo | None:
        """Get the certificate a request for this scope would actually present.

        The exact scope wins, then the longest in-scope parent, and only an
        entry whose certificate and key are both still on disk qualifies: an
        entry whose files are gone authenticates nothing, so reporting it as
        the identity in play would describe a request that cannot happen.

        Args:
            host: Hostname
            port: Port number
            path: Path scope

        Returns:
            The registry entry in play for that request, or None
        """
        # Try exact match first
        key = self._get_cert_key(host, port, path)
        cert_info = self._certificates.get(key)

        if cert_info and self._files_present(cert_info):
            return cert_info

        # Try to find a certificate for a parent path
        from .ssrf import normalize_host

        norm_host = normalize_host(host)
        best_match = None
        best_path_len = 0

        for stored_cert in self._certificates.values():
            if (
                normalize_host(stored_cert.host) == norm_host
                and stored_cert.port == port
                and _path_in_scope(path, stored_cert.path)
                and len(stored_cert.path) > best_path_len
            ):
                best_match = stored_cert
                best_path_len = len(stored_cert.path)

        if best_match and self._files_present(best_match):
            return best_match

        return None

    def get_certificate_for_scope(
        self, host: str, port: int = 1965, path: str = "/"
    ) -> tuple[str, str] | None:
        """Get certificate paths for a specific scope.

        Args:
            host: Hostname
            port: Port number
            path: Path scope

        Returns:
            Tuple of (cert_path, key_path) or None if not found
        """
        cert_info = self.get_certificate_info_for_scope(host, port, path)
        if cert_info is None:
            return None

        cert_path, key_path = self._certificate_paths(cert_info)
        return str(cert_path), str(key_path)

    def _extract_common_name(self, subject: str) -> str:
        """Extract the common name from an RFC 4514 certificate subject.

        Parse via the cryptography library so escaped separators inside an
        attribute value (RFC 4514 renders an embedded comma as ``\\,``) are
        unescaped correctly. A naive split on commas would truncate such a CN,
        and the filename derived from it would then no longer match the file on
        disk -- silently disabling the certificate.
        """
        try:
            name = x509.Name.from_rfc4514_string(subject)
            attrs = name.get_attributes_for_oid(NameOID.COMMON_NAME)
            if attrs:
                return str(attrs[0].value)
            return "unknown"
        except ValueError:
            # Not strict RFC 4514 (e.g. a legacy/hand-entered subject with a
            # space after the comma). Fall back to a lenient split -- safe here
            # because any value with an escaped comma IS valid RFC 4514 and was
            # handled above, so this path never sees an escape to mangle.
            for raw_part in subject.split(","):
                part = raw_part.strip()
                if part.startswith("CN="):
                    return part[3:]
            return "unknown"

    def list_certificates(self) -> list[GeminiCertificateInfo]:
        """List all stored certificates.

        Returns:
            List of certificate information
        """
        return list(self._certificates.values())

    def remove_certificate(self, host: str, port: int = 1965, path: str = "/") -> bool:
        """Remove certificate for a scope.

        The registry is persisted before the files are unlinked, and the entry
        is put back if persisting fails, so a reported failure always means the
        identity is still held both in memory and on disk. A private key that
        survives its unlink is reported rather than swallowed: the entry is
        gone and nothing attaches the identity any more, but the key is still
        at rest and callers must not claim it was destroyed.

        Args:
            host: Hostname
            port: Port number
            path: Path scope

        Returns:
            True if certificate was removed, False if not found

        Raises:
            ClientCertificateKeyRetainedError: If the registry entry was
                removed but its private key file could not be deleted.
        """
        key = self._get_cert_key(host, port, path)
        cert_info = self._certificates.get(key)

        if cert_info:
            cert_path, key_path = self._certificate_paths(cert_info)

            # Remove from registry
            del self._certificates[key]
            try:
                self._save_registry()
            except Exception:
                self._certificates[key] = cert_info
                raise

            # Remove files
            try:
                if cert_path.exists():
                    cert_path.unlink()
                if key_path.exists():
                    key_path.unlink()
            except Exception as e:
                logger.warning("Failed to remove certificate files", error=str(e))

            key_retained = key_path.exists()
            logger.info(
                "Client certificate removed",
                host=host,
                port=port,
                path=path,
                key_retained=key_retained,
            )
            if key_retained:
                logger.error(
                    "Client certificate private key survived removal",
                    host=host,
                    port=port,
                    path=path,
                )
                raise ClientCertificateKeyRetainedError(
                    "The registry entry was removed, but its private key file "
                    "could not be deleted from the certificate store"
                )
            return True

        return False
