"""Certificate fingerprint utilities and storage for Gemini protocol."""

import hashlib
import json
import re
import time
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Any, Union
from dataclasses import dataclass

import structlog

from .utils import atomic_write_json, get_home_directory

logger = structlog.get_logger(__name__)


class HashAlgorithm(Enum):
    """Supported hash algorithms for fingerprints."""

    SHA256 = "sha256"
    SHA1 = "sha1"
    MD5 = "md5"


@dataclass
class CertificateFingerprint:
    """Certificate fingerprint with multiple hash algorithms."""

    sha256: str
    sha1: Optional[str] = None
    md5: Optional[str] = None

    def __post_init__(self) -> None:
        """Validate fingerprint formats."""
        self.sha256 = self._normalize_fingerprint(self.sha256)
        if self.sha1:
            self.sha1 = self._normalize_fingerprint(self.sha1)
        if self.md5:
            self.md5 = self._normalize_fingerprint(self.md5)

    @staticmethod
    def _normalize_fingerprint(fingerprint: str) -> str:
        """Normalize fingerprint format (remove prefixes, convert to lowercase)."""
        # Remove common prefixes
        for prefix in ["sha256:", "sha1:", "md5:"]:
            if fingerprint.lower().startswith(prefix):
                fingerprint = fingerprint[len(prefix) :]

        # Remove colons and spaces, convert to lowercase
        return re.sub(r"[:\s]", "", fingerprint.lower())

    @classmethod
    def from_certificate(cls, cert_der: bytes) -> "CertificateFingerprint":
        """Create fingerprint from certificate DER bytes.

        Args:
            cert_der: Certificate in DER format

        Returns:
            CertificateFingerprint with all hash algorithms
        """
        sha256 = hashlib.sha256(cert_der).hexdigest()
        sha1 = hashlib.sha1(cert_der, usedforsecurity=False).hexdigest()
        md5 = hashlib.md5(cert_der, usedforsecurity=False).hexdigest()

        return cls(sha256=sha256, sha1=sha1, md5=md5)

    def get_fingerprint(self, algorithm: HashAlgorithm) -> Optional[str]:
        """Get fingerprint for specific algorithm.

        Args:
            algorithm: Hash algorithm

        Returns:
            Fingerprint string or None if not available
        """
        if algorithm == HashAlgorithm.SHA256:
            return self.sha256
        elif algorithm == HashAlgorithm.SHA1:
            return self.sha1
        else:  # algorithm == HashAlgorithm.MD5
            return self.md5

    def matches(self, other: Union[str, "CertificateFingerprint"]) -> bool:
        """Check if this fingerprint matches another.

        Args:
            other: Another fingerprint (string or CertificateFingerprint)

        Returns:
            True if fingerprints match
        """
        if isinstance(other, str):
            other_normalized = self._normalize_fingerprint(other)
            return (
                other_normalized == self.sha256
                or other_normalized == self.sha1
                or other_normalized == self.md5
            )

        else:  # isinstance(other, CertificateFingerprint)
            return (
                self.sha256 == other.sha256
                or (
                    self.sha1 is not None
                    and other.sha1 is not None
                    and self.sha1 == other.sha1
                )
                or (
                    self.md5 is not None
                    and other.md5 is not None
                    and self.md5 == other.md5
                )
            )

    def to_dict(self) -> Dict[str, str]:
        """Convert to dictionary for serialization."""
        result = {"sha256": self.sha256}
        if self.sha1:
            result["sha1"] = self.sha1
        if self.md5:
            result["md5"] = self.md5
        return result

    @classmethod
    def from_dict(cls, data: Dict[str, str]) -> "CertificateFingerprint":
        """Create from dictionary."""
        return cls(sha256=data["sha256"], sha1=data.get("sha1"), md5=data.get("md5"))


