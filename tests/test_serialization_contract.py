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

from gopher_mcp import models

# Expected serialized keys = declared fields + computed fields (what model_dump()
# emits without ``by_alias=True``, which is how the tools serialize results).
EXPECTED_KEYS: dict[str, set[str]] = {
    # Gopher result models
    "GopherMenuItem": {"type", "title", "selector", "host", "port", "next_url"},
    "MenuResult": {"kind", "items", "truncated", "request_info"},
    "TextResult": {"kind", "charset", "bytes", "text", "truncated", "request_info"},
    "BinaryResult": {"kind", "bytes", "mime_type", "note", "request_info"},
    "ErrorResult": {"kind", "error", "request_info"},
    # Gemini result models
    "GeminiSuccessResult": {
        "kind",
        "mime_type",
        "content",
        "size",
        "truncated",
        "request_info",
    },
    "GeminiInputResult": {"kind", "prompt", "sensitive", "request_info"},
    "GeminiRedirectResult": {"kind", "new_url", "permanent", "request_info"},
    "GeminiErrorResult": {"kind", "error", "request_info"},
    "GeminiCertificateResult": {
        "kind",
        "message",
        "status",
        "required",
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
