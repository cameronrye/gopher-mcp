"""The documented error-code tables must match the codes the source emits.

The error payload's ``code`` is the contract a caller switches on, and the only
place it is *explained* is the tables in ``docs/api-reference.md``. Those tables
drifted before: the 0.8.0 recoding widened ``FETCH_ERROR``, narrowed
``TLS_ERROR`` and extended ``INVALID_REDIRECT``, and the rows describing them
were carried along untouched for a release, because nothing failed when they
stopped being true (finding G039).

These tests cannot check that a row's *prose* is right -- only a reader can --
but they pin the thing that rotted silently: the set of codes. A code the
clients or the parsers can hand back with no row to explain it, or a row for a
code nothing emits any more, fails here, naming the code and the file to edit.

The codes are read out of the AST rather than by importing and exercising the
clients: every emission site is a literal in one of two shapes (``_error(...)``
/ ``_error_result(...)``, or a ``{"code": ...}`` payload), and reaching them all
at runtime would mean provoking every certificate, TLS and robots failure.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

import gopher_mcp

# The package as installed, so the test reads the code that actually ships.
SOURCE_DIR = Path(gopher_mcp.__file__).parent
# The docs live in the repository, not in the wheel.
DOCS = Path(__file__).resolve().parents[1] / "docs" / "api-reference.md"

# An error code as the payload spells it: SCREAMING_SNAKE, at least three
# characters so a Gopher item type (`I`, `M`) in a neighbouring table is not
# mistaken for one.
CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]{2,}$")

# The helpers whose first string argument is a code.
EMITTERS = frozenset({"_error", "_error_result"})

# Which modules answer to which table. server.py is deliberately absent: its
# trust- and certificate-tool codes are split across two further tables, and
# attributing them per tool would pin the table layout rather than the codes.
# ``test_every_error_code_the_source_emits_is_documented`` covers them.
PROTOCOL_TABLES = {
    "Gemini error codes": ("gemini_client.py", "gemini_parse.py", "gemini_tls.py"),
    "Gopher error codes": ("gopher_client.py", "gopher_parse.py"),
}

# A code written into a branch that cannot be reached today, so it is
# deliberately not in that protocol's table. ``GopherClient._robots_denied_result``
# writes the ROBOTS_UNAVAILABLE arm even though Gopher's robots gate fails
# *open* and only "disallowed" can reach it -- the branch is there so flipping
# ``_robots_fail_closed`` cannot silently report "the host refused us" when the
# host never answered. Documenting it under Gopher would promise a code the
# tool does not return.
UNREACHABLE = {"Gopher error codes": {"ROBOTS_UNAVAILABLE"}}


def _string_values(node: ast.AST, names: dict[str, set[str]]) -> list[str]:
    """Resolve an expression to the string literals it can evaluate to."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return [node.value]
    if isinstance(node, ast.IfExp):  # code = "A" if x else "B"
        return _string_values(node.body, names) + _string_values(node.orelse, names)
    if isinstance(node, ast.Name):  # error_type = "..."; {"code": error_type}
        return sorted(names.get(node.id, ()))
    return []


def _codes_in(path: Path) -> dict[str, int]:
    """Map every error code emitted in ``path`` to the line that emits it."""
    tree = ast.parse(path.read_text(encoding="utf-8"))

    # Pass one: local names bound to a code literal, so `{"code": error_type}`
    # can be followed back to the string.
    names: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
            if isinstance(target, ast.Name):
                found = {
                    v for v in _string_values(node.value, {}) if CODE_PATTERN.match(v)
                }
                if found:
                    names.setdefault(target.id, set()).update(found)

    codes: dict[str, int] = {}

    def record(values: list[str], lineno: int) -> None:
        for value in values:
            if CODE_PATTERN.match(value):
                codes.setdefault(value, lineno)

    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values, strict=True):
                if isinstance(key, ast.Constant) and key.value == "code":
                    record(_string_values(value, names), getattr(value, "lineno", 0))
        elif isinstance(node, ast.Call):
            func = node.func
            name = (
                func.attr
                if isinstance(func, ast.Attribute)
                else getattr(func, "id", "")
            )
            if name in EMITTERS:
                for arg in node.args:
                    record(_string_values(arg, names), arg.lineno)
    return codes


