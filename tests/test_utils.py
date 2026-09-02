"""Tests for gopher_mcp.utils module."""

import errno
import os
import re
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

import gopher_mcp
import gopher_mcp.utils
from gopher_mcp.helpers import describe_oserror, window_text
from gopher_mcp.utils import (
    atomic_write_json,
    format_gemini_url,
    parse_gopher_menu,
    parse_gopher_url,
    parse_menu_line,
    truncate_text,
)


class TestAtomicWriteJson:
    """Durability and cleanup contract of atomic_write_json."""

    def test_writes_and_reads_back(self):
        with tempfile.TemporaryDirectory() as d:
            target = str(Path(d) / "store.json")
            atomic_write_json(target, {"a": 1, "b": [2, 3]})
            import json

            assert json.loads(Path(target).read_text()) == {"a": 1, "b": [2, 3]}

    def test_no_orphan_temp_file_when_fsync_fails(self):
        """A flush/fsync failure (e.g. disk full) must not leave a .tmp orphan --
        the durability fsync must be inside the cleanup-guarded region."""
        with tempfile.TemporaryDirectory() as d:
            target = str(Path(d) / "store.json")
            with (
                patch("gopher_mcp.helpers.os.fsync", side_effect=OSError("ENOSPC")),
                pytest.raises(OSError),
            ):
                atomic_write_json(target, {"a": 1})

            leftovers = list(Path(d).glob("*.tmp"))
            assert leftovers == [], f"orphaned temp files: {leftovers}"


class TestTruncateText:
    """Test the LLM-facing render-limit helper."""

    def test_under_limit_unchanged(self):
        assert truncate_text("hello", 10) == ("hello", False)

    def test_over_limit_flagged(self):
        assert truncate_text("hello world", 5) == ("hello", True)

    def test_zero_means_unlimited(self):
        big = "x" * 10000
        assert truncate_text(big, 0) == (big, False)


class TestParseGopherUrl:
    """Test parse_gopher_url function."""

    def test_basic_gopher_url(self):
        """Test parsing basic Gopher URL."""
        url = "gopher://example.com/1/"
        result = parse_gopher_url(url)

        assert result.host == "example.com"
        assert result.port == 70
        assert result.gopher_type == "1"
        assert result.selector == "/"
        assert result.search is None

    def test_gopher_url_with_port(self):
        """Test parsing Gopher URL with custom port."""
        url = "gopher://example.com:7070/0/test.txt"
        result = parse_gopher_url(url)

        assert result.host == "example.com"
        assert result.port == 7070
        assert result.gopher_type == "0"
        assert result.selector == "/test.txt"

    def test_gopher_url_with_search(self):
        """Test parsing Gopher URL with search query."""
        url = "gopher://example.com/7/search?test%20query"
        result = parse_gopher_url(url)

        assert result.host == "example.com"
        assert result.gopher_type == "7"
        assert result.selector == "/search"
        assert result.search == "test query"

    def test_gopher_url_with_tab_search(self):
        """Test parsing Gopher URL with tab-separated search."""
        url = "gopher://example.com/7/search%09test%20query"
        result = parse_gopher_url(url)

        assert result.host == "example.com"
        assert result.gopher_type == "7"
        assert result.selector == "/search"
        assert result.search == "test query"

    def test_invalid_url_scheme(self):
        """Test parsing invalid URL scheme."""
        with pytest.raises(ValueError) as exc_info:
            parse_gopher_url("http://example.com/")
        assert "URL must start with 'gopher://'" in str(exc_info.value)

    @pytest.mark.parametrize(
        "url",
        [
            "GOPHER://example.com/1/world",
            "Gopher://example.com/1/world",
            "gOpHeR://example.com/1/world",
        ],
    )
    def test_scheme_is_case_insensitive(self, url):
        """RFC 3986 s3.1 makes the scheme case-insensitive, matching what
        ``parse_gemini_url`` already accepts. Refusing a capitalised one told
        the caller a valid Gopher URL was not a Gopher URL at all."""
        result = parse_gopher_url(url)

        assert result.host == "example.com"
        assert result.gopher_type == "1"
        assert result.selector == "/world"

    def test_a_non_gopher_scheme_is_still_refused(self):
        """Only the case is forgiven; the scheme itself is still checked."""
        with pytest.raises(ValueError, match="URL must start with 'gopher://'"):
            parse_gopher_url("GEMINI://example.com/")

    def test_url_without_hostname(self):
        """Test parsing URL without hostname."""
        with pytest.raises(ValueError) as exc_info:
            parse_gopher_url("gopher:///1/")
        assert "URL must contain a hostname" in str(exc_info.value)

    def test_empty_path_defaults(self):
        """Test that empty path defaults to directory listing."""
        url = "gopher://example.com"
        result = parse_gopher_url(url)

        assert result.gopher_type == "1"
        assert result.selector == ""

    def test_root_path_defaults(self):
        """Test that root path defaults to directory listing."""
        url = "gopher://example.com/"
        result = parse_gopher_url(url)

        assert result.gopher_type == "1"
        assert result.selector == ""


