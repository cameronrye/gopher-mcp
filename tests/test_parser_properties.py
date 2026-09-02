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

from gopher_mcp.gemini_parse import normalize_gemini_path
from gopher_mcp.models import GeminiResponse, GopherMenuItem
from gopher_mcp.utils import (
    format_gemini_url,
    parse_gemini_response,
    parse_gemini_url,
    parse_gemtext,
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
_CONTROL_RE_KEEPING_TAB = re.compile(r"[\x00-\x08\x0a-\x1f\x7f]")

# Selector characters that survive a URL built without percent-encoding and
# round-trip back through ``parse_gopher_url`` (which ``unquote``s) unchanged:
# printable ASCII minus ``%`` (would be decoded), ``?`` (starts a query), ``#``
# (fragment), and all whitespace (urlparse strips tab/CR/LF anyway).
_SAFE_SELECTOR_CHARS = "".join(
    c for c in string.printable if c not in "%?# \t\n\r\x0b\x0c"
)
# ``parse_menu_line`` percent-encodes the selector, so the round-trip alphabet
# is wider: '%', '?', '#' and the space are encoded rather than read as URL
# syntax. TAB/CR/LF stay out (they are the menu line's own framing) and so do
# VT/FF, which would decode back to control characters that ``parse_gopher_url``
# rejects.
_ROUND_TRIP_SELECTOR_CHARS = "".join(
    c for c in string.printable if c not in "\t\n\r\x0b\x0c"
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

safe_selectors = st.text(alphabet=_SAFE_SELECTOR_CHARS, max_size=64)

round_trip_selectors = st.text(alphabet=_ROUND_TRIP_SELECTOR_CHARS, max_size=64)

# Every single character a server can put in the item-type field, including the
# URL-significant ones ('?', '#', '/', '%') and the control bytes.
# TAB/CR/LF are the menu line's own framing, so they can never reach the type
# field; everything else a server can put there is fair game.
item_types = st.one_of(
    st.sampled_from("0123456789+gIThicsdp;<MT"),
    st.sampled_from("?#/%&= ~.\x00\x1b\x7f"),
    st.characters(blacklist_categories=("Cs",), blacklist_characters="\t\r\n"),
)

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
        result = parse_gemini_url(s)
    except ValueError:
        return  # clean, expected failure
    # The success path is the interesting one: these components become the
    # on-wire ``<url>\r\n`` request line and the client-certificate scope
    # decision, so a control byte or an un-normalized path reaching GeminiURL
    # is exactly the regression this module exists to catch.
    assert not _CONTROL_RE.search(result.host)
    assert not _CONTROL_RE.search(result.path)
    assert result.query is None or not _CONTROL_RE.search(result.query)
    # Normalization is a fixed point: every path-scoped decision downstream
    # assumes re-normalizing changes nothing.
    assert result.path == normalize_gemini_path(result.path)
    assert 1 <= result.port <= 65535


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
    # Stay within the spec's 1024-byte <URL> bound; ASCII inputs keep this rare.
    assume(len(url.encode("utf-8")) <= 1024)
    result = parse_gemini_url(url)

    assert result.host == host
    assert result.port == port
    # Parsing resolves dot segments (RFC 3986 5.2.4), so the round trip is
    # through the normalized path -- and parsing it a second time is a fixed
    # point, which is what every path-scoped decision downstream relies on.
    assert result.path == normalize_gemini_path(path)
    assert parse_gemini_url(format_gemini_url(host, port, result.path)).path == (
        result.path
    )
    assert result.query == (query if query else None)


@PROPERTY
@given(
    item_type=item_types,
    selector=round_trip_selectors,
    host=regname_hosts,
    # Port 0 is legal on an info line but not in a URL, so it has no round trip.
    port=st.integers(min_value=1, max_value=65535),
)
def test_menu_item_next_url_round_trips(
    item_type: str, selector: str, host: str, port: int
) -> None:
    # The type and selector are entirely server-controlled, so the constructed
    # nextUrl must re-parse to the same item -- a raw '?' type turned the
    # selector into a search, and a raw '#' made it vanish into a fragment.
    item = parse_menu_line(f"{item_type}Title\t{selector}\t{host}\t{port}")
    assert item is not None

    if not item.next_url:
        # An info line is banner text, not a link: its host/port fields are
        # placeholders, so no URL is emitted and there is nothing to round-trip.
        # A non-printable type degrades to info for the same reason.
        assert item.type == "i"
        return

    parsed = parse_gopher_url(item.next_url)
    assert parsed.gopher_type == item.type
    assert parsed.selector == item.selector
    assert parsed.search is None
    assert parsed.host == host
    assert parsed.port == port


# ---------------------------------------------------------------------------
# 3. Security invariants
# ---------------------------------------------------------------------------


@PROPERTY
@given(line=st.text(max_size=200))
def test_menu_item_fields_never_carry_control_characters(line: str) -> None:
    # Every menu field reaches the model (and often a terminal) verbatim, so an
    # ANSI escape or other control character must never survive parsing.
    item = parse_menu_line(line)
    if item is None:
        return
    assert not _CONTROL_RE.search(item.title)
    assert not _CONTROL_RE.search(item.selector)
    assert not _CONTROL_RE.search(item.host)
    assert not _CONTROL_RE.search(item.next_url)


# Gemtext dispatches on a line's leading marker, and each branch builds its
# line differently -- the marker-stripped `text` of a heading/list/quote, the
# split URL and label of a link, the alt text carried on a preformat toggle.
# Generating bare ``st.text()`` exercises only the plain-text branch (the
# markers are three-in-a-million as a random prefix), so an escape sequence
# surviving in, say, a list item's stripped text would go unnoticed: every line
# type has to be *generated*, not merely reachable in principle.
_GEMTEXT_MARKERS = ["", "* ", "> ", "# ", "## ", "### ", "=> ", "```", "=>"]

# A line's body carries no newline of its own -- the marker is only meaningful
# at the start of a line, so an embedded newline would silently produce a
# different document than the one the strategy describes.
_free_bodies = st.text(alphabet=st.characters(exclude_characters="\r\n"), max_size=60)

# Link lines are two tokens, and the second is optional -- free text almost
# never lands on that shape, so a link's URL/label split would otherwise be
# generated only by accident. The control-character tokens are here because a
# `=>` line whose URL is nothing but an escape sequence must degrade to plain
# text rather than emit an empty link; note that `parse_gemtext` sanitizes the
# whole document *before* splitting it, so what reaches the link parser is
# already the stripped remainder (`\x1b[2J` arrives as `[2J`, a usable URL).
_hostile_tokens = st.sampled_from(["\x1b", "\x1b[2J", "\x07\x07", "\x00"])
_link_bodies = st.builds(
    lambda url, label: f"{url} {label}".rstrip(),
    st.one_of(_hostile_tokens, st.just("/page.gmi"), st.just("gemini://example.org/")),
    st.one_of(_hostile_tokens, st.just("Label"), st.just("")),
)

_line_bodies = st.one_of(_free_bodies, _link_bodies)

gemtext_lines = st.builds(
    lambda marker, body: marker + body,
    marker=st.sampled_from(_GEMTEXT_MARKERS),
    body=_line_bodies,
)

gemtext_documents = st.one_of(
    st.text(max_size=500),
    st.lists(gemtext_lines, max_size=12).map("\n".join),
)


@PROPERTY
@given(content=gemtext_documents)
def test_gemtext_lines_never_carry_control_characters(content: str) -> None:
    document = parse_gemtext(content)
    for line in document.lines:
        # TAB is meaningful inside a line (notably in preformatted blocks) and
        # is deliberately kept; nothing else in the control range is.
        assert not _CONTROL_RE_KEEPING_TAB.search(line.content)
        # The marker-stripped text and a preformat block's alt-text are
        # separately built strings, so sanitizing ``content`` alone would not
        # cover them.
        assert line.text is None or not _CONTROL_RE_KEEPING_TAB.search(line.text)
        assert line.alt_text is None or not _CONTROL_RE_KEEPING_TAB.search(
            line.alt_text
        )
    for link in document.links:
        assert not _CONTROL_RE.search(link.url)
        assert link.text is None or not _CONTROL_RE.search(link.text)


@PROPERTY
@given(lines=st.lists(gemtext_lines, min_size=1, max_size=12))
def test_every_gemtext_line_is_accounted_for(lines: list[str]) -> None:
    """No line type is silently dropped.

    Every input line yields exactly one output line, whatever its marker -- in
    particular a link line with no usable URL degrades to a text line rather
    than vanishing, which is the one branch that could plausibly lose content.

    The sentinel line is not decoration: the parser drops one trailing empty
    line as the document's final newline, and a generated last line can *become*
    empty (a body of nothing but control characters sanitizes away), so counting
    without it would be asserting the trailing-newline rule rather than this
    one.
    """
    document = parse_gemtext("\n".join([*lines, "end"]))
    assert len(document.lines) == len(lines) + 1


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
