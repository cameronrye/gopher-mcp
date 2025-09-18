"""Security policy enforcement for Gemini protocol operations."""

import re
import time
from enum import Enum
from typing import Dict, List, Optional, Set, Any, Tuple
from dataclasses import dataclass, field

import structlog

from .models import GeminiCertificateInfo

logger = structlog.get_logger(__name__)


class PolicyAction(Enum):
    """Actions that can be taken when a policy is violated."""

    ALLOW = "allow"
    WARN = "warn"
    BLOCK = "block"
    PROMPT = "prompt"


class PolicyViolationType(Enum):
    """Types of policy violations."""

    HOST_BLOCKED = "host_blocked"
    HOST_NOT_ALLOWED = "host_not_allowed"
    CERTIFICATE_SCOPE_VIOLATION = "certificate_scope_violation"
    CERTIFICATE_REUSE = "certificate_reuse"
    CERTIFICATE_EXPIRED = "certificate_expired"
    CERTIFICATE_CHANGED = "certificate_changed"
    CONNECTION_LIMIT_EXCEEDED = "connection_limit_exceeded"
    RATE_LIMIT_EXCEEDED = "rate_limit_exceeded"
    INSECURE_CONNECTION = "insecure_connection"


@dataclass
class PolicyViolation:
    """Represents a security policy violation."""

    violation_type: PolicyViolationType
    message: str
    host: str
    port: int
    path: str = "/"
    severity: str = "medium"
    metadata: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)


@dataclass
class SecurityPolicyConfig:
    """Configuration for security policy enforcement."""

    # Host restrictions
    allowed_hosts: Optional[Set[str]] = None
    blocked_hosts: Optional[Set[str]] = None
    host_patterns_allowed: Optional[List[str]] = None
    host_patterns_blocked: Optional[List[str]] = None

    # Certificate policies
    allow_certificate_reuse: bool = False
    max_certificate_age_days: int = 365
    require_certificate_for_hosts: Optional[Set[str]] = None
    certificate_scope_enforcement: bool = True

    # Connection limits
    max_connections_per_host: int = 10
    max_connections_per_minute: int = 60
    connection_timeout_seconds: float = 30.0

    # Security requirements
    require_tls_1_3: bool = False
    require_perfect_forward_secrecy: bool = True
    allow_self_signed_certificates: bool = True  # Common in Gemini

    # Policy actions
    host_violation_action: PolicyAction = PolicyAction.BLOCK
    certificate_violation_action: PolicyAction = PolicyAction.WARN
    connection_limit_action: PolicyAction = PolicyAction.WARN

    # Logging and monitoring
    log_policy_violations: bool = True
    log_allowed_connections: bool = False

    def __post_init__(self) -> None:
        """Validate configuration."""
        if self.allowed_hosts and self.blocked_hosts:
            overlap = self.allowed_hosts & self.blocked_hosts
            if overlap:
                raise ValueError(f"Hosts cannot be both allowed and blocked: {overlap}")