class FingerprintValidator:
    """Validator for certificate fingerprints."""

    @staticmethod
    def is_valid_fingerprint(fingerprint: str, algorithm: HashAlgorithm) -> bool:
        """Validate fingerprint format for specific algorithm.

        Args:
            fingerprint: Fingerprint string
            algorithm: Hash algorithm

        Returns:
            True if fingerprint is valid format
        """
        normalized = CertificateFingerprint._normalize_fingerprint(fingerprint)

        if algorithm == HashAlgorithm.SHA256:
            return len(normalized) == 64 and all(
                c in "0123456789abcdef" for c in normalized
            )
        elif algorithm == HashAlgorithm.SHA1:
            return len(normalized) == 40 and all(
                c in "0123456789abcdef" for c in normalized
            )
        else:  # algorithm == HashAlgorithm.MD5
            return len(normalized) == 32 and all(
                c in "0123456789abcdef" for c in normalized
            )

    @staticmethod
    def detect_algorithm(fingerprint: str) -> Optional[HashAlgorithm]:
        """Detect hash algorithm from fingerprint length.

        Args:
            fingerprint: Fingerprint string

        Returns:
            Detected algorithm or None
        """
        normalized = CertificateFingerprint._normalize_fingerprint(fingerprint)

        if len(normalized) == 64:
            return HashAlgorithm.SHA256
        elif len(normalized) == 40:
            return HashAlgorithm.SHA1
        elif len(normalized) == 32:
            return HashAlgorithm.MD5

        return None

    @staticmethod
    def format_fingerprint(fingerprint: str, with_colons: bool = False) -> str:
        """Format fingerprint for display.

        Args:
            fingerprint: Raw fingerprint
            with_colons: Whether to add colons between bytes

        Returns:
            Formatted fingerprint
        """
        normalized = CertificateFingerprint._normalize_fingerprint(fingerprint)

        if with_colons:
            # Add colons between every two characters
            return ":".join(normalized[i : i + 2] for i in range(0, len(normalized), 2))

        return normalized.upper()


