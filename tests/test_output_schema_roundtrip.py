"""Every result model must validate against the output schema its tool advertises.

The MCP SDK does not merely publish ``outputSchema``: it validates the payload a
tool returns back through the corresponding output model. So a result model can
be individually correct, serialize cleanly, and still break every call, because
the shape that comes out of ``model_dump()`` is not a shape the output model
accepts.

That is not hypothetical. Collapsing the duplicated gemtext payload left
``GeminiGemtextResult.raw_content`` required but ``exclude=True``: present on
the object, absent from the dump. Nothing in the unit tests noticed, because
each side was self-consistent, and every ``gemini_fetch`` that returned gemtext
failed with "raw_content Field required" instead of a page.

These tests close the round trip for the whole union, so any future field whose
serialization and validation rules disagree fails here rather than at a caller.

There are TWO validators in that path, though, and they do not agree with each
other. Pydantic's is the one above. The one that actually runs at the far end of
a real call is ``jsonschema.validate`` inside the SDK's own ``ClientSession``
(see ``mcp/client/session.py``), run against the advertised ``outputSchema``
rather than the model -- and it neither reads the ``discriminator`` nor sees the
Python objects Pydantic sees. The second half of this file covers that one.
"""

import asyncio
import json
import time
from functools import cache
from typing import Any

import jsonschema
import pytest
from pydantic import BaseModel
from pydantic_core import to_json

from gopher_mcp.models import (
    BinaryResult,
    ErrorResult,
    GeminiBinaryResult,
    GeminiCertificateResult,
    GeminiFetchOutput,
    GeminiFetchResponse,
    GeminiGemtextResult,
    GeminiInputResult,
    GeminiMimeType,
    GeminiRedirectResult,
    GeminiSuccessResult,
    GemtextDocument,
    GemtextLine,
    GemtextLineType,
    GemtextLink,
    GopherFetchOutput,
    GopherFetchResponse,
    GopherMenuItem,
    MenuResult,
    TextResult,
    mark_from_cache,
)
from gopher_mcp.server import mcp


def _variants(model: type[BaseModel]) -> dict[str, Any]:
    """Build a minimally valid instance of ``model``.

    Only fields with no default need a value; anything defaulted is left alone
    so the test exercises the defaults the real code relies on.
    """
    from gopher_mcp.models import GemtextDocument, GemtextLine, GemtextLineType

    samples: dict[str, Any] = {
        "document": GemtextDocument(
            lines=[GemtextLine(type=GemtextLineType.TEXT, content="hello")],
            links=[],
        ),
        "items": [],
        "text": "hello",
        "content": "hello",
        "size": 5,
        "bytes": 5,
        "mime_type": {"type": "text", "subtype": "gemini"},
        "status": 20,
        "prompt": "Search",
        "new_url": "gemini://example.org/moved",
        "message": "something happened",
        "error": {"code": "FETCH_ERROR", "message": "something happened"},
        "url": "gemini://example.org/",
        "entries": [],
        "certificates": [],
    }
    values: dict[str, Any] = {}
    for name, field in model.model_fields.items():
        if field.is_required() and name in samples:
            values[name] = samples[name]
        elif field.is_required():  # pragma: no cover - guards a future field
            pytest.fail(
                f"{model.__name__}.{name} is required and this test has no sample "
                f"value for it. Add one to _variants() so the round trip stays covered."
            )
    return values


def _members(union: Any) -> list[type[BaseModel]]:
    """The concrete models in a result union."""
    from typing import get_args

    return [m for m in get_args(union) if isinstance(m, type)]


