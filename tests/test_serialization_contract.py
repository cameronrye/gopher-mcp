"""Serialization-contract tests for the public result models.

The MCP tools return ``model_dump()`` dicts (field names, no aliases), and the
documentation examples access those dicts by key. These tests pin the serialized
key set of every public result/content model so that a field rename or addition
fails loudly here — a reminder to update the docs (and any consumers) alongside
the code. If you intentionally change a model's shape, update the expected set
below and the corresponding documentation/examples.
"""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from gopher_mcp import models

# Expected serialized keys = declared fields + computed fields (what model_dump()
# emits without ``by_alias=True``, which is how the tools serialize results).
# Cache provenance, carried only by the result kinds the clients cache. Errors,
# redirects and the input/certificate prompts are never cached, so they must NOT
# grow these keys -- three permanently-null fields on every failure is noise the
# model pays for on every call.
CACHE_KEYS = {"cached", "cached_at", "cache_age_seconds"}

EXPECTED_KEYS: dict[str, set[str]] = {
    # Gopher result models
    "GopherMenuItem": {"type", "title", "selector", "host", "port", "next_url"},
    "MenuResult": {"kind", "items", "truncated", "request_info"} | CACHE_KEYS,
    "TextResult": {"kind", "charset", "bytes", "text", "truncated", "request_info"}
    | CACHE_KEYS,
    "BinaryResult": {"kind", "bytes", "mime_type", "note", "request_info"} | CACHE_KEYS,
    "ErrorResult": {"kind", "error", "request_info"},
    # Gemini result models
    "GeminiSuccessResult": {
        "kind",
        "mime_type",
        "content",
        "size",
        "truncated",
        "request_info",
    }
    | CACHE_KEYS,
    "GeminiBinaryResult": {
        "kind",
        "mime_type",
        "size",
        "note",
        "request_info",
    }
    | CACHE_KEYS,
    "GeminiInputResult": {"kind", "prompt", "sensitive", "request_info"},
    "GeminiRedirectResult": {"kind", "new_url", "permanent", "request_info"},
    "GeminiErrorResult": {"kind", "error", "request_info"},
    "GeminiCertificateResult": {
        "kind",
        "message",
        "status",
        "required",
        "next_step",
        "request_info",
    },
    "GeminiGemtextResult": {
        "kind",
        "document",
        "raw_content",
        "charset",
        "lang",
        "size",
        "truncated",
        "request_info",
    }
    | CACHE_KEYS,
    # Trust-store tool results
    "TOFUTrustListResult": {"kind", "entries", "request_info"},
    "TOFUTrustUpdateResult": {
        "kind",
        "action",
        "host",
        "port",
        "changed",
        "message",
        "request_info",
    },
    "TOFUEntry": {
        "host",
        "port",
        "fingerprint",
        "first_seen",
        "last_seen",
        "expires",
    },
    # Client-certificate tool results
    "GeminiClientCertListResult": {"kind", "entries", "request_info"},
    "GeminiClientCertUpdateResult": {
        "kind",
        "action",
        "host",
        "port",
        "path",
        "fingerprint",
        "expires",
        "changed",
        "message",
        "request_info",
    },
    # A projection of GeminiCertificateInfo, not the whole of it: the stored
    # entry also carries the certificate's subject (which names its key pair on
    # disk) and its issuer, and neither may reach a model.
    "GeminiClientCertificateEntry": {
        "url",
        "host",
        "port",
        "path",
        "fingerprint",
        "not_before",
        "not_after",
        "expired",
    },
    # Gemtext content models
    "GemtextDocument": {"lines", "links"},
    "GemtextLine": {
        "type",
        "content",
        "link",
        "level",
        "alt_text",
        "heading",
        "list_item",
        "quote",
        "preformat",
    },
    "GemtextLink": {"url", "text"},
    "GemtextHeading": {"level", "text", "raw_content"},
    # MIME type model (nested under GeminiSuccessResult.mime_type)
    "GeminiMimeType": {"type", "subtype", "charset", "lang"},
}


# Plain (non-computed) properties on the content models. These never appear in
# model_dump(), so the LLM never sees them: each one only earns its place by
# having a caller in ``src/``. Pinned here so an unused analysis helper cannot
# quietly accumulate again.
EXPECTED_PROPERTIES: dict[str, set[str]] = {
    "GeminiMimeType": {"full_type", "is_text", "is_gemtext", "is_binary"},
    "GemtextDocument": set(),
    "GemtextLink": set(),
    "GemtextLine": set(),
}


@pytest.mark.parametrize("model_name", sorted(EXPECTED_KEYS))
def test_serialized_keys_match_contract(model_name: str) -> None:
    """The model's serialized key set matches the documented contract."""
    model = getattr(models, model_name)
    serialized = set(model.model_fields) | set(model.model_computed_fields)
    assert serialized == EXPECTED_KEYS[model_name], (
        f"{model_name} serialized keys changed: "
        f"unexpected={serialized - EXPECTED_KEYS[model_name]}, "
        f"missing={EXPECTED_KEYS[model_name] - serialized}. "
        "Update EXPECTED_KEYS and the docs/examples that reference these fields."
    )


@pytest.mark.parametrize("model_name", sorted(EXPECTED_PROPERTIES))
def test_non_serialized_properties_have_production_callers(model_name: str) -> None:
    """The model's plain properties match the set production code actually uses."""
    model = getattr(models, model_name)
    properties = {
        name
        for name in dir(model)
        if not name.startswith("_")
        and isinstance(getattr(model, name, None), property)
        # BaseModel's own properties (model_extra, model_fields_set) are not ours.
        and not hasattr(BaseModel, name)
    }
    assert properties == EXPECTED_PROPERTIES[model_name], (
        f"{model_name} properties changed: "
        f"unexpected={properties - EXPECTED_PROPERTIES[model_name]}, "
        f"missing={EXPECTED_PROPERTIES[model_name] - properties}. "
        "A property is invisible to model_dump(), so add one only with a caller "
        "in src/ (and list it here)."
    )
