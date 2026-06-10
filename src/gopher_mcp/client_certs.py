"""Client certificate management for Gemini protocol."""

import contextlib
import hashlib
import json
import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import structlog
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from .models import GeminiCertificateInfo
from .utils import atomic_write_json, get_home_directory

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


class ClientCertificateManager:
    """Manager for Gemini client certificates."""

    def __init__(self, storage_path: str | None = None):
        """Initialize client certificate manager.

        Args:
            storage_path: Path to certificate storage directory (default: ~/.gemini/certs/)
        """
        if storage_path is None:
            home_dir = get_home_directory()
            if home_dir is None:
                raise ClientCertificateError("Could not determine home directory")
            storage_path = str(home_dir / ".gemini" / "certs")

        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
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
        """Save certificate registry to storage."""
        try:
            # Convert certificates to dict for JSON serialization
            data = {}
            for key, cert in self._certificates.items():
                data[key] = cert.model_dump()

            # Use atomic write function
            atomic_write_json(str(self.registry_path), data)

            logger.debug("Certificate registry saved", count=len(self._certificates))
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

            # Generate file names
            cert_filename = f"{common_name}.crt"
            key_filename = f"{common_name}.key"
            cert_path = self.storage_path / cert_filename
            key_path = self.storage_path / key_filename

            # Write certificate
            with cert_path.open("wb") as f:
                f.write(cert.public_bytes(serialization.Encoding.PEM))

            # Write the private key with owner-only permissions from creation.
            # Using os.open avoids the brief world-readable TOCTOU window that
            # exists when writing first and chmod-ing afterwards.
            key_bytes = private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
            fd = os.open(key_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
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
            )

            # Store in registry
            key = self._get_cert_key(host, port, path)
            self._certificates[key] = cert_info
            self._save_registry()

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

        except Exception as e:
            logger.error("Failed to generate client certificate", error=str(e))
            raise ClientCertificateError(f"Certificate generation failed: {e}") from e

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
        # Try exact match first
        key = self._get_cert_key(host, port, path)
        cert_info = self._certificates.get(key)

        if cert_info:
            cert_path = (
                self.storage_path
                / f"{self._extract_common_name(cert_info.subject)}.crt"
            )
            key_path = (
                self.storage_path
                / f"{self._extract_common_name(cert_info.subject)}.key"
            )

            if cert_path.exists() and key_path.exists():
                return str(cert_path), str(key_path)

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

        if best_match:
            cert_path = (
                self.storage_path
                / f"{self._extract_common_name(best_match.subject)}.crt"
            )
            key_path = (
                self.storage_path
                / f"{self._extract_common_name(best_match.subject)}.key"
            )

            if cert_path.exists() and key_path.exists():
                return str(cert_path), str(key_path)

        return None

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

        Args:
            host: Hostname
            port: Port number
            path: Path scope

        Returns:
            True if certificate was removed, False if not found
        """
        key = self._get_cert_key(host, port, path)
        cert_info = self._certificates.get(key)

        if cert_info:
            # Remove files
            common_name = self._extract_common_name(cert_info.subject)
            cert_path = self.storage_path / f"{common_name}.crt"
            key_path = self.storage_path / f"{common_name}.key"

            try:
                if cert_path.exists():
                    cert_path.unlink()
                if key_path.exists():
                    key_path.unlink()
            except Exception as e:
                logger.warning("Failed to remove certificate files", error=str(e))

            # Remove from registry
            del self._certificates[key]
            self._save_registry()

            logger.info("Client certificate removed", host=host, port=port, path=path)
            return True

        return False

    def cleanup_expired(self) -> int:
        """Remove expired certificates.

        Returns:
            Number of certificates removed
        """
        current_time = datetime.now(UTC)
        expired_keys = []

        for key, cert_info in self._certificates.items():
            try:
                not_after = datetime.fromisoformat(
                    cert_info.not_after.replace("Z", "+00:00")
                )
                # Ensure timezone-aware comparison
                if not_after.tzinfo is None:
                    not_after = not_after.replace(tzinfo=UTC)
                if not_after < current_time:
                    expired_keys.append(key)
            except ValueError:
                # If we can't parse the date, consider it expired
                expired_keys.append(key)

        for key in expired_keys:
            cert_info = self._certificates[key]
            self.remove_certificate(cert_info.host, cert_info.port, cert_info.path)

        if expired_keys:
            logger.info("Expired client certificates removed", count=len(expired_keys))

        return len(expired_keys)
