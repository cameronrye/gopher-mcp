"""Backward-compatible facade for the gopher-mcp utility modules.

The implementations live in focused submodules -- ``helpers`` (shared URL/IO
helpers), ``mime`` (MIME guessing/detection), ``gemtext`` (gemtext parsing),
``gopher_parse`` (gopher URL/menu parsing) and ``gemini_parse`` (gemini
URL/response parsing). Every public name is re-exported here so that
``from gopher_mcp.utils import X`` keeps working unchanged.
"""

# ``os`` stays importable from this module so the suite can keep patching
# ``gopher_mcp.utils.os.fsync`` -- the durability fsync used by
# ``atomic_write_json``, which now lives in ``helpers``.
import os  # noqa: F401

from .gemini_parse import (
    format_gemini_url,
    parse_gemini_response,
    parse_gemini_url,
    process_gemini_response,
    validate_gemini_url_components,
)
from .gemtext import parse_gemtext
from .gopher_parse import (
    format_gopher_url,
    gopher_type_category,
    parse_gopher_menu,
    parse_gopher_url,
    parse_menu_line,
    sanitize_selector,
)
from .helpers import (
    atomic_write_json,
    bracket_host,
    get_home_directory,
    normalize_cache_key,
    truncate_text,
)
from .mime import (
    detect_binary_mime_type,
    get_default_gemini_mime_type,
    guess_mime_type,
    mime_is_denied,
    parse_gemini_mime_type,
    validate_gemini_mime_type,
)

__all__ = [
    "atomic_write_json",
    "bracket_host",
    "detect_binary_mime_type",
    "format_gemini_url",
    "format_gopher_url",
    "get_default_gemini_mime_type",
    "get_home_directory",
    "gopher_type_category",
    "guess_mime_type",
    "mime_is_denied",
    "normalize_cache_key",
    "parse_gemini_mime_type",
    "parse_gemini_response",
    "parse_gemini_url",
    "parse_gemtext",
    "parse_gopher_menu",
    "parse_gopher_url",
    "parse_menu_line",
    "process_gemini_response",
    "sanitize_selector",
    "truncate_text",
    "validate_gemini_mime_type",
    "validate_gemini_url_components",
]
