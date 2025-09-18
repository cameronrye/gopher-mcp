# Gemini Security Architecture Design

## Overview

This document defines the comprehensive security architecture for Gemini protocol implementation, focusing on TLS configuration, Trust-on-First-Use (TOFU) certificate validation, client certificate management, and security policy enforcement.

## Core Security Principles

1. **Mandatory Encryption**: All connections use TLS 1.2+ with no plaintext fallback
2. **Trust-on-First-Use**: Accept any certificate on first connection, verify consistency thereafter
3. **User Agency**: Users control trust decisions and certificate management
4. **Scope Limitation**: Client certificates limited to specific host/port/path combinations
5. **Defense in Depth**: Multiple layers of validation and security checks

## TLS Configuration Requirements

### Minimum TLS Standards

**TLS Version Requirements:**

- **Minimum**: TLS 1.2 (required by Gemini specification)
- **Preferred**: TLS 1.3 (better performance and security)
- **Forbidden**: TLS 1.1 and below (security vulnerabilities)

**Cipher Suite Preferences:**

```python
# TLS 1.3 (preferred)
PREFERRED_TLS13_CIPHERS = [
    "TLS_AES_256_GCM_SHA384",
    "TLS_CHACHA20_POLY1305_SHA256",
    "TLS_AES_128_GCM_SHA256",
]

# TLS 1.2 (fallback)
PREFERRED_TLS12_CIPHERS = [
    "ECDHE-ECDSA-AES256-GCM-SHA384",
    "ECDHE-RSA-AES256-GCM-SHA384",
    "ECDHE-ECDSA-CHACHA20-POLY1305",
    "ECDHE-RSA-CHACHA20-POLY1305",
    "ECDHE-ECDSA-AES128-GCM-SHA256",
    "ECDHE-RSA-AES128-GCM-SHA256",
]
```

**TLS Context Configuration:**

```python
import ssl
from typing import Optional

def create_tls_context(
    min_version: str = "TLSv1.2",
    verify_mode: ssl.VerifyMode = ssl.CERT_NONE,
    client_cert_path: Optional[str] = None,
    client_key_path: Optional[str] = None,
) -> ssl.SSLContext:
    """Create secure TLS context for Gemini connections."""

    context = ssl.create_default_context()

    # Set minimum TLS version
    if min_version == "TLSv1.3":
        context.minimum_version = ssl.TLSVersion.TLSv1_3
    else:
        context.minimum_version = ssl.TLSVersion.TLSv1_2

    # Configure verification mode (TOFU handles verification)
    context.check_hostname = False
    context.verify_mode = verify_mode

    # Load client certificate if provided
    if client_cert_path and client_key_path:
        context.load_cert_chain(client_cert_path, client_key_path)

    # Set cipher preferences
    if hasattr(context, 'set_ciphers'):
        context.set_ciphers(':'.join(PREFERRED_TLS12_CIPHERS))

    return context
```

### SNI (Server Name Indication) Requirements

**Mandatory SNI Support:**

- All connections MUST include hostname in SNI extension
- Required by Gemini specification for proper certificate validation
- Enables virtual hosting on Gemini servers

```python
async def connect_with_sni(host: str, port: int, context: ssl.SSLContext) -> ssl.SSLSocket:
    """Connect with mandatory SNI support."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    ssl_sock = context.wrap_socket(sock, server_hostname=host)
    await ssl_sock.connect((host, port))
    return ssl_sock
```

## TOFU Certificate Validation System

### Certificate Storage Format

**SQLite Database Schema:**

```sql
CREATE TABLE tofu_certificates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    host TEXT NOT NULL,
    port INTEGER NOT NULL DEFAULT 1965,
    fingerprint TEXT NOT NULL,
    algorithm TEXT NOT NULL DEFAULT 'sha256',
    first_seen REAL NOT NULL,
    last_seen REAL NOT NULL,
    expires REAL,
    subject TEXT,
    issuer TEXT,
    created_at REAL NOT NULL DEFAULT (julianday('now')),
    updated_at REAL NOT NULL DEFAULT (julianday('now')),
    UNIQUE(host, port)
);

CREATE INDEX idx_tofu_host_port ON tofu_certificates(host, port);
CREATE INDEX idx_tofu_expires ON tofu_certificates(expires);
```

**Alternative JSON Storage Format:**

