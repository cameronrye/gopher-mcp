"""Property-based / fuzz tests for the protocol parsers in ``utils.py``.

The gopher/gemini parsers are the security boundary of the server, so they get
property-based coverage in addition to the example-based tests. Three classes of
property are asserted here:

1. **No crash / clean failure** -- arbitrary ``str``/``bytes`` either parses or
   raises ``ValueError``; never an unexpected exception, never a hang.
2. **Round-trip** -- ``parse(format(components)) == components`` for valid
   generated component tuples, covering IPv6 literal hosts (bracketed),
   port boundaries, and ``%09`` tab-search splitting.
3. **Security invariants** -- control-byte rejection in selectors/search, the
   RFC 1436 ``.`` terminator (with or without surrounding whitespace), the
   Gemini ``<META>`` 1024-byte bound, and the 10-69 status-code range.

These also form the safety net for the subsequent ``utils.py`` module split:
they should reveal no bugs if the parsers are correct, but a failing property is
a real finding -- capture the minimal example as a regression test and fix the
parser test-first.
"""

import re
import string

import pytest
from hypothesis import HealthCheck, assume, given, settings
from hypothesis import strategies as st

from gopher_mcp.models import GeminiResponse, GopherMenuItem
from gopher_mcp.utils import (
    format_gemini_url,
    format_gopher_url,
    parse_gemini_response,
    parse_gemini_url,
    parse_gopher_menu,
    parse_gopher_url,
    parse_menu_line,
)

# The conftest autouse fixtures are function-scoped; ``@given`` drives many
# examples inside a single fixture setup, which is fine here (the parsers touch
# none of that state) -- silence the resulting health check. ``deadline=None``
# keeps coverage-instrumented runs from flaking on per-example timing.
PROPERTY = settings(
    max_examples=200,
    deadline=None,
    suppress_health_check=[HealthCheck.function_scoped_fixture],
)

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")

# Selector/search characters that survive ``format_gopher_url`` (which does not
# percent-encode) and round-trip back through ``parse_gopher_url`` (which
# ``unquote``s) unchanged: printable ASCII minus ``%`` (would be decoded), ``?``
# (starts a query), ``#`` (fragment), and all whitespace (``sanitize_selector``
# forbids tab/CR/LF; urlparse strips them anyway).
_SAFE_SELECTOR_CHARS = "".join(
    c for c in string.printable if c not in "%?# \t\n\r\x0b\x0c"
)
# Gemini path chars: the gemini parser does NOT percent-decode, so ``%`` is kept
# verbatim and is allowed. ``?`` (query), ``#`` (fragment) and whitespace
# (rejected as a raw space / control) are excluded.
_SAFE_GEMINI_PATH_CHARS = "".join(
    c for c in string.printable if c not in "?# \t\n\r\x0b\x0c"
)
# Gemini query chars: like the path, but ``?`` is allowed (everything after the
# first ``?`` is the query, so an embedded ``?`` round-trips).
_SAFE_GEMINI_QUERY_CHARS = "".join(
    c for c in string.printable if c not in "# \t\n\r\x0b\x0c"
)

# ---------------------------------------------------------------------------
# Shared strategies
# ---------------------------------------------------------------------------

# Lowercase registered-name hosts: urlparse lowercases ``hostname``, so a
# generated host must already be lowercase to compare equal after a round-trip.
_regname_label = st.text(
    alphabet=string.ascii_lowercase + string.digits + "-",
    min_size=1,
    max_size=12,
).filter(lambda s: not s.startswith("-") and not s.endswith("-"))
regname_hosts = st.lists(_regname_label, min_size=1, max_size=3).map(".".join)

# Canonical lowercase IPv6 literals, unbracketed: ``bracket_host`` wraps them and
# ``parsed.hostname`` returns them unbracketed + lowercased.
ipv6_hosts = st.sampled_from(
    [
        "::1",
        "::",
        "2001:db8::1",
        "fe80::1",
        "2001:db8::8a2e:370:7334",
        "2001:db8:1234:5678:9abc:def0:1234:5678",
    ]
)
hosts = st.one_of(regname_hosts, ipv6_hosts)

# Single-character gopher item type from a safe set (no URL-significant chars
# that would shift parsing, no ``%``/whitespace). Includes ``7`` (search).
gopher_types = st.sampled_from("0123456789+gIThicsdp;<MT")