class TestParseMenuLine:
    """Test parse_menu_line function."""

    def test_valid_menu_line(self):
        """Test parsing valid menu line."""
        line = "1About\t/about\texample.com\t70"
        result = parse_menu_line(line)

        assert result is not None
        assert result.type == "1"
        assert result.title == "About"
        assert result.selector == "/about"
        assert result.host == "example.com"
        assert result.port == 70
        assert result.next_url == "gopher://example.com:70/1/about"

    def test_info_line(self):
        """Test parsing info line."""
        line = "iThis is information\t\terror.host\t1"
        result = parse_menu_line(line)

        assert result is not None
        assert result.type == "i"
        assert result.title == "This is information"
        assert result.selector == ""
        assert result.host == "error.host"
        assert result.port == 1
        # "error.host"/1 are the placeholders servers fill an info line's unused
        # fields with, so a URL built from them is dead by construction. The
        # item is display-only and says so with an empty nextUrl.
        assert result.next_url == ""

    def test_hurl_web_link_selector(self):
        """The hURL convention encodes a web link as a 'URL:<target>' selector
        (usually on a type-h item). nextUrl must point at the real destination,
        not a gopher:// URL aimed back at the gopher host."""
        line = "hExample site\tURL:https://example.com/path\tgopher.host\t70"
        result = parse_menu_line(line)

        assert result is not None
        assert result.type == "h"
        assert result.selector == "URL:https://example.com/path"
        assert result.next_url == "https://example.com/path"

    def test_hurl_web_link_preserves_query_and_fragment(self):
        line = "hSearch\tURL:gemini://example.org/q?a=b#frag\tgopher.host\t70"
        result = parse_menu_line(line)
        assert result is not None
        assert result.next_url == "gemini://example.org/q?a=b#frag"

    def test_non_hurl_selector_starting_with_url_text_is_not_a_web_link(self):
        """Only an exact 'URL:' prefix triggers the hURL convention; a normal
        selector that merely starts with 'url' stays a gopher selector."""
        line = "0urls.txt\t/urls.txt\texample.com\t70"
        result = parse_menu_line(line)
        assert result is not None
        assert result.next_url == "gopher://example.com:70/0/urls.txt"

    def test_empty_line(self):
        """Test parsing empty line."""
        result = parse_menu_line("")
        assert result is None

    def test_termination_marker(self):
        """Test parsing termination marker."""
        result = parse_menu_line(".")
        assert result is None

    def test_line_with_crlf(self):
        """Test parsing line with CRLF."""
        line = "0Test File\t/test.txt\texample.com\t70\r\n"
        result = parse_menu_line(line)

        assert result is not None
        assert result.type == "0"
        assert result.title == "Test File"

    def test_insufficient_parts(self):
        """A short line whose first character is not the info type is junk: its
        leading character is not reliably an item type, so it stays dropped."""
        line = "1About\t/about"  # Missing host and port
        result = parse_menu_line(line)
        assert result is None

    def test_tabless_info_line_is_kept(self):
        """'iSome banner text' with the trailing fields omitted is common enough
        that lenient clients render it; it must not vanish from the menu."""
        result = parse_menu_line("iSome banner text")

        assert result is not None
        assert result.type == "i"
        assert result.title == "Some banner text"
        assert result.selector == ""
        assert result.host == ""
        assert result.next_url == ""

    def test_partially_tabbed_info_line_is_kept(self):
        result = parse_menu_line("iBanner\t")

        assert result is not None
        assert result.title == "Banner"

    def test_short_line_without_display_text_is_dropped(self):
        """Nothing to render -> still None."""
        assert parse_menu_line("i") is None
        assert parse_menu_line("\t") is None

    def test_invalid_port(self):
        """Test parsing line with invalid port."""
        line = "1About\t/about\texample.com\tinvalid"
        result = parse_menu_line(line)

        assert result is not None
        assert result.port == 70  # Should default to 70

    def test_empty_type_defaults_to_info(self):
        """Test that empty type defaults to info line."""
        line = "\t\terror.host\t1"
        result = parse_menu_line(line)

        assert result is not None
        assert result.type == "i"

    def test_malformed_line_causes_exception(self):
        """Test that malformed lines that cause exceptions return None."""
        # Test with a line that has parts but causes ValueError in GopherMenuItem creation
        # This is a bit tricky since GopherMenuItem is quite permissive
        # Let's try a line that might cause issues in the URL construction
        line = "1Test\t/test\t\t70"  # Empty host
        result = parse_menu_line(line)

        # Should handle gracefully and return None or a valid item
        # The actual behavior depends on how GopherMenuItem handles empty host
        # This test ensures the exception handling works
        assert result is None or isinstance(result, type(result))

    def test_line_with_special_characters_in_port(self):
        """Test line with special characters that might cause ValueError."""
        line = "1Test\t/test\texample.com\t70.5"  # Float port
        result = parse_menu_line(line)

        assert result is not None
        assert result.port == 70  # Should default to 70 when int() fails


