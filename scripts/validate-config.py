#!/usr/bin/env python3
"""Configuration validation for the Gopher & Gemini MCP Server.

Checks the environment variables the server actually reads, against the bounds
``src/gopher_mcp/config.py`` actually enforces, and flags variables that look
like configuration but are silently ignored.

Usage::

    python scripts/validate-config.py             # validate the environment
    python scripts/validate-config.py .env        # validate an env file
    python scripts/validate-config.py config/example.env

An env file is parsed the way the server reads one (``KEY=value`` lines, ``#``
comments); real environment variables take precedence over it, matching
pydantic-settings' own ordering. The script deliberately has no imports outside
the standard library so it can be run before the package is installed.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

# Accepted spellings for a boolean, matching pydantic's own parsing.
BOOLEAN_VALUES = {
    "true",
    "false",
    "1",
    "0",
    "yes",
    "no",
    "on",
    "off",
    "t",
    "f",
    "y",
    "n",
}

LOG_LEVELS = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}


class Spec:
    """One environment variable the server reads.

    Bounds mirror the Field constraints in ``src/gopher_mcp/config.py``; keep the
    two in step when a bound changes there.
    """

    def __init__(
        self,
        name: str,
        kind: str,
        *,
        minimum: float | None = None,
        maximum: float | None = None,
        exclusive_min: float | None = None,
        note: str = "",
    ) -> None:
        self.name = name
        self.kind = kind
        self.minimum = minimum
        self.maximum = maximum
        self.exclusive_min = exclusive_min
        self.note = note


def _protocol_specs(prefix: str, default_port_example: str) -> list[Spec]:
    """Build the specs shared by both protocol namespaces."""
    return [
        Spec(f"{prefix}MAX_RESPONSE_SIZE", "int", minimum=1024, maximum=104857600),
        Spec(f"{prefix}TIMEOUT_SECONDS", "float", exclusive_min=0, maximum=300),
        Spec(f"{prefix}CACHE_ENABLED", "bool"),
        Spec(
            f"{prefix}CACHE_TTL_SECONDS",
            "int",
            minimum=0,
            maximum=86400,
            note="0 disables caching entirely",
        ),
        Spec(f"{prefix}MAX_CACHE_ENTRIES", "int", minimum=1, maximum=100000),
        Spec(f"{prefix}ALLOWED_HOSTS", "host_list"),
        Spec(f"{prefix}ALLOW_LOCAL_HOSTS", "bool"),
        Spec(
            f"{prefix}ALLOWED_PORTS",
            "port_list",
            note=f"e.g. {default_port_example}",
        ),
        Spec(f"{prefix}MAX_RENDERED_CHARS", "int", minimum=0, maximum=10485760),
        Spec(f"{prefix}REQUESTS_PER_MINUTE", "float", minimum=0, maximum=6000),
        Spec(f"{prefix}MAX_CONCURRENT_REQUESTS", "int", minimum=0, maximum=1000),
        Spec(f"{prefix}RESPECT_ROBOTS_TXT", "bool"),
        Spec(f"{prefix}ROBOTS_CACHE_TTL_SECONDS", "int", minimum=0, maximum=604800),
        Spec(f"{prefix}ROBOTS_HONOR_AI_TOKENS", "bool"),
        Spec(
            f"{prefix}ROBOTS_FAILURE_BACKOFF_SECONDS",
            "float",
            minimum=0,
            maximum=3600,
        ),
    ]


SPECS: list[Spec] = [
    *_protocol_specs("GOPHER_", "70"),
    Spec("GOPHER_MAX_SELECTOR_LENGTH", "int", minimum=1, maximum=65536),
    Spec("GOPHER_MAX_SEARCH_LENGTH", "int", minimum=1, maximum=4096),
    Spec("GOPHER_MAX_MENU_ITEMS", "int", minimum=0, maximum=1000000),
    *_protocol_specs("GEMINI_", "1965"),
    Spec("GEMINI_TOFU_ENABLED", "bool"),
    Spec("GEMINI_TOFU_REJECT_EXPIRED", "bool"),
    Spec("GEMINI_CLIENT_CERTS_ENABLED", "bool"),
    Spec("GEMINI_TOFU_STORAGE_PATH", "file_path"),
    Spec("GEMINI_CLIENT_CERTS_STORAGE_PATH", "dir_path"),
    Spec("GEMINI_DENIED_MIME_TYPES", "mime_list"),
    Spec("GOPHER_MCP_LOG_LEVEL", "log_level"),
    Spec("GOPHER_MCP_STRUCTURED_LOGGING", "bool"),
    Spec("GOPHER_MCP_LOG_FILE_PATH", "file_path"),
]

KNOWN_NAMES = {spec.name for spec in SPECS}

# Variables people set expecting them to do something. They are ignored: either
# the setting never existed, or the real name carries a prefix.
IGNORED_NAMES: dict[str, str] = {
    "GEMINI_TLS_VERSION": (
        "TLS 1.2 is the enforced minimum, fixed in code and not configurable"
    ),
    "GEMINI_TLS_VERIFY_HOSTNAME": (
        "server identity is verified by TOFU, not hostname/CA-chain checks"
    ),
    "GEMINI_TLS_CLIENT_CERT_PATH": (
        "client certificates are managed under "
        "GEMINI_CLIENT_CERTS_STORAGE_PATH; there is no external cert/key setting"
    ),
    "GEMINI_TLS_CLIENT_KEY_PATH": (
        "client certificates are managed under "
        "GEMINI_CLIENT_CERTS_STORAGE_PATH; there is no external cert/key setting"
    ),
    "GEMINI_CLIENT_CERT_STORAGE_PATH": "did you mean GEMINI_CLIENT_CERTS_STORAGE_PATH?",
    "MAX_REDIRECTS": "redirects are returned to the caller, never followed automatically",
    "MAX_CONCURRENT_CONNECTIONS": (
        "did you mean GOPHER_MAX_CONCURRENT_REQUESTS / GEMINI_MAX_CONCURRENT_REQUESTS?"
    ),
    "STRICT_HOST_VALIDATION": "use GOPHER_ALLOWED_HOSTS / GEMINI_ALLOWED_HOSTS",
    "DEVELOPMENT_MODE": "no such setting; raise GOPHER_MCP_LOG_LEVEL instead",
    "LOG_LEVEL": "did you mean GOPHER_MCP_LOG_LEVEL?",
    "STRUCTURED_LOGGING": "did you mean GOPHER_MCP_STRUCTURED_LOGGING?",
    "LOG_FILE_PATH": "did you mean GOPHER_MCP_LOG_FILE_PATH?",
}


def parse_env_file(path: Path) -> dict[str, str]:
    """Read ``KEY=value`` lines from an env file, ignoring comments and blanks."""
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def split_list_value(value: str) -> list[str]:
    """Split a list-valued variable, accepting JSON arrays and commas.

    Mirrors ``gopher_mcp.config._split_list_value``.
    """
    stripped = value.strip()
    if stripped.startswith("["):
        decoded = json.loads(stripped)
        return [str(item).strip() for item in decoded if str(item).strip()]
    return [entry.strip() for entry in stripped.split(",") if entry.strip()]


class ConfigValidator:
    """Validates configuration settings for the MCP server."""

    def __init__(self, values: dict[str, str], source: str) -> None:
        self.values = values
        self.source = source
        self.errors: list[str] = []
        self.warnings: list[str] = []

    def validate_all(self) -> bool:
        """Validate every setting and report the outcome."""
        print("🔍 Validating Gopher & Gemini MCP Server Configuration...")
        print(f"   Source: {self.source}")
        print()

        print("📡 Validating Gopher configuration...")
        self._validate_prefix("GOPHER_", skip_prefix="GOPHER_MCP_")
        print("🔐 Validating Gemini configuration...")
        self._validate_prefix("GEMINI_")
        print("📝 Validating server and logging configuration...")
        self._validate_prefix("GOPHER_MCP_")
        print("🛡️ Checking for ignored variables...")
        self._check_ignored()

        self._report_results()
        return not self.errors

    def _validate_prefix(self, prefix: str, skip_prefix: str | None = None) -> None:
        for spec in SPECS:
            if not spec.name.startswith(prefix):
                continue
            if skip_prefix and spec.name.startswith(skip_prefix):
                continue
            if spec.name in self.values:
                self._validate(spec, self.values[spec.name])

    def _check_ignored(self) -> None:
        for name, reason in IGNORED_NAMES.items():
            if name in self.values:
                self.warnings.append(f"{name} is not read by the server ({reason})")
        for name in sorted(self.values):
            if name in KNOWN_NAMES or name in IGNORED_NAMES:
                continue
            if name.startswith(("GOPHER_", "GEMINI_")):
                self.warnings.append(
                    f"{name} is not a recognized setting and will be ignored"
                )

    def _validate(self, spec: Spec, value: str) -> None:
        """Dispatch to the checker for this spec's kind."""
        getattr(self, f"_validate_{spec.kind}")(spec, value)

    def _range_error(self, spec: Spec, value: Any) -> None:
        if spec.exclusive_min is not None:
            bounds = f"greater than {spec.exclusive_min} and at most {spec.maximum}"
        else:
            bounds = f"between {spec.minimum} and {spec.maximum}"
        suffix = f" ({spec.note})" if spec.note else ""
        self.errors.append(f"{spec.name} must be {bounds}, got: {value}{suffix}")

    def _in_range(self, spec: Spec, value: float) -> bool:
        if spec.exclusive_min is not None and value <= spec.exclusive_min:
            return False
        if spec.minimum is not None and value < spec.minimum:
            return False
        return not (spec.maximum is not None and value > spec.maximum)

    def _validate_int(self, spec: Spec, value: str) -> None:
        try:
            parsed = int(value)
        except ValueError:
            self.errors.append(f"{spec.name} must be a valid integer, got: {value!r}")
            return
        if not self._in_range(spec, parsed):
            self._range_error(spec, parsed)

    def _validate_float(self, spec: Spec, value: str) -> None:
        try:
            parsed = float(value)
        except ValueError:
            self.errors.append(f"{spec.name} must be a valid number, got: {value!r}")
            return
        if not self._in_range(spec, parsed):
            self._range_error(spec, parsed)

    def _validate_bool(self, spec: Spec, value: str) -> None:
        if value.strip().lower() not in BOOLEAN_VALUES:
            self.errors.append(
                f"{spec.name} must be a boolean value "
                f"(true/false, 1/0, yes/no, on/off), got: {value!r}"
            )

    def _entries(self, spec: Spec, value: str) -> list[str] | None:
        """Split a list value, or record why it cannot be used."""
        if not value.strip():
            # Unset or empty means "no restriction"; nothing to check.
            return None
        try:
            entries = split_list_value(value)
        except json.JSONDecodeError:
            self.errors.append(
                f"{spec.name} looks like a JSON array but is not valid JSON: {value!r}"
            )
            return None
        if not entries:
            self.errors.append(
                f"{spec.name} is set to {value!r} but names no entries; unset it "
                "instead — an empty allowlist cannot be told apart from an absent "
                "one, so the server refuses to start"
            )
            return None
        return entries

    def _validate_host_list(self, spec: Spec, value: str) -> None:
        # A malformed hostname is a warning, not an error: the server accepts the
        # allowlist and simply never matches that entry, so reporting it as a
        # startup failure would be wrong.
        entries = self._entries(spec, value)
        for host in entries or []:
            if not self._is_valid_hostname(host):
                self.warnings.append(
                    f"{spec.name} contains a hostname that can never match: {host!r}"
                )

    def _validate_port_list(self, spec: Spec, value: str) -> None:
        entries = self._entries(spec, value)
        for entry in entries or []:
            try:
                port = int(entry)
            except ValueError:
                self.errors.append(
                    f"{spec.name} contains a non-numeric port: {entry!r}"
                )
                continue
            if not 1 <= port <= 65535:
                self.errors.append(
                    f"{spec.name} port must be between 1 and 65535: {port}"
                )

    def _validate_mime_list(self, spec: Spec, value: str) -> None:
        # An empty deny list is legitimate (no filtering), so only the JSON
        # spelling can fail here.
        if value.strip().startswith("["):
            try:
                split_list_value(value)
            except json.JSONDecodeError:
                self.errors.append(
                    f"{spec.name} looks like a JSON array but is not valid JSON: "
                    f"{value!r}"
                )
                return
        for entry in [e.strip() for e in value.split(",") if e.strip()]:
            if "/" not in entry:
                self.warnings.append(
                    f"{spec.name} entry {entry!r} is not a type/subtype or type/* "
                    "pattern and will never match"
                )

    def _validate_file_path(self, spec: Spec, value: str) -> None:
        # A blank value means "unset, use the default", exactly as the server
        # reads it (config._blank_path_is_unset). There is nothing to check.
        if not value.strip():
            return
        path = Path(value).expanduser()
        if path.is_dir():
            self.errors.append(
                f"{spec.name} points to a directory, expected a file: {value}"
            )
        elif not path.parent.exists():
            self.warnings.append(
                f"{spec.name} parent directory does not exist: {path.parent}"
            )

    def _validate_dir_path(self, spec: Spec, value: str) -> None:
        # As above: blank means "use the default", not the current directory.
        if not value.strip():
            return
        path = Path(value).expanduser()
        if path.exists() and not path.is_dir():
            self.errors.append(
                f"{spec.name} points to an existing file, expected a directory: {value}"
            )
        elif not path.exists() and not path.parent.exists():
            self.warnings.append(
                f"{spec.name} parent directory does not exist: {path.parent}"
            )

    def _validate_log_level(self, spec: Spec, value: str) -> None:
        if value.strip().upper() not in LOG_LEVELS:
            self.errors.append(
                f"{spec.name} must be one of: {', '.join(sorted(LOG_LEVELS))}, "
                f"got: {value!r}"
            )

    def _is_valid_hostname(self, hostname: str) -> bool:
        """Check if hostname is roughly valid."""
        if not hostname or len(hostname) > 253:
            return False
        if hostname.startswith("."):
            return False
        allowed = set(
            "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789.-:[]"
        )
        return all(c in allowed for c in hostname)

    def _report_results(self) -> None:
        """Report validation results."""
        print()
        print("=" * 60)
        print("📊 VALIDATION RESULTS")
        print("=" * 60)

        if self.errors:
            print(f"❌ {len(self.errors)} ERROR(S) FOUND:")
            for i, error in enumerate(self.errors, 1):
                print(f"  {i}. {error}")
            print()

        if self.warnings:
            print(f"⚠️  {len(self.warnings)} WARNING(S) FOUND:")
            for i, warning in enumerate(self.warnings, 1):
                print(f"  {i}. {warning}")
            print()

        if not self.errors and not self.warnings:
            print("✅ All configuration settings are valid!")
        elif not self.errors:
            print("✅ Configuration is valid (with warnings)")
        else:
            print("❌ Configuration validation failed")

        print()
        print("💡 TIP: See config/example.env for every variable and its default")
        print("📖 DOC: See docs/configuration.md for types, ranges and defaults")