@pytest.mark.parametrize(
    ("union", "output_model"),
    [
        (GopherFetchResponse, GopherFetchOutput),
        (GeminiFetchResponse, GeminiFetchOutput),
    ],
    ids=["gopher", "gemini"],
)
def test_every_result_validates_against_its_own_dump(
    union: Any, output_model: type[BaseModel]
) -> None:
    """A dumped result must be accepted by the tool's advertised output model.

    This is exactly the round trip the SDK performs on every tool call, so a
    failure here is a failure of every call that returns that kind.
    """
    for member in _members(union):
        instance = member(**_variants(member))
        dumped = instance.model_dump()
        # by_alias too: the SDK dumps with aliases in some code paths, and the
        # advertised schema is generated from the serialization aliases.
        aliased = instance.model_dump(by_alias=True)
        for payload, label in ((dumped, "model_dump()"), (aliased, "by_alias=True")):
            try:
                output_model.model_validate(payload)
            except Exception as exc:
                pytest.fail(
                    f"{member.__name__} cannot be validated back through "
                    f"{output_model.__name__} from its own {label}: {exc}\n"
                    f"A field that is required but excluded from serialization "
                    f"causes this. Give it a default."
                )


@pytest.mark.parametrize(
    ("union", "output_model"),
    [
        (GopherFetchResponse, GopherFetchOutput),
        (GeminiFetchResponse, GeminiFetchOutput),
    ],
    ids=["gopher", "gemini"],
)
def test_no_result_field_is_both_required_and_excluded(
    union: Any, output_model: type[BaseModel]
) -> None:
    """Name the defect directly, so the failure says what to change.

    The round-trip test above catches this too, but its message describes a
    symptom. This one points at the field.
    """
    for member in _members(union):
        for name, field in member.model_fields.items():
            excluded = getattr(field, "exclude", False)
            assert not (field.is_required() and excluded), (
                f"{member.__name__}.{name} is required but excluded from "
                f"serialization, so a dumped result can never satisfy "
                f"{output_model.__name__}. Give the field a default."
            )


# ---------------------------------------------------------------------------
# The other enforcement path: `jsonschema` against the advertised outputSchema.
#
# The round trip above is the one PYDANTIC performs. It is not the one a client
# performs. The bundled SDK's ClientSession._validate_tool_result (see
# mcp/client/session.py) does, on every non-error call, hand
# `result.structuredContent` and the tool's advertised `output_schema` to
# `jsonschema.validate`. It raises RuntimeError("Invalid structured content
# returned by tool ...") when it fails -- so a payload Pydantic accepts and
# jsonschema rejects is a call that fails at the client, after the fetch had
# already succeeded, for every user of a conforming client. Two differences
# between the two validators make that reachable:
#
# 1. `discriminator` is an OpenAPI keyword. JSON Schema has no such keyword, so
#    jsonschema IGNORES it and enforces the bare `oneOf`, which demands a
#    payload match EXACTLY ONE branch. Pydantic, told the discriminator, only
#    ever tries the one branch `kind` names. If two branches can accept the same
#    payload, Pydantic is happy and a conforming client rejects a valid result.
# 2. Pydantic validates model-first (unknown keys ignored, missing optionals
#    defaulted); jsonschema validates the literal JSON that went over the wire.
#
# The tests above also only ever build MINIMAL instances -- required fields and
# nothing else -- and optional fields are exactly where a schema and a model
# drift apart. So each kind is exercised twice below: bare, and with every
# optional field populated.


@cache
def _advertised_schemas() -> dict[str, dict[str, Any]]:
    """The ``outputSchema`` of every registered tool, as a client is handed it.

    Taken from the server's own ``list_tools()`` rather than rebuilt from the
    models, because the point of these tests is the schema that actually goes
    out on the wire: anything FastMCP does to it between the model and the
    listing is exactly what a re-derived copy would hide. Cached because
    building it walks every tool, and it cannot change within a run.
    """
    tools = asyncio.run(mcp.list_tools())
    return {t.name: t.outputSchema for t in tools if t.outputSchema is not None}


def _schema(tool: str) -> dict[str, Any]:
    """The advertised output schema of one tool."""
    schemas = _advertised_schemas()
    assert tool in schemas, f"{tool} advertises no outputSchema at all"
    return schemas[tool]