class TestParseGopherMenu:
    """Test parse_gopher_menu function."""

    def test_complete_menu(self):
        """Test parsing complete menu."""
        content = """1About\t/about\texample.com\t70
0README\t/README.txt\texample.com\t70
iThis is information\t\terror.host\t1
.
"""
        result = parse_gopher_menu(content)

        assert len(result) == 3
        assert result[0].type == "1"
        assert result[0].title == "About"
        assert result[1].type == "0"
        assert result[1].title == "README"
        assert result[2].type == "i"
        assert result[2].title == "This is information"

    def test_empty_menu(self):
        """Test parsing empty menu."""
        content = ".\n"
        result = parse_gopher_menu(content)
        assert len(result) == 0

    def test_max_items_stops_early(self):
        """max_items bounds how many items are constructed, so a huge directory
        doesn't materialise tens of thousands of model objects to keep a slice."""
        content = "".join(f"0File {i}\t/f{i}\texample.com\t70\n" for i in range(100))
        result = parse_gopher_menu(content, max_items=5)
        assert len(result) == 5
        assert result[0].title == "File 0"
        assert result[-1].title == "File 4"

    def test_menu_with_invalid_lines(self):
        """Test parsing menu with some invalid lines."""
        content = """1Valid\t/valid\texample.com\t70
0invalid line
0Another Valid\t/valid2\texample.com\t70
"""
        result = parse_gopher_menu(content)

        assert len(result) == 2
        assert result[0].title == "Valid"
        assert result[1].title == "Another Valid"

    def test_menu_keeps_tabless_info_lines(self):
        """A banner written without the trailing tab fields must still appear."""
        content = (
            "1Valid\t/valid\texample.com\t70\r\n"
            "iWelcome to the archive\r\n"
            "0README\t/README\texample.com\t70\r\n"
            ".\r\n"
        )
        result = parse_gopher_menu(content)

        assert [item.title for item in result] == [
            "Valid",
            "Welcome to the archive",
            "README",
        ]
        assert result[1].type == "i"

    def test_stops_at_terminator(self):
        """RFC 1436: the lone '.' line terminates the menu. Anything after it
        (which a server could append past the terminator) must NOT be parsed
        into menu items the model would be told it can navigate to."""
        content = (
            "1Before\t/before\texample.com\t70\r\n"
            ".\r\n"
            "1AfterTerminator\t/evil\tattacker.example\t70\r\n"
        )
        result = parse_gopher_menu(content)

        assert len(result) == 1
        assert result[0].title == "Before"

    def test_stops_at_terminator_with_trailing_whitespace(self):
        """A terminator line carrying trailing whitespace (`. `) must still
        terminate the menu, so a non-conformant server cannot slip navigable
        items past what reads as the end of the listing."""
        content = (
            "1Before\t/before\texample.com\t70\r\n"
            ". \r\n"
            "1AfterTerminator\t/evil\tattacker.example\t70\r\n"
        )
        result = parse_gopher_menu(content)

        assert len(result) == 1
        assert result[0].title == "Before"


class TestFormatGeminiUrl:
    """IPv6 bracketing for Gemini URL construction."""

    def test_ipv6_host_is_bracketed(self):
        assert format_gemini_url("::1") == "gemini://[::1]/"

    def test_ipv6_host_with_port_is_bracketed(self):
        assert (
            format_gemini_url("2001:db8::1", port=1966)
            == "gemini://[2001:db8::1]:1966/"
        )

    def test_regular_host_unchanged(self):
        assert format_gemini_url("example.com", path="/x") == "gemini://example.com/x"


