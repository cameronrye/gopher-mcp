"""The documented Gopher item-type tables must match the categories the code assigns.

A type's category -- "menu", "text", "binary" or "interactive" -- is what decides
whether a fetch comes back as a menu, as text, as binary metadata, or as a
``NOT_FETCHABLE`` error answered from the type alone. Callers plan their
branching from the tables in the docs rather than from ``_GOPHER_TYPE_CATEGORY``,
and those tables are hand-maintained in four files plus a handful of prose lists.
Nothing failed when a type was added to the dict and to none of them: every table
still rendered, every link still resolved, and the docs were quietly wrong
(finding G016).

These tests cannot check that a row's prose is right -- only a reader can -- but
they pin what rots silently: which types are listed, which category each is
listed under, which ``kind`` that category produces, and whether the prose lists
that enumerate a whole category are still complete.

``_GOPHER_TYPE_CATEGORY`` is imported rather than read out of the AST, which is
what ``test_error_code_docs`` has to do for error codes: those are scattered
string literals at every emission site, whereas this is a single module-level
dict, so importing it is both simpler and exactly what ships.

Deliberately not covered: the "Core Item Types" table in
``docs/gopher-specification-for-llms.md``. That one documents RFC 1436 itself --
it lists types this server does not categorize (`+`) and classifies them by the
spec's transaction type rather than by this server's dispatch -- so pinning it to
``_GOPHER_TYPE_CATEGORY`` would assert something that was never true.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from gopher_mcp.gopher_parse import _GOPHER_TYPE_CATEGORY, gopher_type_category

REPO = Path(__file__).resolve().parents[1]
DOCS = REPO / "docs"

# The canonical table: one row per type, naming its category and the `kind` a
# fetch returns. Everything else in the documentation summarizes this.
REFERENCE = DOCS / "api-reference.md"
REFERENCE_HEADING = "Gopher item types"
# Type | Description | Category | Result `kind`
REFERENCE_COLUMNS = 4

# The summary tables. They group several types into one row rather than listing
# one per row, so only their coverage can be checked here, not the grouping --
# the "Action"/"Handled as" columns are prose, not category names.
SUMMARIES = {
    DOCS / "index.md": "Gopher item types",
    DOCS / "ai-assistant-guide.md": "Gopher Item Types",
}

# What the reference table's "Result `kind`" column must say for each category.
# Interactive types never reach a result body: they are refused from the item
# type alone, without a connection, so their kind is `error`.
EXPECTED_KIND = {
    "menu": "menu",
    "text": "text",
    "binary": "binary",
    "interactive": "error",
}

# Every Markdown file that could spell a category out in prose. Globbed rather
# than listed so a new page is covered the day it is written.
PROSE = [*sorted(DOCS.rglob("*.md")), REPO / "README.md"]

# A run of backticked single characters, comma- or "and"-separated:
# "`4`, `5`, `6`, ... `M` and `<`".
RUN = re.compile(r"`.`(?:\s*(?:,\s*and|,|and)\s*`.`)+")

# Five or more item types in such a run is a page enumerating a whole category,
# not one citing a couple of examples. Only "binary" is that large today, but
# the rule is written against the categories so it keeps holding if another
# grows.
ENUMERATION = 5

# Prose that claims how many types a category has: "the fourteen binary types",
# "the three interactive types". The count is as much a fact about the dict as
# the list is, and it goes stale the same way.
COUNT_CLAIM = re.compile(
    r"\b([a-z]+)\s+(menu|text|binary|interactive)\s+(?:item\s+)?types\b",
    re.IGNORECASE,
)
NUMBER_WORDS = {
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
}

SOURCE = "_GOPHER_TYPE_CATEGORY in src/gopher_mcp/gopher_parse.py"


def _markdown(path: Path) -> str:
    """Read a documentation file, skipping if the docs are not present."""
    if not path.is_file():
        pytest.skip(f"{path} is not present (docs are not shipped in the wheel)")
    return path.read_text(encoding="utf-8")


def _types_in(category: str) -> set[str]:
    """Every item type the code puts in ``category``."""
    return {t for t, c in _GOPHER_TYPE_CATEGORY.items() if c == category}


def _where(text: str, offset: int) -> int:
    """The 1-based line number of an offset, so a failure can be looked up."""
    return text.count("\n", 0, offset) + 1


def _table_rows(text: str, heading: str) -> list[str]:
    """The Markdown table rows under ``heading``, up to the next heading."""
    rows: list[str] = []
    collecting = False
    for line in text.splitlines():
        title = re.match(r"^#{2,6}\s+(.*\S)\s*$", line)
        if title:
            collecting = title.group(1) == heading
        elif collecting and line.lstrip().startswith("|"):
            rows.append(line.strip())
    return rows


def _cells(row: str) -> list[str]:
    return [cell.strip() for cell in row.strip().strip("|").split("|")]


def _reference_table(text: str) -> dict[str, tuple[str, str]]:
    """Map each type in the reference table to its (category, result kind)."""
    table: dict[str, tuple[str, str]] = {}
    for row in _table_rows(text, REFERENCE_HEADING):
        cells = _cells(row)
        if len(cells) != REFERENCE_COLUMNS:
            continue
        item = re.fullmatch(r"`(.)`", cells[0])
        if not item:  # the header and separator rows
            continue
        kind = re.search(r"`([A-Za-z_]+)`", cells[3])
        table[item.group(1)] = (cells[2], kind.group(1) if kind else cells[3])
    return table


def _summary_types(text: str, heading: str) -> set[str]:
    """Every item type named in the Type column of a grouped summary table."""
    found: set[str] = set()
    for row in _table_rows(text, heading):
        listed = _cells(row)[0].replace("`", "").split(",")
        found.update(t for t in (part.strip() for part in listed) if len(t) == 1)
    return found


@pytest.fixture(scope="module")
def reference() -> dict[str, tuple[str, str]]:
    """The item types as the published reference lists them."""
    table = _reference_table(_markdown(REFERENCE))
    assert table, f"docs/{REFERENCE.name} lost its '{REFERENCE_HEADING}' table"
    return table


def test_every_item_type_has_a_row_in_the_reference_table(reference):
    """A type with no row is a type a caller cannot look up."""
    missing = {t: c for t, c in _GOPHER_TYPE_CATEGORY.items() if t not in reference}

    assert not missing, "\n".join(
        [
            f"docs/{REFERENCE.name}'s '{REFERENCE_HEADING}' table is missing:",
            *(
                f"  `{t}`  (categorized as '{c}' by the code)"
                for t, c in sorted(missing.items())
            ),
            f"Add a row for each, or drop the type from {SOURCE}.",
        ]
    )


def test_the_reference_table_lists_no_type_the_code_does_not_know(reference):
    """A row for a type the dispatcher never sees is the other half of the rot."""
    stale = sorted(t for t in reference if t not in _GOPHER_TYPE_CATEGORY)

    assert not stale, "\n".join(
        [
            f"docs/{REFERENCE.name} documents item types absent from {SOURCE}:",
            *(f"  `{t}`" for t in stale),
            "An unlisted type is handled as text like any other unknown one, so "
            "the row promises a category the code does not assign. Delete the "
            "row, or restore the type.",
        ]
    )


def test_each_row_names_the_category_the_code_assigns(reference):
    """The Category column is the claim the rest of the table is derived from."""
    wrong = {
        t: (documented, _GOPHER_TYPE_CATEGORY[t])
        for t, (documented, _) in reference.items()
        if t in _GOPHER_TYPE_CATEGORY and documented != _GOPHER_TYPE_CATEGORY[t]
    }

    assert not wrong, "\n".join(
        [
            f"docs/{REFERENCE.name} disagrees with {SOURCE}:",
            *(
                f"  `{t}`  documented as '{documented}', code says '{actual}'"
                for t, (documented, actual) in sorted(wrong.items())
            ),
            "Fix the Category column, or the dict.",
        ]
    )


def test_each_row_names_the_kind_its_category_produces(reference):
    """A row whose category and `kind` disagree misroutes a caller's branch."""
    wrong = {
        t: (kind, EXPECTED_KIND[category])
        for t, (category, kind) in reference.items()
        if category in EXPECTED_KIND and kind != EXPECTED_KIND[category]
    }

    assert not wrong, "\n".join(
        [
            f"docs/{REFERENCE.name}'s 'Result `kind`' column does not follow "
            "from the category:",
            *(
                f"  `{t}`  says `{kind}`, but its category returns `{expected}`"
                for t, (kind, expected) in sorted(wrong.items())
            ),
        ]
    )