def _wire(payload: dict[str, Any]) -> Any:
    """The payload as JSON types, which is all the client ever sees.

    ``model_dump()`` leaves Python objects in place -- a ``GemtextLineType`` is
    still an enum member, not a ``str`` -- and jsonschema is duck-typed enough
    to accept several of those by accident. The client validates what came off
    the wire, so the wire form is validated here too.

    Deliberately no ``fallback=``. FastMCP builds the real payload with
    ``model_dump(mode="json", by_alias=True)``, which RAISES
    ``PydanticSerializationError`` on a value it cannot serialize. A fallback
    here would instead render that same value as its ``repr`` -- handing the
    schema a plausible ``str`` that a ``string`` field accepts -- so the one
    file written to catch a field whose serialization drifts would be the file
    that hid it, while every real call failed.
    """
    return json.loads(to_json(payload))


def _branches(schema: dict[str, Any]) -> list[dict[str, Any]]:
    """Each ``oneOf`` branch as a standalone, self-contained schema.

    The branches are ``$ref``s into the parent's ``$defs``, so the defs travel
    with each one; otherwise the reference dangles and jsonschema raises
    instead of answering the question being asked.
    """
    return [{**branch, "$defs": schema.get("$defs", {})} for branch in schema["oneOf"]]


def _matching_branches(payload: Any, schema: dict[str, Any]) -> list[int]:
    """Indices of the ``oneOf`` branches that accept ``payload``."""
    matched: list[int] = []
    for index, branch in enumerate(_branches(schema)):
        validator = jsonschema.validators.validator_for(branch)(branch)
        if validator.is_valid(payload):
            matched.append(index)
    return matched


def _gopher_payloads() -> list[tuple[str, str, BaseModel]]:
    """One minimal and one maximal instance of every Gopher result kind.

    Minimal is what the models make mandatory; maximal populates every optional
    field with a non-default value, because a default that is never overridden
    can hide a type the schema does not actually permit.
    """
    cache = {
        "cached": True,
        "cached_at": "2026-01-01T00:00:00+00:00",
        "cache_age_seconds": 12.5,
    }
    info = {"url": "gopher://example.org/1/", "timestamp": "2026-01-01T00:00:05+00:00"}
    item = GopherMenuItem(
        type="1",
        title="Phlog",
        selector="/phlog",
        host="example.org",
        port=70,
        next_url="gopher://example.org/1/phlog",
    )
    return [
        ("minimal", "menu", MenuResult(items=[item])),
        (
            "maximal",
            "menu",
            MenuResult(
                items=[item],
                truncated=True,
                total_items=42,
                next_offset=1,
                request_info=info,
                **cache,
            ),
        ),
        ("minimal", "text", TextResult(bytes=5, text="hello")),
        (
            "maximal",
            "text",
            TextResult(
                charset="iso-8859-1",
                bytes=5,
                text="hello",
                truncated=True,
                total_chars=120,
                next_offset=5,
                request_info=info,
                **cache,
            ),
        ),
        ("minimal", "binary", BinaryResult(bytes=1024)),
        (
            "maximal",
            "binary",
            BinaryResult(
                bytes=1024,
                mime_type="image/png",
                note="Binary content withheld",
                request_info=info,
                **cache,
            ),
        ),
        ("minimal", "error", ErrorResult(error={"message": "boom"})),
        (
            "maximal",
            "error",
            ErrorResult(
                # A Gopher error carries only code/message today, but `error`
                # is `dict[str, Any]` precisely so a protocol can add to it --
                # so the maximal case sends more than the two.
                error={
                    "code": "FETCH_ERROR",
                    "message": "boom",
                    "temporary": True,
                    "retry_after": 30,
                },
                request_info=info,
            ),
        ),
    ]