def emitted_codes(*filenames: str) -> dict[str, str]:
    """Map each emitted code to the ``file:line`` a reviewer should look at."""
    paths = (
        [SOURCE_DIR / name for name in filenames]
        if filenames
        else sorted(SOURCE_DIR.glob("*.py"))
    )
    found: dict[str, str] = {}
    for path in paths:
        for code, lineno in _codes_in(path).items():
            found.setdefault(code, f"src/gopher_mcp/{path.name}:{lineno}")
    return found


def documented_codes() -> dict[str, set[str]]:
    """Map each "... error codes" heading to the codes its table lists."""
    tables: dict[str, set[str]] = {}
    heading: str | None = None
    for line in DOCS.read_text(encoding="utf-8").splitlines():
        title = re.match(r"^#{2,6}\s+(.*\S)\s*$", line)
        if title:
            heading = title.group(1) if "error code" in title.group(1).lower() else None
            if heading is not None:
                tables.setdefault(heading, set())
            continue
        if heading is not None:
            row = re.match(r"^\|\s*`([A-Z][A-Z0-9_]{2,})`\s*\|", line)
            if row:
                tables[heading].add(row.group(1))
    return tables


@pytest.fixture(scope="module")
def tables() -> dict[str, set[str]]:
    """The error-code tables as the published reference lists them."""
    if not DOCS.is_file():
        pytest.skip(f"{DOCS} is not present (docs are not shipped in the wheel)")
    found = documented_codes()
    assert found, f"no '... error codes' table found in {DOCS.name}"
    return found


def test_every_error_code_the_source_emits_is_documented(tables):
    """A code with no row is a code a caller cannot look up."""
    documented = set().union(*tables.values())
    undocumented = {
        code: where for code, where in emitted_codes().items() if code not in documented
    }

    assert not undocumented, "\n".join(
        [
            "Error codes are emitted but appear in no table in docs/api-reference.md:",
            *(
                f"  {code}  (emitted at {where})"
                for code, where in sorted(undocumented.items())
            ),
            "Add a row for each under the matching '... error codes' heading.",
        ]
    )


def test_every_documented_error_code_is_still_emitted(tables):
    """A row for a code nothing returns any more is the other half of the rot."""
    emitted = set(emitted_codes())
    stale = {
        code: heading
        for heading, codes in tables.items()
        for code in codes
        if code not in emitted
    }

    assert not stale, "\n".join(
        [
            "docs/api-reference.md documents error codes that no longer exist in src/:",
            *(
                f"  {code}  (under '{heading}')"
                for code, heading in sorted(stale.items())
            ),
            "Delete the row, or restore the code.",
        ]
    )


@pytest.mark.parametrize("heading", sorted(PROTOCOL_TABLES))
def test_each_protocol_table_lists_that_protocol_s_codes(heading, tables):
    """A row under the wrong protocol's heading is as good as missing: the
    Gemini and Gopher tables are what a caller reads to decide how to branch."""
    assert heading in tables, f"docs/api-reference.md lost its '{heading}' table"

    emitted = emitted_codes(*PROTOCOL_TABLES[heading])
    exempt = UNREACHABLE.get(heading, set())
    missing = {
        code: where
        for code, where in emitted.items()
        if code not in tables[heading] and code not in exempt
    }

    assert not missing, "\n".join(
        [
            f"docs/api-reference.md's '{heading}' table is missing:",
            *(
                f"  {code}  (emitted at {where})"
                for code, where in sorted(missing.items())
            ),
        ]
    )

    # And the exemption itself must stay honest: if the unreachable branch is
    # ever deleted, so should the entry above.
    for code in exempt:
        assert code in emitted, (
            f"{code} is exempted from the '{heading}' table as unreachable, but "
            f"nothing in {', '.join(PROTOCOL_TABLES[heading])} emits it any "
            f"more. Drop it from UNREACHABLE in this file."
        )