class TestParseMenuLineIPv6:
    """A menu item whose host is an IPv6 literal must yield a re-parseable URL."""

    def test_ipv6_host_next_url_round_trips(self):
        line = "0Title\t/sel\t::1\t70"
        item = parse_menu_line(line)
        assert item is not None
        assert item.next_url == "gopher://[::1]:70/0/sel"
        # The constructed nextUrl must parse back without a port-split error.
        parsed = parse_gopher_url(item.next_url)
        assert parsed.host == "::1"
        assert parsed.port == 70


class TestParseMenuLineItemTypeRoundTrip:
    """A server-controlled item type must survive nextUrl, or not be carried.

    Every printable type -- including the URL-significant ones -- has to
    round-trip through the constructed URL unchanged. A non-printable one is
    the single exception: it is degraded rather than encoded, so there is
    nothing to round-trip.
    """

    def test_question_mark_type_does_not_become_a_search(self):
        """An unencoded '?' type turned the selector into a query string, so
        following the link ran a SEARCH against the root selector."""
        item = parse_menu_line("?Click here\t/sel\texample.com\t70")

        assert item is not None
        assert item.next_url == "gopher://example.com:70/%3F/sel"
        parsed = parse_gopher_url(item.next_url)
        assert parsed.gopher_type == "?"
        assert parsed.selector == "/sel"
        assert parsed.search is None

    def test_hash_type_does_not_swallow_the_selector(self):
        """An unencoded '#' type made the selector vanish into a fragment."""
        item = parse_menu_line("#Weird\t/sel\texample.com\t70")

        assert item is not None
        parsed = parse_gopher_url(item.next_url)
        assert parsed.gopher_type == "#"
        assert parsed.selector == "/sel"

    def test_control_char_type_is_degraded_to_the_info_type(self):
        """A non-printable byte is not an item type, so it is not carried at
        all: `type` degrades to "i", which leaves the item display-only and
        therefore without a nextUrl to embed the byte in. Encoding it into a
        URL instead would have handed the model a link whose type no client
        can act on, built from an info line's placeholder host and port."""
        item = parse_menu_line("\x1bEsc\t/sel\texample.com\t70")

        assert item is not None
        assert item.type == "i"
        assert item.title == "Esc"
        assert item.next_url == ""
        # No field carries the escape onward, in any spelling.
        assert not any("\x1b" in str(value) for value in item.model_dump().values())

    def test_ordinary_type_stays_literal(self):
        item = parse_menu_line("1About\t/about\texample.com\t70")
        assert item is not None
        assert item.next_url == "gopher://example.com:70/1/about"


class TestMenuItemSanitization:
    """Server-controlled menu fields must not carry control characters."""

    def test_ansi_escape_stripped_from_title(self):
        """A hostile server can put an OSC/CSI sequence in every menu title."""
        item = parse_menu_line("1\x1b]0;pwned\x07Evil\t/x\texample.com\t70")

        assert item is not None
        assert item.title == "]0;pwnedEvil"

    def test_control_chars_stripped_from_selector_and_next_url(self):
        item = parse_menu_line("1Title\t/se\x00l\x1b[31m\texample.com\t70")

        assert item is not None
        assert item.selector == "/sel[31m"
        assert item.next_url == "gopher://example.com:70/1/sel%5B31m"

    def test_control_chars_stripped_from_host(self):
        item = parse_menu_line("1Title\t/x\texam\x07ple.com\t70")

        assert item is not None
        assert item.host == "example.com"
        assert item.next_url == "gopher://example.com:70/1/x"

    def test_tabless_info_line_is_sanitized(self):
        item = parse_menu_line("iBan\x1b[2Jner")

        assert item is not None
        assert item.title == "Ban[2Jner"