```json
{
  "version": "1.0",
  "certificates": {
    "example.org:1965": {
      "fingerprint": "sha256:1234567890abcdef...",
      "algorithm": "sha256",
      "first_seen": 1640995200.0,
      "last_seen": 1640995200.0,
      "expires": 1672531200.0,
      "subject": "CN=example.org",
      "issuer": "CN=example.org",
      "metadata": {
        "user_approved": true,
        "warning_shown": false
      }
    }
  }
}
```

### TOFU Validation Workflow

**Certificate Fingerprint Calculation:**

```python
import hashlib
import ssl
from typing import Tuple

def calculate_certificate_fingerprint(cert_der: bytes, algorithm: str = "sha256") -> str:
    """Calculate certificate fingerprint using specified algorithm."""
    if algorithm == "sha256":
        hash_obj = hashlib.sha256()
    elif algorithm == "sha1":
        hash_obj = hashlib.sha1()
    else:
        raise ValueError(f"Unsupported hash algorithm: {algorithm}")

    hash_obj.update(cert_der)
    return f"{algorithm}:{hash_obj.hexdigest()}"

def extract_certificate_info(ssl_sock: ssl.SSLSocket) -> Tuple[str, dict]:
    """Extract certificate information from SSL connection."""
    cert_der = ssl_sock.getpeercert_chain()[0].to_bytes()
    cert_info = ssl_sock.getpeercert()

    fingerprint = calculate_certificate_fingerprint(cert_der)

    return fingerprint, {
        "subject": cert_info.get("subject", []),
        "issuer": cert_info.get("issuer", []),
        "not_before": cert_info.get("notBefore"),
        "not_after": cert_info.get("notAfter"),
    }
```

**TOFU Validation Process:**

```python
class TOFUValidator:
    """Trust-on-First-Use certificate validator."""

    async def validate_certificate(
        self,
        host: str,
        port: int,
        fingerprint: str,
        cert_info: dict,
    ) -> Tuple[bool, str]:
        """Validate certificate using TOFU policy.

        Returns:
            Tuple of (is_valid, reason)
        """
        stored_cert = await self.get_stored_certificate(host, port)

        if stored_cert is None:
            # First connection - store certificate
            await self.store_certificate(host, port, fingerprint, cert_info)
            return True, "First connection - certificate stored"

        if stored_cert.fingerprint == fingerprint:
            # Certificate matches - update last seen
            await self.update_last_seen(host, port)
            return True, "Certificate matches stored fingerprint"

        # Certificate changed - security warning
        if stored_cert.expires and time.time() > stored_cert.expires:
            # Old certificate expired - allow new certificate
            await self.store_certificate(host, port, fingerprint, cert_info)
            return True, "Certificate renewed after expiry"

        # Certificate changed before expiry - potential attack
        return False, "Certificate fingerprint changed before expiry"
```

### Certificate Change Handling

**Security Warning System:**

```python
class CertificateChangeHandler:
    """Handle certificate changes with user interaction."""

    async def handle_certificate_change(
        self,
        host: str,
        port: int,
        old_fingerprint: str,
        new_fingerprint: str,
        cert_info: dict,
    ) -> bool:
        """Handle certificate change with user approval."""

        warning_message = f"""
        SECURITY WARNING: Certificate changed for {host}:{port}

        Old fingerprint: {old_fingerprint}
        New fingerprint: {new_fingerprint}

        This could indicate:
        1. Server certificate renewal (normal)
        2. Man-in-the-middle attack (security risk)
        3. Server configuration change

        Do you want to accept the new certificate? (y/N)
        """

        # In MCP context, log warning and return False for safety
        logger.warning(
            "Certificate change detected",
            host=host,
            port=port,
            old_fingerprint=old_fingerprint,
            new_fingerprint=new_fingerprint,
        )

        # For automated systems, reject certificate changes
        return False
```

## Client Certificate Management

### Certificate Generation

**Client Certificate Creation:**