def collect_values(env_file: Path | None) -> tuple[dict[str, str], str]:
    """Gather the settings to check, and describe where they came from."""
    relevant = KNOWN_NAMES | set(IGNORED_NAMES)
    values: dict[str, str] = {}
    sources: list[str] = []

    if env_file is not None:
        values.update(parse_env_file(env_file))
        sources.append(str(env_file))

    # Process environment wins, as it does for pydantic-settings.
    from_environ = {
        name: value
        for name, value in os.environ.items()
        if name in relevant or name.startswith(("GOPHER_", "GEMINI_"))
    }
    if from_environ:
        values.update(from_environ)
        sources.append("process environment")

    return values, " + ".join(
        sources
    ) if sources else "process environment (nothing set)"


def main() -> None:
    """Main entry point."""
    args = sys.argv[1:]
    if args and args[0] in {"-h", "--help"}:
        print(__doc__)
        sys.exit(0)

    env_file: Path | None = None
    if args:
        env_file = Path(args[0])
        if not env_file.is_file():
            print(f"❌ No such env file: {env_file}")
            sys.exit(2)
    elif Path(".env").is_file():
        env_file = Path(".env")

    values, source = collect_values(env_file)
    validator = ConfigValidator(values, source)
    sys.exit(0 if validator.validate_all() else 1)


if __name__ == "__main__":
    main()