safe_selectors = st.text(alphabet=_SAFE_SELECTOR_CHARS, max_size=64)
safe_search = st.text(alphabet=_SAFE_SELECTOR_CHARS, min_size=1, max_size=64)

# Every C0 control byte and DEL except TAB (0x09): a percent-encoded ``%09`` is
# the legitimate type-7 search separator, handled by splitting rather than
# rejection, so it is excluded from the "must be rejected" set.
_CONTROL_BYTES_NO_TAB = [b for b in range(0x20) if b != 0x09] + [0x7F]

# A well-formed (tab-separated, 4-field) gopher menu line that always parses to
# an item and never strips to the ``.`` terminator.
menu_lines = st.builds(
    lambda t, title, sel, host, port: f"{t}{title}\t{sel}\t{host}\t{port}",
    st.sampled_from("01279ghIi"),
    st.text(alphabet=_SAFE_SELECTOR_CHARS, max_size=20),
    st.text(alphabet=_SAFE_SELECTOR_CHARS, max_size=20),
    regname_hosts,
    st.integers(min_value=0, max_value=65535),
)

# ``.`` terminators with assorted surrounding whitespace -- all strip to ``.``.
terminators = st.sampled_from([".", ". ", ".\t", "  .  ", ".\t\t", "\t.", " ."])

# Arbitrary text, including the scheme prefixes so the parser body (not just the
# prefix guard) is exercised.
arbitrary_url_text = st.one_of(
    st.text(max_size=200),
    st.text(max_size=200).map(lambda s: "gopher://" + s),
    st.text(max_size=200).map(lambda s: "gemini://" + s),
)


# ---------------------------------------------------------------------------
# 1. No crash / clean failure
# ---------------------------------------------------------------------------


@PROPERTY
@given(s=arbitrary_url_text)
def test_parse_gopher_url_never_crashes(s: str) -> None:
    try:
        result = parse_gopher_url(s)
    except ValueError:
        return  # clean, expected failure
    # On success the decoded output must never carry a control byte.
    assert not _CONTROL_RE.search(result.selector)
    if result.search is not None:
        assert not _CONTROL_RE.search(result.search)


@PROPERTY
@given(s=arbitrary_url_text)
def test_parse_gemini_url_never_crashes(s: str) -> None:
    try:
        parse_gemini_url(s)
    except ValueError:
        return


@PROPERTY
@given(line=st.text(max_size=200))
def test_parse_menu_line_never_crashes(line: str) -> None:
    result = parse_menu_line(line)
    assert result is None or isinstance(result, GopherMenuItem)


@PROPERTY
@given(content=st.text(max_size=500))
def test_parse_gopher_menu_never_crashes(content: str) -> None:
    items = parse_gopher_menu(content)
    assert isinstance(items, list)
    assert all(isinstance(i, GopherMenuItem) for i in items)


@PROPERTY
@given(raw=st.binary(max_size=300))
def test_parse_gemini_response_never_crashes(raw: bytes) -> None:
    try:
        resp = parse_gemini_response(raw)
    except ValueError:
        return
    assert isinstance(resp, GeminiResponse)


# ---------------------------------------------------------------------------
# 2. Round-trip
# ---------------------------------------------------------------------------


@PROPERTY
@given(
    host=hosts,
    port=st.one_of(st.just(70), st.integers(min_value=1, max_value=65535)),
    gopher_type=gopher_types,
    selector=safe_selectors,
    search=st.one_of(st.none(), safe_search),
)
def test_gopher_url_round_trip(
    host: str,
    port: int,
    gopher_type: str,
    selector: str,
    search: str | None,
) -> None:
    url = format_gopher_url(host, port, gopher_type, selector, search)
    result = parse_gopher_url(url)

    assert result.host == host
    assert result.port == port
    assert result.gopher_type == gopher_type
    assert result.selector == selector
    # ``format_gopher_url`` only emits the search for a type-7 item; otherwise it
    # is dropped, so the parsed value is None.
    expected_search = search if (search and gopher_type == "7") else None
    assert result.search == expected_search