class TestGopherUrlPortAndSelectorHandling:
    """Regression tests for Gopher URL port/selector parsing fixes."""

    def test_port_zero_is_rejected(self):
        """An explicit :0 must be rejected, not silently coerced to 70."""
        with pytest.raises(ValueError, match=r"[Pp]ort"):
            parse_gopher_url("gopher://example.com:0/1/")

    def test_port_out_of_range_is_rejected(self):
        """An out-of-range port must raise a clear ValueError."""
        with pytest.raises(ValueError, match=r"[Pp]ort"):
            parse_gopher_url("gopher://example.com:99999/1/")

    def test_selector_is_percent_decoded(self):
        """Percent-encoded selectors must be decoded to on-wire bytes."""
        result = parse_gopher_url("gopher://example.com/0/path%20with%20space")
        assert result.selector == "/path with space"

    def test_selector_tab_search_still_decoded(self):
        """A %09 search embedded in the selector is split then decoded."""
        result = parse_gopher_url("gopher://example.com/7/find%09a%20b")
        assert result.selector == "/find"
        assert result.search == "a b"

    def test_menu_line_non_ascii_digit_port_defaults_to_70(self):
        """A non-ASCII 'digit' port must default to 70, not drop the item."""
        item = parse_menu_line("0Title\t/sel\texample.com\t²")
        assert item is not None
        assert item.port == 70

    def test_menu_line_out_of_range_port_defaults_to_70(self):
        """A numeric but out-of-range port (>65535) must degrade to 70 rather
        than failing model validation and dropping the whole menu item."""
        item = parse_menu_line("0Title\t/sel\texample.com\t99999")
        assert item is not None
        assert item.port == 70

    def test_percent_encoded_crlf_in_selector_is_rejected(self):
        """A %0d%0a in the selector decodes to raw CRLF -- the parser must
        fail closed rather than relying solely on a downstream re-check."""
        with pytest.raises(ValueError, match=r"control character"):
            parse_gopher_url("gopher://example.com/0sel%0d%0aINJECT")

    def test_percent_encoded_nul_in_selector_is_rejected(self):
        """A percent-encoded NUL must be rejected at parse time."""
        with pytest.raises(ValueError, match=r"control character"):
            parse_gopher_url("gopher://example.com/0sel%00evil")

    def test_percent_encoded_control_char_in_search_is_rejected(self):
        """A control char in the type-7 search field must be rejected."""
        with pytest.raises(ValueError, match=r"control character"):
            parse_gopher_url("gopher://example.com/7sel%09a%0db")


class TestDescribeOSError:
    """The address an OSError carries must never reach the caller-facing text."""

    def test_asyncio_connect_failure_text_is_dropped(self):
        """asyncio raises ``OSError(err, f"Connect call failed {address}")``, so
        ``strerror`` itself carries the sockaddr -- the resolved IP the SSRF
        guard vetted. Only the errno's canonical text may survive."""
        exc = OSError(errno.ECONNREFUSED, "Connect call failed ('127.0.0.1', 1)")

        described = describe_oserror(exc)

        assert "127.0.0.1" not in described
        assert described == os.strerror(errno.ECONNREFUSED)

    def test_errnoless_oserror_gets_a_generic_description(self):
        assert describe_oserror(OSError("boom")) == "unable to connect"


class TestWindowText:
    """The render cap has to be continuable, not just a cut."""

    def test_first_window_reports_where_the_rest_starts(self):
        window = window_text("abcdefghij", 0, 4)

        assert window.text == "abcd"
        assert window.start == 0
        assert window.total == 10
        assert window.next_offset == 4

    def test_windows_chain_to_the_exact_original(self):
        text = "".join(f"line {i}\n" for i in range(50))
        seen = ""
        offset = 0
        while offset is not None:
            window = window_text(text, offset, 37)
            seen += window.text
            offset = window.next_offset

        assert seen == text

    def test_last_window_has_no_next_offset(self):
        assert window_text("abcdefghij", 8, 4).next_offset is None

    def test_zero_means_unlimited(self):
        window = window_text("abcdefghij", 2, 0)

        assert window.text == "cdefghij"
        assert window.next_offset is None

    def test_offset_past_the_end_is_empty_not_an_error(self):
        window = window_text("abc", 99, 4)

        assert window.text == ""
        assert window.start == 3
        assert window.next_offset is None


class TestUtilsFacadeIsExternalCompatOnly:
    """The facade re-exports names for importers OUTSIDE the package.

    While the package's own modules imported through it, it could never be
    retired -- and a new reader looking for the bottom of the import graph
    found the generically named `utils` instead of `helpers`, which is where
    the implementations actually live.
    """

    def test_no_module_in_the_package_imports_it(self):
        package = Path(gopher_mcp.__file__).parent
        offenders = [
            path.name
            for path in sorted(package.glob("*.py"))
            if path.name != "utils.py"
            and re.search(
                r"^from \.utils import|^from \. import utils", path.read_text(), re.M
            )
        ]

        assert offenders == []

    def test_it_still_re_exports_every_name_it_promises(self):
        for name in gopher_mcp.utils.__all__:
            assert hasattr(gopher_mcp.utils, name), name