@pytest.mark.parametrize(
    ("path", "heading"),
    sorted(SUMMARIES.items()),
    ids=lambda value: value.name if isinstance(value, Path) else value,
)
def test_each_summary_table_covers_every_item_type(path: Path, heading: str):
    """A summary that has quietly stopped being a summary is worse than none."""
    listed = _summary_types(_markdown(path), heading)
    assert listed, f"docs/{path.name} lost its '{heading}' table"

    missing = {t: c for t, c in _GOPHER_TYPE_CATEGORY.items() if t not in listed}

    assert not missing, "\n".join(
        [
            f"docs/{path.name}'s '{heading}' table does not mention:",
            *(
                f"  `{t}`  (categorized as '{c}' by the code)"
                for t, c in sorted(missing.items())
            ),
            f"Add each to the row for its category. Source of truth: {SOURCE}.",
        ]
    )


@pytest.mark.parametrize(
    ("path", "heading"),
    sorted(SUMMARIES.items()),
    ids=lambda value: value.name if isinstance(value, Path) else value,
)
def test_no_summary_table_lists_a_type_the_code_does_not_know(path: Path, heading: str):
    """The same staleness, from the other side."""
    stale = sorted(
        t
        for t in _summary_types(_markdown(path), heading)
        if t not in _GOPHER_TYPE_CATEGORY
    )

    assert not stale, "\n".join(
        [
            f"docs/{path.name}'s '{heading}' table lists item types absent "
            f"from {SOURCE}:",
            *(f"  `{t}`" for t in stale),
            "Each is handled as text like any other unknown type, so the row it "
            "sits in is wrong about it.",
        ]
    )