def _gemini_payloads() -> list[tuple[str, str, BaseModel]]:
    """One minimal and one maximal instance of every Gemini result kind."""
    cache = {
        "cached": True,
        "cached_at": "2026-01-01T00:00:00+00:00",
        "cache_age_seconds": 12.5,
    }
    info = {"url": "gemini://example.org/", "timestamp": "2026-01-01T00:00:05+00:00"}
    mime = GeminiMimeType(type="text", subtype="gemini")
    full_mime = GeminiMimeType(
        type="text", subtype="gemini", charset="iso-8859-1", lang="en-GB"
    )
    minimal_doc = GemtextDocument(
        lines=[GemtextLine(type=GemtextLineType.TEXT, content="hello")]
    )
    # Every gemtext line type, and every optional field a line can carry: the
    # per-line serializer drops nulls, so a line's shape depends on its type
    # and only a line of each type exercises them all.
    full_doc = GemtextDocument(
        lines=[
            GemtextLine(type=GemtextLineType.TEXT, content="hello"),
            GemtextLine(
                type=GemtextLineType.LINK,
                content="=> /about About us",
                link=GemtextLink(url="gemini://example.org/about", text="About us"),
            ),
            GemtextLine(
                type=GemtextLineType.HEADING_1,
                content="# Title",
                text="Title",
                level=1,
            ),
            GemtextLine(
                type=GemtextLineType.HEADING_3, content="### Deep", text="Deep", level=3
            ),
            GemtextLine(type=GemtextLineType.LIST_ITEM, content="* one", text="one"),
            GemtextLine(type=GemtextLineType.QUOTE, content="> said", text="said"),
            GemtextLine(
                type=GemtextLineType.PREFORMAT,
                content="```python",
                alt_text="python",
                language="python",
            ),
        ],
        links=[GemtextLink(url="gemini://example.org/about", text="About us")],
    )
    return [
        (
            "minimal",
            "success",
            GeminiSuccessResult(mime_type=mime, content="hello", size=5),
        ),
        (
            "maximal",
            "success",
            GeminiSuccessResult(
                mime_type=full_mime,
                content="hello",
                size=5,
                truncated=True,
                total_chars=120,
                next_offset=5,
                request_info=info,
                **cache,
            ),
        ),
        ("minimal", "binary", GeminiBinaryResult(mime_type=mime, size=1024)),
        (
            "maximal",
            "binary",
            GeminiBinaryResult(
                mime_type=full_mime,
                size=1024,
                note="Binary content withheld",
                request_info=info,
                **cache,
            ),
        ),
        ("minimal", "gemtext", GeminiGemtextResult(document=minimal_doc, size=5)),
        (
            "maximal",
            "gemtext",
            GeminiGemtextResult(
                document=full_doc,
                # Excluded from serialization on purpose; populated here so the
                # exclusion is what keeps it off the wire, not its emptiness.
                raw_content="# Title\nhello\n",
                charset="iso-8859-1",
                lang="en-GB",
                size=5,
                truncated=True,
                partial_line=True,
                total_chars=120,
                next_offset=5,
                request_info=info,
                **cache,
            ),
        ),
        ("minimal", "input", GeminiInputResult(prompt="Search")),
        (
            "maximal",
            "input",
            GeminiInputResult(prompt="Password", sensitive=True, request_info=info),
        ),
        (
            "minimal",
            "redirect",
            GeminiRedirectResult(new_url="gemini://example.org/moved"),
        ),
        (
            "maximal",
            "redirect",
            GeminiRedirectResult(
                new_url="gemini://elsewhere.example/moved",
                permanent=True,
                cross_host=True,
                scheme="gemini",
                request_info=info,
            ),
        ),
        ("minimal", "certificate", GeminiCertificateResult(message="cert required")),
        (
            "maximal",
            "certificate",
            GeminiCertificateResult(
                message="not authorized",
                status=61,
                required=False,
                next_step="Present a different identity.",
                request_info=info,
            ),
        ),
        (
            "minimal",
            "error",
            ErrorResult(error={"message": "boom"}),
        ),
        (
            "maximal",
            "error",
            # The shape gemini_client really builds: the numeric status and the
            # temporary flag ride alongside code and message.
            ErrorResult(
                error={
                    "code": "GEMINI_ERROR",
                    "message": "boom",
                    "status": 51,
                    "temporary": False,
                },
                request_info=info,
            ),
        ),
    ]


_PAYLOADS = [
    ("gopher_fetch", completeness, kind, result)
    for completeness, kind, result in _gopher_payloads()
] + [
    ("gemini_fetch", completeness, kind, result)
    for completeness, kind, result in _gemini_payloads()
]

_PAYLOAD_PARAMS = [
    pytest.param(tool, kind, result, id=f"{tool}-{kind}-{completeness}")
    for tool, completeness, kind, result in _PAYLOADS
]