```python
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
import datetime

class ClientCertificateManager:
    """Manage client certificates for Gemini authentication."""

    def generate_client_certificate(
        self,
        host: str,
        port: int = 1965,
        path: str = "/",
        key_size: int = 2048,
        validity_days: int = 365,
    ) -> Tuple[bytes, bytes]:
        """Generate client certificate and private key.

        Returns:
            Tuple of (certificate_pem, private_key_pem)
        """
        # Generate private key
        private_key = rsa.generate_private_key(
            public_exponent=65537,
            key_size=key_size,
        )

        # Create certificate
        subject = issuer = x509.Name([
            x509.NameAttribute(NameOID.COMMON_NAME, f"gemini-client-{host}"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Gemini MCP Client"),
        ])

        cert = x509.CertificateBuilder().subject_name(
            subject
        ).issuer_name(
            issuer
        ).public_key(
            private_key.public_key()
        ).serial_number(
            x509.random_serial_number()
        ).not_valid_before(
            datetime.datetime.utcnow()
        ).not_valid_after(
            datetime.datetime.utcnow() + datetime.timedelta(days=validity_days)
        ).add_extension(
            x509.SubjectAlternativeName([
                x509.DNSName(host),
            ]),
            critical=False,
        ).sign(private_key, hashes.SHA256())

        # Serialize to PEM format
        cert_pem = cert.public_bytes(serialization.Encoding.PEM)
        key_pem = private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )

        return cert_pem, key_pem
```

### Certificate Scope Management

**Scope-Limited Certificate Storage:**

```python
class ClientCertificateStore:
    """Store and manage client certificates with scope limitations."""

    def __init__(self, store_path: str):
        self.store_path = Path(store_path)
        self.store_path.mkdir(parents=True, exist_ok=True)

    def get_certificate_path(self, host: str, port: int, path: str) -> Tuple[Path, Path]:
        """Get certificate and key paths for specific scope."""
        scope_hash = hashlib.sha256(f"{host}:{port}:{path}".encode()).hexdigest()[:16]
        cert_path = self.store_path / f"{scope_hash}.crt"
        key_path = self.store_path / f"{scope_hash}.key"
        return cert_path, key_path

    async def store_certificate(
        self,
        host: str,
        port: int,
        path: str,
        cert_pem: bytes,
        key_pem: bytes,
    ) -> None:
        """Store certificate with scope limitations."""
        cert_path, key_path = self.get_certificate_path(host, port, path)

        # Write certificate and key files
        cert_path.write_bytes(cert_pem)
        key_path.write_bytes(key_pem)

        # Set restrictive permissions
        cert_path.chmod(0o600)
        key_path.chmod(0o600)

        # Store metadata
        metadata = {
            "host": host,
            "port": port,
            "path": path,
            "created": time.time(),
            "fingerprint": calculate_certificate_fingerprint(cert_pem),
        }

        metadata_path = cert_path.with_suffix(".json")
        metadata_path.write_text(json.dumps(metadata, indent=2))
```

## Security Policy Enforcement

### Connection Security Policies

**Security Policy Configuration:**

```python
@dataclass
class GeminiSecurityPolicy:
    """Security policy configuration for Gemini connections."""

    # TLS configuration
    min_tls_version: str = "TLSv1.2"
    require_sni: bool = True
    verify_certificates: bool = True

    # TOFU configuration
    tofu_enabled: bool = True
    allow_certificate_changes: bool = False
    certificate_change_warning: bool = True

    # Client certificate configuration
    auto_generate_client_certs: bool = False
    client_cert_validity_days: int = 365
    client_cert_key_size: int = 2048

    # Connection limits
    max_redirects: int = 5
    connection_timeout: float = 30.0

    # Host restrictions
    allowed_hosts: Optional[List[str]] = None
    blocked_hosts: Optional[List[str]] = None
```

### Security Validation Pipeline

**Multi-Layer Security Validation:**

```python
class SecurityValidator:
    """Multi-layer security validation for Gemini connections."""

    async def validate_connection(
        self,
        url: GeminiURL,
        policy: GeminiSecurityPolicy,
    ) -> Tuple[bool, List[str]]:
        """Validate connection against security policy.

        Returns:
            Tuple of (is_valid, validation_errors)
        """
        errors = []

        # Host allowlist/blocklist validation
        if policy.allowed_hosts and url.host not in policy.allowed_hosts:
            errors.append(f"Host {url.host} not in allowed hosts list")

        if policy.blocked_hosts and url.host in policy.blocked_hosts:
            errors.append(f"Host {url.host} is blocked")

        # Port validation
        if not 1 <= url.port <= 65535:
            errors.append(f"Invalid port number: {url.port}")

        # URL length validation
        if len(str(url).encode('utf-8')) > 1024:
            errors.append("URL exceeds 1024 byte limit")

        return len(errors) == 0, errors
```

This security architecture provides comprehensive protection while maintaining the simplicity and user agency principles of the Gemini protocol.