@pytest.mark.parametrize("path", PROSE, ids=lambda p: p.relative_to(REPO).as_posix())
def test_prose_that_enumerates_a_category_enumerates_all_of_it(path: Path):
    """A half-listed category reads as complete: nothing marks it as partial."""
    text = _markdown(path)
    problems: list[str] = []

    for match in RUN.finditer(text):
        listed = re.findall(r"`(.)`", match.group(0))
        if len(listed) < ENUMERATION:
            continue
        if not all(t in _GOPHER_TYPE_CATEGORY for t in listed):
            continue  # a run of something else that happens to be this long

        found = set(listed)
        category = max(
            set(_GOPHER_TYPE_CATEGORY.values()),
            key=lambda c: len(found & _types_in(c)),
        )
        expected = _types_in(category)
        if found == expected:
            continue

        line = _where(text, match.start())
        for missing in sorted(expected - found):
            problems.append(
                f"  {path.relative_to(REPO)}:{line} omits `{missing}` "
                f"from the '{category}' types"
            )
        for extra in sorted(found - expected):
            problems.append(
                f"  {path.relative_to(REPO)}:{line} lists `{extra}` among the "
                f"'{category}' types, but the code calls it "
                f"'{_GOPHER_TYPE_CATEGORY[extra]}'"
            )

    assert not problems, "\n".join(
        [
            "A prose list of item types has drifted from the code:",
            *problems,
            f"Any run of {ENUMERATION} or more item types is read as a full "
            f"category listing. Update it from {SOURCE}.",
        ]
    )


@pytest.mark.parametrize("path", PROSE, ids=lambda p: p.relative_to(REPO).as_posix())
def test_prose_that_counts_a_category_counts_it_correctly(path: Path):
    """A phrase like "the fourteen binary types" states a fact about the dict,
    and stops being true the moment the dict grows."""
    text = _markdown(path)
    wrong = [
        f"  {path.relative_to(REPO)}:{_where(text, match.start())} says "
        f'"{match.group(0)}", but the code has '
        f"{len(_types_in(match.group(2).lower()))}"
        for match in COUNT_CLAIM.finditer(text)
        if (claimed := NUMBER_WORDS.get(match.group(1).lower())) is not None
        and claimed != len(_types_in(match.group(2).lower()))
    ]

    assert not wrong, "\n".join(
        ["A documented count of item types no longer matches the code:", *wrong]
    )


def test_an_unknown_type_still_falls_back_to_the_documented_category():
    """The reference states this as a rule below the table rather than a row:
    "An unknown type is fetched anyway and returned as `text`." Servers invent
    types, so this is the branch most callers actually hit on the open web."""
    assert gopher_type_category("\x1b") == "text"
    assert gopher_type_category("+") == "text"
    assert gopher_type_category("") == "text"
