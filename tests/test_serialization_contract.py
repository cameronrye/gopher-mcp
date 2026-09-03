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

# Expected serialized keys = declared fields (minus any marked exclude=True) plus
# computed fields -- what model_dump() emits without ``by_alias=True``, which is
# how the tools serialize results.
# Cache provenance, carried only by the result kinds the clients cache. Errors,
# redirects and the input/certificate prompts are never cached, so they must NOT
# grow these keys -- three permanently-null fields on every failure is noise the
# model pays for on every call.
CACHE_KEYS = {"cached", "cached_at", "cache_age_seconds"}
# The continuation contract, carried by the result kinds a render limit can cut
# so a truncated result is not a dead end. A menu counts items, so it names its
# total `total_items` instead.
CONTINUATION_KEYS = {"total_chars", "next_offset"}

EXPECTED_KEYS: dict[str, set[str]] = {
    # Gopher result models
    "GopherMenuItem": {"type", "title", "selector", "host", "port", "next_url"},
    "MenuResult": {"kind", "items", "truncated", "request_info"}
    | CACHE_KEYS
    | {"total_items", "next_offset"},
    "TextResult": {"kind", "charset", "bytes", "text", "truncated", "request_info"}
    | CACHE_KEYS
    | CONTINUATION_KEYS,
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
    | CACHE_KEYS
    | CONTINUATION_KEYS,
    "GeminiBinaryResult": {
        "kind",
        "mime_type",
        "size",
        "note",
        "request_info",
    }
    | CACHE_KEYS,
    "GeminiInputResult": {"kind", "prompt", "sensitive", "request_info"},
    "GeminiRedirectResult": {
        "kind",
        "new_url",
        "permanent",
        "cross_host",
        "scheme",
        "request_info",
    },
    "GeminiErrorResult": {"kind", "error", "request_info"},
    "GeminiCertificateResult": {
        "kind",
        "message",
        "status",
        "required",
        "next_step",
        "request_info",
    },
    # `raw_content` is declared but excluded from serialization: the parsed
    # document already carries every line, so shipping the whole page again was
    # a third of the payload. It stays reachable as an attribute (the robots.txt
    # reader parses it), which is why it must NOT appear here.
    "GeminiGemtextResult": {
        "kind",
        "document",
        "charset",
        "lang",
        "size",
        "truncated",
        # Gemtext-only: says this window is the middle of one over-long line, so
        # a caller joins it to the next window's first line instead of reading
        # the two as separate lines.
        "partial_line",
        "request_info",
    }
    | CACHE_KEYS
    | CONTINUATION_KEYS,
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
    # The on-disk record. It is never a result itself -- tofu.json is written
    # from its model_dump(), so its epoch timestamps must stay floats.
    "TOFUEntry": {
        "host",
        "port",
        "fingerprint",
        "first_seen",
        "last_seen",
        "expires",
    },
    # ...and the projection of it that gemini_trust_list actually reports, with
    # ISO-8601 timestamps matching the client-certificate tools.
    "TOFUTrustEntry": {
        "host",
        "port",
        "fingerprint",
        "first_seen",
        "last_seen",
        "expires",
        "expired",
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
    # One fact per field, all on the line: the nested heading/list_item/quote/
    # preformat objects were dropped because each repeated this line's raw
    # `content` under a second name.
    "GemtextLine": {
        "type",
        "content",
        "text",
        "link",
        "level",
        "alt_text",
        "language",
    },
    "GemtextLink": {"url", "text"},
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
    # A field marked exclude=True is declared but never serialized, so it is not
    # part of the wire contract -- the point of marking it.
    serialized = {
        name for name, field in model.model_fields.items() if not field.exclude
    } | set(model.model_computed_fields)
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


def test_gemtext_result_does_not_ship_the_body_twice() -> None:
    """`raw_content` stays readable in-process but never reaches the payload.

    Every line of it is already in ``document.lines[*].content``; emitting it
    again made the whole page a third of the tool output. The attribute has to
    survive because the robots.txt reader parses a text/gemini policy out of it.
    """
    document = models.GemtextDocument(
        lines=[
            models.GemtextLine(type=models.GemtextLineType.TEXT, content="Hello"),
        ],
        links=[],
    )
    result = models.GeminiGemtextResult(
        document=document, rawContent="Hello", size=5, requestInfo={}
    )

    assert result.raw_content == "Hello"
    assert "raw_content" not in result.model_dump()
    assert "rawContent" not in result.model_dump(by_alias=True)