@pytest.mark.parametrize(("tool", "kind", "result"), _PAYLOAD_PARAMS)
def test_a_conforming_client_accepts_every_payload_the_fetch_tools_can_return(
    tool: str, kind: str, result: BaseModel
) -> None:
    """``jsonschema.validate`` is the check that runs at the far end of a call.

    The SDK's own ClientSession runs it on ``structuredContent`` after every
    successful call. A failure here is not a schema nicety: it is the SDK
    raising ``RuntimeError("Invalid structured content returned by tool ...")``
    at the caller, discarding a fetch that had already succeeded.
    """
    schema = _schema(tool)
    payload = result.model_dump()
    assert payload["kind"] == kind, "the fixture is mislabelled"
    try:
        jsonschema.validate(_wire(payload), schema)
    except jsonschema.ValidationError as exc:
        pytest.fail(
            f"{type(result).__name__} produces structuredContent that the "
            f"outputSchema advertised by {tool} rejects, so the SDK's own "
            f"client raises instead of returning the result:\n{exc}"
        )


@pytest.mark.parametrize(("tool", "kind", "result"), _PAYLOAD_PARAMS)
def test_every_payload_matches_exactly_one_branch_of_the_advertised_union(
    tool: str, kind: str, result: BaseModel
) -> None:
    """``oneOf`` means exactly one, and nothing tells jsonschema otherwise.

    The schema carries a ``discriminator``, but that keyword is OpenAPI's, not
    JSON Schema's: a conforming validator ignores it and enforces the bare
    ``oneOf``. So a payload accepted by two branches is REJECTED -- "is valid
    under each of" -- even though Pydantic, which does read the discriminator,
    only ever tried the branch ``kind`` named and was satisfied.

    What keeps the branches disjoint is the ``kind`` ``const`` on each one.
    Asserting the count rather than "at least one" is what makes this test
    notice a new result kind that forgets its literal, or an existing one whose
    ``kind`` stops being serialized -- either of which leaves the union
    ambiguous and every result of that kind unusable by a conforming client.
    """
    schema = _schema(tool)
    payload = _wire(result.model_dump())
    matched = _matching_branches(payload, schema)
    mapping = schema["discriminator"]["mapping"]
    names = [schema["oneOf"][index]["$ref"] for index in matched]
    assert len(matched) == 1, (
        f"a {kind} result matched {len(matched)} of the {len(schema['oneOf'])} "
        f"branches of {tool}'s oneOf ({names}); jsonschema ignores the "
        f"discriminator, so anything but exactly one makes a conforming client "
        f"reject this payload"
    )
    assert schema["oneOf"][matched[0]]["$ref"] == mapping[kind], (
        f"a {kind} result validated against a branch other than the one the "
        f"discriminator maps {kind!r} to, so the two enforcement paths disagree "
        f"about what this payload is"
    )


@pytest.mark.parametrize("tool", ["gopher_fetch", "gemini_fetch"])
def test_the_payloads_here_cover_every_kind_the_schema_advertises(tool: str) -> None:
    """A new result kind must arrive with payloads, or these tests miss it.

    Every test above is parametrized over a hand-written list. Adding a member
    to a fetch union without adding it here would leave the new kind advertised
    to clients and validated by nobody, which is the exact gap this file was
    written to close.
    """
    covered = {kind for name, _, kind, _ in _PAYLOADS if name == tool}
    advertised = set(_schema(tool)["discriminator"]["mapping"])
    assert covered == advertised, (
        f"{tool} advertises {sorted(advertised)} but these tests build "
        f"{sorted(covered)}. Add a minimal and a maximal payload for the "
        f"difference."
    )


def _unpopulated_optional_fields(result: BaseModel) -> list[str]:
    """Optional fields on ``result`` still sitting at their default value.

    ``kind`` is skipped: it is the discriminator literal, so the only value it
    may ever hold is the one it defaults to.
    """
    unpopulated: list[str] = []
    for name, field in type(result).model_fields.items():
        if name == "kind" or field.is_required():
            continue
        if field.default_factory is not None:
            default = field.default_factory()
        else:
            default = field.default
        if getattr(result, name) == default:
            unpopulated.append(name)
    return unpopulated