class SecurityPolicyEnforcer:
    """Enforces security policies for Gemini connections."""

    def __init__(self, config: Optional[SecurityPolicyConfig] = None):
        """Initialize policy enforcer.

        Args:
            config: Security policy configuration
        """
        self.config = config or SecurityPolicyConfig()
        self._connection_counts: Dict[str, int] = {}
        self._connection_times: Dict[str, List[float]] = {}
        self._certificate_usage: Dict[str, List[Tuple[str, int, str]]] = {}

    def validate_connection(
        self,
        host: str,
        port: int,
        path: str = "/",
        certificate_info: Optional[GeminiCertificateInfo] = None,
    ) -> Tuple[bool, List[PolicyViolation]]:
        """Validate a connection against security policies.

        Args:
            host: Target hostname
            port: Target port
            path: Request path
            certificate_info: Certificate information if available

        Returns:
            Tuple of (is_allowed, violations)
        """
        violations = []

        # Validate host restrictions
        host_violations = self._validate_host_restrictions(host, port, path)
        violations.extend(host_violations)

        # Validate connection limits
        limit_violations = self._validate_connection_limits(host, port, path)
        violations.extend(limit_violations)

        # Validate certificate policies
        if certificate_info:
            cert_violations = self._validate_certificate_policies(
                host, port, path, certificate_info
            )
            violations.extend(cert_violations)

        # Determine if connection should be allowed
        is_allowed = self._should_allow_connection(violations)

        # Log violations if configured
        if self.config.log_policy_violations and violations:
            for violation in violations:
                logger.warning(
                    "Security policy violation",
                    violation_type=violation.violation_type.value,
                    host=host,
                    port=port,
                    path=path,
                    message=violation.message,
                    severity=violation.severity,
                )

        # Log allowed connections if configured
        if self.config.log_allowed_connections and is_allowed:
            logger.info(
                "Connection allowed by security policy",
                host=host,
                port=port,
                path=path,
                violations_count=len(violations),
            )

        return is_allowed, violations

    def _validate_host_restrictions(
        self, host: str, port: int, path: str
    ) -> List[PolicyViolation]:
        """Validate host restrictions."""
        violations = []

        # Check blocked hosts
        if self.config.blocked_hosts and host in self.config.blocked_hosts:
            violations.append(
                PolicyViolation(
                    violation_type=PolicyViolationType.HOST_BLOCKED,
                    message=f"Host {host} is explicitly blocked",
                    host=host,
                    port=port,
                    path=path,
                    severity="high",
                )
            )

        # Check allowed hosts
        if self.config.allowed_hosts and host not in self.config.allowed_hosts:
            violations.append(
                PolicyViolation(
                    violation_type=PolicyViolationType.HOST_NOT_ALLOWED,
                    message=f"Host {host} is not in allowed hosts list",
                    host=host,
                    port=port,
                    path=path,
                    severity="high",
                )
            )

        # Check blocked host patterns
        if self.config.host_patterns_blocked:
            for pattern in self.config.host_patterns_blocked:
                if re.match(pattern, host):
                    violations.append(
                        PolicyViolation(
                            violation_type=PolicyViolationType.HOST_BLOCKED,
                            message=f"Host {host} matches blocked pattern {pattern}",
                            host=host,
                            port=port,
                            path=path,
                            severity="high",
                            metadata={"pattern": pattern},
                        )
                    )

        # Check allowed host patterns
        if self.config.host_patterns_allowed:
            allowed = False
            for pattern in self.config.host_patterns_allowed:
                if re.match(pattern, host):
                    allowed = True
                    break

            if not allowed:
                violations.append(
                    PolicyViolation(
                        violation_type=PolicyViolationType.HOST_NOT_ALLOWED,
                        message=f"Host {host} does not match any allowed patterns",
                        host=host,
                        port=port,
                        path=path,
                        severity="high",
                    )
                )

        return violations

    def _validate_connection_limits(
        self, host: str, port: int, path: str
    ) -> List[PolicyViolation]:
        """Validate connection limits."""
        violations = []
        current_time = time.time()
        host_key = f"{host}:{port}"

        # Check per-host connection limit
        current_connections = self._connection_counts.get(host_key, 0)
        if current_connections >= self.config.max_connections_per_host:
            violations.append(
                PolicyViolation(
                    violation_type=PolicyViolationType.CONNECTION_LIMIT_EXCEEDED,
                    message=f"Too many connections to {host}:{port} ({current_connections}/{self.config.max_connections_per_host})",
                    host=host,
                    port=port,
                    path=path,
                    severity="medium",
                    metadata={
                        "current_connections": current_connections,
                        "limit": self.config.max_connections_per_host,
                    },
                )
            )

        # Check rate limiting
        if host_key not in self._connection_times:
            self._connection_times[host_key] = []

        # Clean old connection times (older than 1 minute)
        minute_ago = current_time - 60
        self._connection_times[host_key] = [
            t for t in self._connection_times[host_key] if t > minute_ago
        ]

        # Check rate limit
        connections_this_minute = len(self._connection_times[host_key])
        if connections_this_minute >= self.config.max_connections_per_minute:
            violations.append(
                PolicyViolation(
                    violation_type=PolicyViolationType.RATE_LIMIT_EXCEEDED,
                    message=f"Rate limit exceeded for {host}:{port} ({connections_this_minute}/{self.config.max_connections_per_minute} per minute)",
                    host=host,
                    port=port,
                    path=path,
                    severity="medium",
                    metadata={
                        "connections_this_minute": connections_this_minute,
                        "limit": self.config.max_connections_per_minute,
                    },
                )
            )

        return violations

    def _validate_certificate_policies(
        self, host: str, port: int, path: str, certificate_info: GeminiCertificateInfo
    ) -> List[PolicyViolation]:
        """Validate certificate policies."""
        violations = []

        # Check certificate scope
        if self.config.certificate_scope_enforcement:
            if certificate_info.host != host:
                violations.append(
                    PolicyViolation(
                        violation_type=PolicyViolationType.CERTIFICATE_SCOPE_VIOLATION,
                        message=f"Certificate host {certificate_info.host} does not match connection host {host}",
                        host=host,
                        port=port,
                        path=path,
                        severity="high",
                        metadata={"cert_host": certificate_info.host},
                    )
                )

            if certificate_info.port != port:
                violations.append(
                    PolicyViolation(
                        violation_type=PolicyViolationType.CERTIFICATE_SCOPE_VIOLATION,
                        message=f"Certificate port {certificate_info.port} does not match connection port {port}",
                        host=host,
                        port=port,
                        path=path,
                        severity="medium",
                        metadata={"cert_port": certificate_info.port},
                    )
                )

            if not path.startswith(certificate_info.path):
                violations.append(
                    PolicyViolation(
                        violation_type=PolicyViolationType.CERTIFICATE_SCOPE_VIOLATION,
                        message=f"Request path {path} is outside certificate scope {certificate_info.path}",
                        host=host,
                        port=port,
                        path=path,
                        severity="medium",
                        metadata={"cert_path": certificate_info.path},
                    )
                )

        # Check certificate reuse
        if not self.config.allow_certificate_reuse:
            cert_key = certificate_info.fingerprint
            if cert_key in self._certificate_usage:
                existing_usage = self._certificate_usage[cert_key]
                for existing_host, existing_port, existing_path in existing_usage:
                    if existing_host != host or existing_port != port:
                        violations.append(
                            PolicyViolation(
                                violation_type=PolicyViolationType.CERTIFICATE_REUSE,
                                message=f"Certificate is already used for {existing_host}:{existing_port}",
                                host=host,
                                port=port,
                                path=path,
                                severity="medium",
                                metadata={
                                    "existing_host": existing_host,
                                    "existing_port": existing_port,
                                    "existing_path": existing_path,
                                },
                            )
                        )

        return violations

    def _should_allow_connection(self, violations: List[PolicyViolation]) -> bool:
        """Determine if connection should be allowed based on violations."""
        for violation in violations:
            if violation.violation_type in (
                PolicyViolationType.HOST_BLOCKED,
                PolicyViolationType.HOST_NOT_ALLOWED,
            ):
                if self.config.host_violation_action == PolicyAction.BLOCK:
                    return False

            elif violation.violation_type in (
                PolicyViolationType.CERTIFICATE_SCOPE_VIOLATION,
                PolicyViolationType.CERTIFICATE_REUSE,
                PolicyViolationType.CERTIFICATE_EXPIRED,
                PolicyViolationType.CERTIFICATE_CHANGED,
            ):
                if self.config.certificate_violation_action == PolicyAction.BLOCK:
                    return False

            elif violation.violation_type in (
                PolicyViolationType.CONNECTION_LIMIT_EXCEEDED,
                PolicyViolationType.RATE_LIMIT_EXCEEDED,
            ):
                if self.config.connection_limit_action == PolicyAction.BLOCK:
                    return False

        return True

    def record_connection(self, host: str, port: int, path: str = "/") -> None:
        """Record a successful connection for tracking purposes.

        Args:
            host: Connected hostname
            port: Connected port
            path: Request path
        """
        current_time = time.time()
        host_key = f"{host}:{port}"

        # Update connection count
        self._connection_counts[host_key] = self._connection_counts.get(host_key, 0) + 1

        # Record connection time for rate limiting
        if host_key not in self._connection_times:
            self._connection_times[host_key] = []
        self._connection_times[host_key].append(current_time)

    def record_certificate_usage(
        self,
        certificate_info: GeminiCertificateInfo,
        host: str,
        port: int,
        path: str = "/",
    ) -> None:
        """Record certificate usage for reuse tracking.

        Args:
            certificate_info: Certificate information
            host: Hostname where certificate is used
            port: Port where certificate is used
            path: Path where certificate is used
        """
        cert_key = certificate_info.fingerprint

        if cert_key not in self._certificate_usage:
            self._certificate_usage[cert_key] = []

        usage_entry = (host, port, path)
        if usage_entry not in self._certificate_usage[cert_key]:
            self._certificate_usage[cert_key].append(usage_entry)

    def cleanup_expired_records(self) -> None:
        """Clean up expired connection and certificate records."""
        current_time = time.time()

        # Clean up old connection times (older than 1 hour)
        hour_ago = current_time - 3600
        for host_key in list(self._connection_times.keys()):
            self._connection_times[host_key] = [
                t for t in self._connection_times[host_key] if t > hour_ago
            ]
            if not self._connection_times[host_key]:
                del self._connection_times[host_key]

        # Reset connection counts periodically
        # This is a simple approach; in production, you might want more sophisticated tracking
        if len(self._connection_counts) > 1000:
            self._connection_counts.clear()

    def get_policy_statistics(self) -> Dict[str, Any]:
        """Get statistics about policy enforcement.

        Returns:
            Dictionary with policy statistics
        """
        return {
            "active_connections": dict(self._connection_counts),
            "tracked_hosts": len(self._connection_times),
            "tracked_certificates": len(self._certificate_usage),
            "total_certificate_usages": sum(
                len(usages) for usages in self._certificate_usage.values()
            ),
            "config": {
                "max_connections_per_host": self.config.max_connections_per_host,
                "max_connections_per_minute": self.config.max_connections_per_minute,
                "allow_certificate_reuse": self.config.allow_certificate_reuse,
                "certificate_scope_enforcement": self.config.certificate_scope_enforcement,
            },
        }