@PROPERTY
@given(
    host=hosts,
    port=st.one_of(st.just(1965), st.integers(min_value=1, max_value=65535)),
    path_tail=st.text(alphabet=_SAFE_GEMINI_PATH_CHARS, max_size=64),
    query=st.one_of(
        st.none(),
        st.text(alphabet=_SAFE_GEMINI_QUERY_CHARS, min_size=1, max_size=64),
    ),
)
def test_gemini_url_round_trip(
    host: str,
    port: int,
    path_tail: str,
    query: str | None,
) -> None:
    path = "/" + path_tail
    url = format_gemini_url(host, port, path, query)
    # Stay within the spec's request-line bound; ASCII inputs keep this rare.
    assume(len(url.encode("utf-8")) + len(b"\r\n") <= 1024)
    result = parse_gemini_url(url)

    assert result.host == host
    assert result.port == port
    assert result.path == path
    assert result.query == (query if query else None)


# ---------------------------------------------------------------------------
# 3. Security invariants
# ---------------------------------------------------------------------------


@PROPERTY
@given(
    prefix=safe_selectors,
    byte=st.sampled_from(_CONTROL_BYTES_NO_TAB),
    suffix=safe_selectors,
)
def test_gopher_selector_rejects_encoded_control_bytes(
    prefix: str, byte: int, suffix: str
) -> None:
    # The only ``%`` is the injected one, so it decodes to exactly chr(byte);
    # a control byte in the decoded selector must fail closed.
    url = f"gopher://example.com/1{prefix}%{byte:02X}{suffix}"
    with pytest.raises(ValueError, match="Selector must not contain control"):
        parse_gopher_url(url)


@PROPERTY
@given(
    sel=safe_selectors,
    byte=st.sampled_from(_CONTROL_BYTES_NO_TAB),
    tail=safe_selectors,
)
def test_gopher_search_rejects_encoded_control_bytes(
    sel: str, byte: int, tail: str
) -> None:
    # type-7 URL: ``%09`` splits selector from search; the control byte lands in
    # the decoded search field and must be rejected.
    url = f"gopher://example.com/7{sel}%09{tail}%{byte:02X}"
    with pytest.raises(ValueError, match="Search query must not contain control"):
        parse_gopher_url(url)


@PROPERTY
@given(
    pre=st.lists(menu_lines, max_size=5),
    terminator=terminators,
    post=st.lists(menu_lines, min_size=1, max_size=5),
)
def test_menu_terminator_stops_parsing(
    pre: list[str], terminator: str, post: list[str]
) -> None:
    pre_content = "\r\n".join(pre)
    full = "\r\n".join([*pre, terminator, *post]) + "\r\n"
    # Everything from the terminator onward is ignored, so parsing the full menu
    # yields exactly what parsing the pre-terminator lines alone yields.
    assert parse_gopher_menu(full) == parse_gopher_menu(pre_content)


@PROPERTY
@given(
    n=st.integers(min_value=1025, max_value=4000),
    status=st.integers(min_value=20, max_value=29),
)
def test_gemini_meta_over_1024_bytes_rejected(n: int, status: int) -> None:
    meta = "m" * n  # ASCII -> one byte per char
    raw = f"{status:02d} {meta}\r\nbody".encode("ascii")
    with pytest.raises(ValueError, match="Meta field exceeds 1024 bytes"):
        parse_gemini_response(raw)


@PROPERTY
@given(status=st.integers(min_value=20, max_value=29))
def test_gemini_meta_at_1024_bytes_accepted(status: int) -> None:
    meta = "m" * 1024  # exactly 1024 bytes is the allowed boundary
    raw = f"{status:02d} {meta}\r\n".encode("ascii")
    resp = parse_gemini_response(raw)
    assert resp.meta == meta


@PROPERTY
@given(status=st.one_of(st.integers(0, 9), st.integers(70, 99)))
def test_gemini_status_out_of_range_rejected(status: int) -> None:
    raw = f"{status:02d} text/gemini\r\n".encode("ascii")
    with pytest.raises(ValueError, match="Status code out of range"):
        parse_gemini_response(raw)


@PROPERTY
@given(status=st.integers(min_value=10, max_value=69))
def test_gemini_status_in_range_accepted(status: int) -> None:
    raw = f"{status:02d} text/gemini\r\n".encode("ascii")
    resp = parse_gemini_response(raw)
    assert int(resp.status) == status