_MAXIMAL_PARAMS = [
    pytest.param(tool, kind, result, id=f"{tool}-{kind}")
    for tool, completeness, kind, result in _PAYLOADS
    if completeness == "maximal"
]


@pytest.mark.parametrize(("tool", "kind", "result"), _MAXIMAL_PARAMS)
def test_every_maximal_payload_leaves_no_optional_field_at_its_default(
    tool: str, kind: str, result: BaseModel
) -> None:
    """The maximal payloads are only worth having for as long as they stay maximal.

    Every jsonschema test in this file is exactly as strong as the payload it
    is handed, and the maximal ones exist because an optional field left at its
    default is almost always ``None`` -- which every branch of the union
    permits, whatever type the field really is. So a field is only actually
    checked against the schema on the run where something non-default is in it.

    The sibling test above guards the discriminator mapping, so a new result
    KIND cannot arrive untested. Nothing guarded a new FIELD: add one optional
    field to an existing result model, forget to populate it here, and it
    serializes as ``null`` in all 22 payloads, matches the schema trivially,
    and every test above stays green while the field's real serialized type is
    never once compared against the type the schema advertises.

    This is the guard for that. It fails on the fixture, naming the field, so
    the answer is to populate it rather than to discover the drift from a
    client's RuntimeError.
    """
    unpopulated = _unpopulated_optional_fields(result)
    assert not unpopulated, (
        f"the maximal {kind} payload for {tool} leaves {sorted(unpopulated)} at "
        f"the default, so those fields only ever reach the schema as their "
        f"default value and their real serialized type is never checked. "
        f"Populate them in the maximal fixture with a non-default value."
    )


@pytest.mark.parametrize("tool", ["gopher_fetch", "gemini_fetch"])
def test_the_advertised_schema_is_itself_a_valid_json_schema(tool: str) -> None:
    """An unusable schema fails the call just as loudly as a bad payload.

    The SDK catches ``SchemaError`` separately and re-raises it as "Invalid
    schema for tool ...", so a malformed ``outputSchema`` breaks every call to
    that tool without any payload being wrong. Checking it here costs nothing
    and names the cause.
    """
    schema = _schema(tool)
    validator = jsonschema.validators.validator_for(schema)
    validator.check_schema(schema)


# The cacheable kinds -- the only ones `mark_from_cache` is ever handed, since
# an error, redirect, input prompt or certificate prompt is never cached.
_CACHEABLE = {
    "gopher_fetch": {"menu", "text", "binary"},
    "gemini_fetch": {"success", "binary", "gemtext"},
}

_CACHE_PARAMS = [
    pytest.param(tool, kind, result, id=f"{tool}-{kind}")
    for tool, completeness, kind, result in _PAYLOADS
    if completeness == "minimal" and kind in _CACHEABLE[tool]
]


@pytest.mark.parametrize(("tool", "kind", "result"), _CACHE_PARAMS)
def test_a_cache_replay_still_validates_against_the_advertised_schema(
    tool: str, kind: str, result: BaseModel
) -> None:
    """``mark_from_cache`` writes three fields without validating any of them.

    It stamps provenance with ``model_copy(update=...)``, which assigns
    straight into the copy: Pydantic never sees the values, so a wrong type
    there is caught by nothing on the server side. ``cached_at`` must be the
    ISO-8601 string the schema declares (not the float epoch it is computed
    from) and ``cache_age_seconds`` a number, or every cache HIT -- not the
    miss that filled the cache, which is why this would look intermittent --
    fails validation at a conforming client.
    """
    replayed = mark_from_cache(result, cached_at=time.time() - 30)
    payload = _wire(replayed.model_dump())
    assert payload["cached"] is True, "the fixture did not actually get stamped"
    try:
        jsonschema.validate(payload, _schema(tool))
    except jsonschema.ValidationError as exc:
        pytest.fail(
            f"a cached {kind} result is rejected by the schema {tool} "
            f"advertises, so every cache hit fails at the client while the "
            f"first, uncached fetch succeeds:\n{exc}"
        )
