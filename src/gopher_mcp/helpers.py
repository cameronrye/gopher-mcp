"""Shared URL and filesystem helpers for the gopher-mcp protocol modules.

These low-level utilities have no dependency on the project's models or parsers,
so they sit at the bottom of the import graph and can be imported freely by the
parser modules without risking a cycle.
"""

import contextlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse, urlsplit, urlunsplit

# Whitespace that carries meaning in a multi-line body and therefore survives
# ``sanitize_display_text`` even though it is not "printable".
_MEANINGFUL_WHITESPACE = ("\n", "\t", "\r")


def atomic_write_json(file_path: str, data: Any) -> None:
    """Atomically write JSON data to a file.

    This function writes to a temporary file first, then renames it to the target
    path. On Windows, it handles the case where the target file already exists.

    Args:
        file_path: Target file path
        data: Data to write as JSON

    Raises:
        Exception: If the write operation fails
    """
    # Ensure directory exists
    Path(file_path).parent.mkdir(parents=True, exist_ok=True)

    # Create temporary file in the same directory as the target. Capture its
    # path first so the cleanup below can always reach it -- every fallible step
    # after creation (json.dump, flush, fsync, rename, chmod, dir fsync) runs
    # inside the single try whose ``except`` unlinks the temp file, so a failure
    # mid-write (e.g. ENOSPC surfacing on flush/fsync) can't orphan a .tmp file.
    temp_dir = Path(file_path).parent
    temp_path: str | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", dir=temp_dir, delete=False, suffix=".tmp"
        ) as temp_file:
            temp_path = temp_file.name
            json.dump(data, temp_file, indent=2)
            # Durability: force the bytes to stable storage BEFORE the rename.
            # ``rename`` is atomic only for *visibility* -- without the fsync a
            # crash/power-loss after the rename can leave a zero-length or
            # truncated file, which the deliberately fail-closed TOFU loader then
            # refuses to start with. Flush the Python buffer, then the OS buffer.
            temp_file.flush()
            os.fsync(temp_file.fileno())

        # On Windows, we need to remove the target file first if it exists
        if os.name == "nt" and Path(file_path).exists():
            Path(file_path).unlink()

        # Rename temporary file to target
        Path(temp_path).rename(file_path)
        # Make the destination owner-only. These files (TOFU store, client-cert
        # registry) are integrity-sensitive, so don't rely solely on the parent
        # dir's 0700 (whose chmod is best-effort). No-op / harmless on Windows.
        with contextlib.suppress(OSError):
            Path(file_path).chmod(0o600)
        # fsync the directory so the rename itself is durable (POSIX). Best
        # effort: not supported on every platform/FS, and a no-op on Windows.
        with contextlib.suppress(OSError, AttributeError):
            dir_fd = os.open(str(temp_dir), os.O_RDONLY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
    except Exception:
        # Clean up the temp file on any failure (ignore cleanup failures so the
        # original error is preserved). After a successful rename temp_path no
        # longer exists, so the unlink is a harmless no-op.
        if temp_path is not None:
            with contextlib.suppress(Exception):
                Path(temp_path).unlink()
        raise


def bracket_host(host: str) -> str:
    """Wrap an IPv6 literal host in brackets for use in a URL authority.

    RFC 3986 requires an IPv6 address in a URL to be enclosed in ``[...]`` so
    its colons are not confused with the host:port separator. A bare IPv4
    address or registered name (already bracketed or containing no colon) is
    returned unchanged.
    """
    if ":" in host and not host.startswith("["):
        return f"[{host}]"
    return host


def sanitize_display_text(text: str, *, keep_whitespace: bool = True) -> str:
    """Strip non-printable characters from server-supplied text bound for the LLM.

    Every string a remote gopher/gemini server controls -- menu titles, decoded
    bodies, gemtext link labels, a Gemini ``<META>`` -- reaches the model (and
    often a terminal) verbatim. ANSI escapes (CSI/OSC), NUL and other C0/C1
    control characters in that text are a display-injection vector, so drop them
    everywhere rather than at individual call sites.

    Args:
        text: Raw server-supplied text.
        keep_whitespace: Preserve ``\\n``, ``\\t`` and ``\\r``. True for
            multi-line bodies whose line structure is meaningful; False for a
            single field (a menu title, a ``<META>``) where they are noise.

    Returns:
        ``text`` with every non-printable character removed.

    """
    allowed = _MEANINGFUL_WHITESPACE if keep_whitespace else ()
    return "".join(char for char in text if char.isprintable() or char in allowed)


def resolve_gemini_reference(base_url: str, target: str) -> str:
    """Resolve a (possibly relative) Gemini reference against ``base_url``.

    ``urllib.parse.urljoin`` doesn't treat ``gemini`` as a hierarchical scheme,
    so relative references would pass through unresolved. Resolve under an
    ``https`` placeholder (which urljoin understands) and swap the scheme back.
    An absolute reference that carries its own scheme (gemini://, https://,
    mailto:, ...) is returned unchanged so the caller/SSRF layer can inspect
    cross-scheme or cross-host targets.

    Args:
        base_url: The URL the reference was found in.
        target: The (absolute or relative) reference to resolve.

    Returns:
        The absolute form of ``target``.

    """
    if urlparse(target).scheme:  # already absolute
        return target

    if not base_url.startswith("gemini://"):
        return urljoin(base_url, target)

    placeholder_base = "https://" + base_url[len("gemini://") :]
    joined = urljoin(placeholder_base, target)
    if joined.startswith("https://"):
        return "gemini://" + joined[len("https://") :]
    return joined


def normalize_cache_key(url: str) -> str:
    """Canonicalize a URL for use as a cache key.

    Hostnames are case-insensitive (RFC 3986), so requests differing only in
    host case must map to the same entry instead of duplicating it. Lowercase
    only the authority (host/port -- ports are digits, unaffected) and leave the
    path/query byte-for-byte intact, since selectors and queries ARE
    case-sensitive. An already-lowercase URL is returned unchanged.
    """
    parts = urlsplit(url)
    return urlunsplit(
        (parts.scheme, parts.netloc.lower(), parts.path, parts.query, parts.fragment)
    )


def get_home_directory() -> Path | None:
    """Get the user's home directory with fallback handling.

    Returns:
        Path to home directory or None if it cannot be determined
    """
    try:
        return Path.home()
    except Exception:
        # Fallback to environment variables
        home = os.environ.get("HOME") or os.environ.get("USERPROFILE")
        if home:
            return Path(home)
        return None


def truncate_text(text: str, max_chars: int) -> tuple[str, bool]:
    """Truncate ``text`` to an LLM-facing character budget.

    Distinct from the network response-size cap: a 1 MB text page is well under
    the byte limit yet still ~250k tokens. Returns ``(text, truncated)``; a
    ``max_chars`` of 0 means unlimited (the truncation is opt-out).
    """
    if max_chars and len(text) > max_chars:
        return text[:max_chars], True
    return text, False
