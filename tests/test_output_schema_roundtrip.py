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
"""

from typing import Any

import pytest
from pydantic import BaseModel

from gopher_mcp.models import (
    GeminiFetchOutput,
    GeminiFetchResponse,
    GopherFetchOutput,
    GopherFetchResponse,
)


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