class FingerprintStore:
    """Advanced storage and retrieval for certificate fingerprints."""

    def __init__(self, storage_path: Optional[str] = None):
        """Initialize fingerprint store.

        Args:
            storage_path: Path to storage file
        """
        if storage_path is None:
            home_dir = get_home_directory()
            if home_dir is None:
                raise ValueError("Could not determine home directory")
            gemini_dir = home_dir / ".gemini"
            gemini_dir.mkdir(exist_ok=True)
            storage_path = str(gemini_dir / "fingerprints.json")

        self.storage_path = storage_path
        self._fingerprints: Dict[str, Dict[str, Any]] = {}
        self._load_fingerprints()

    def _get_key(self, host: str, port: int) -> str:
        """Get storage key for host:port."""
        return f"{host}:{port}"

    def _load_fingerprints(self) -> None:
        """Load fingerprints from storage."""
        try:
            if Path(self.storage_path).exists():
                with open(self.storage_path, "r") as f:
                    self._fingerprints = json.load(f)
                logger.info(
                    "Fingerprints loaded",
                    count=len(self._fingerprints),
                    storage_path=self.storage_path,
                )
            else:
                logger.info("No existing fingerprint storage found")
        except Exception as e:
            logger.error("Failed to load fingerprints", error=str(e))
            self._fingerprints = {}

    def _save_fingerprints(self) -> None:
        """Save fingerprints to storage."""
        try:
            # Use atomic write function
            atomic_write_json(self.storage_path, self._fingerprints)

            logger.debug("Fingerprints saved", count=len(self._fingerprints))
        except Exception as e:
            logger.error("Failed to save fingerprints", error=str(e))
            raise

    def store_fingerprint(
        self,
        host: str,
        port: int,
        fingerprint: CertificateFingerprint,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Store certificate fingerprint.

        Args:
            host: Hostname
            port: Port number
            fingerprint: Certificate fingerprint
            metadata: Additional metadata
        """
        key = self._get_key(host, port)

        entry = {
            "host": host,
            "port": port,
            "fingerprint": fingerprint.to_dict(),
            "stored_at": time.time(),
            "metadata": metadata or {},
        }

        self._fingerprints[key] = entry
        self._save_fingerprints()

        logger.info(
            "Fingerprint stored",
            host=host,
            port=port,
            sha256=fingerprint.sha256[:16] + "...",
        )

    def get_fingerprint(self, host: str, port: int) -> Optional[CertificateFingerprint]:
        """Get stored fingerprint for host:port.

        Args:
            host: Hostname
            port: Port number

        Returns:
            Certificate fingerprint or None
        """
        key = self._get_key(host, port)
        entry = self._fingerprints.get(key)

        if entry:
            return CertificateFingerprint.from_dict(entry["fingerprint"])

        return None

    def search_fingerprints(
        self,
        fingerprint: Optional[str] = None,
        host_pattern: Optional[str] = None,
        algorithm: Optional[HashAlgorithm] = None,
    ) -> List[Dict[str, Any]]:
        """Search for fingerprints by various criteria.

        Args:
            fingerprint: Fingerprint to search for
            host_pattern: Host pattern (supports wildcards)
            algorithm: Hash algorithm filter

        Returns:
            List of matching entries
        """
        results = []

        for entry in self._fingerprints.values():
            match = True

            # Filter by fingerprint
            if fingerprint:
                stored_fp = CertificateFingerprint.from_dict(entry["fingerprint"])
                if not stored_fp.matches(fingerprint):
                    match = False

            # Filter by host pattern
            if host_pattern and match:
                import fnmatch

                if not fnmatch.fnmatch(entry["host"], host_pattern):
                    match = False

            # Filter by algorithm
            if algorithm and match:
                stored_fp = CertificateFingerprint.from_dict(entry["fingerprint"])
                if not stored_fp.get_fingerprint(algorithm):
                    match = False

            if match:
                results.append(entry)

        return results

    def remove_fingerprint(self, host: str, port: int) -> bool:
        """Remove stored fingerprint.

        Args:
            host: Hostname
            port: Port number

        Returns:
            True if fingerprint was removed
        """
        key = self._get_key(host, port)

        if key in self._fingerprints:
            del self._fingerprints[key]
            self._save_fingerprints()

            logger.info("Fingerprint removed", host=host, port=port)
            return True

        return False

    def export_fingerprints(self, file_path: str) -> None:
        """Export fingerprints to file.

        Args:
            file_path: Export file path
        """
        with open(file_path, "w") as f:
            json.dump(self._fingerprints, f, indent=2)

        logger.info(
            "Fingerprints exported", file_path=file_path, count=len(self._fingerprints)
        )

    def import_fingerprints(self, file_path: str, merge: bool = True) -> int:
        """Import fingerprints from file.

        Args:
            file_path: Import file path
            merge: Whether to merge with existing fingerprints

        Returns:
            Number of fingerprints imported
        """
        with open(file_path, "r") as f:
            imported_data = json.load(f)

        if not merge:
            self._fingerprints = {}

        count = 0
        for key, entry in imported_data.items():
            if key not in self._fingerprints or not merge:
                self._fingerprints[key] = entry
                count += 1

        self._save_fingerprints()

        logger.info("Fingerprints imported", file_path=file_path, count=count)
        return count

    def get_statistics(self) -> Dict[str, Any]:
        """Get fingerprint storage statistics.

        Returns:
            Statistics dictionary
        """
        total = len(self._fingerprints)
        hosts = set(entry["host"] for entry in self._fingerprints.values())

        algorithms = {"sha256": 0, "sha1": 0, "md5": 0}
        for entry in self._fingerprints.values():
            fp_data = entry["fingerprint"]
            if "sha256" in fp_data:
                algorithms["sha256"] += 1
            if "sha1" in fp_data:
                algorithms["sha1"] += 1
            if "md5" in fp_data:
                algorithms["md5"] += 1

        return {
            "total_fingerprints": total,
            "unique_hosts": len(hosts),
            "algorithms": algorithms,
            "storage_path": self.storage_path,
        }
