"""Tests for the shared display-text sanitizer and reference resolver.

``sanitize_display_text`` is the single invariant the whole parsing layer leans
on: nothing a remote gopher/gemini server controls reaches the model carrying
control characters. ``resolve_gemini_reference`` backs both the redirect target
and gemtext link resolution.
"""

import pytest

from gopher_mcp.helpers import resolve_gemini_reference, sanitize_display_text


class TestSanitizeDisplayText:
    """Control-character stripping for server-supplied text."""

    def test_plain_text_unchanged(self):
        assert sanitize_display_text("Hello, world!") == "Hello, world!"

    def test_unicode_preserved(self):
        assert sanitize_display_text("café — naïve 日本語") == "café — naïve 日本語"

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("\x1b[31mred\x1b[0m", "[31mred[0m"),  # CSI
            ("\x1b]0;pwned\x07title", "]0;pwnedtitle"),  # OSC + BEL
            ("nul\x00byte", "nulbyte"),
            ("del\x7fete", "delete"),
            ("\x9b31m", "31m"),  # C1 single-byte CSI from a latin-1 decode
        ],
    )
    def test_control_sequences_stripped(self, raw, expected):
        assert sanitize_display_text(raw) == expected

    def test_line_structure_preserved_by_default(self):
        assert sanitize_display_text("a\nb\tc\rd") == "a\nb\tc\rd"

    def test_whitespace_dropped_for_single_fields(self):
        assert sanitize_display_text("a\nb\tc\rd", keep_whitespace=False) == "abcd"

    def test_idempotent(self):
        once = sanitize_display_text("x\x1b[2Jy\x00")
        assert sanitize_display_text(once) == once

    def test_zero_width_format_characters_stripped(self):
        # U+200B is category Cf: invisible, and not printable.
        assert sanitize_display_text("a\u200bb") == "ab"


class TestResolveGeminiReference:
    """Relative references resolve; absolute ones pass through untouched."""

    @pytest.mark.parametrize(
        ("base", "target", "expected"),
        [
            (
                "gemini://example.org/docs/",
                "spec.gmi",
                "gemini://example.org/docs/spec.gmi",
            ),
            (
                "gemini://example.org/docs/spec.gmi",
                "/index.gmi",
                "gemini://example.org/index.gmi",
            ),
            (
                "gemini://example.org/a/b/c.gmi",
                "../d.gmi",
                "gemini://example.org/a/d.gmi",
            ),
            (
                "gemini://example.org:1966/x/",
                "y.gmi",
                "gemini://example.org:1966/x/y.gmi",
            ),
        ],
    )
    def test_relative_reference_resolved(self, base, target, expected):
        assert resolve_gemini_reference(base, target) == expected

    @pytest.mark.parametrize(
        "target",
        [
            "gemini://other.example/x",
            "https://example.com/x",
            "gopher://example.com/1/x",
            "mailto:someone@example.org",
        ],
    )
    def test_absolute_reference_unchanged(self, target):
        assert resolve_gemini_reference("gemini://example.org/docs/", target) == target

    def test_non_gemini_base_uses_plain_urljoin(self):
        assert (
            resolve_gemini_reference("https://example.org/a/", "b")
            == "https://example.org/a/b"
        )


class TestTruncationDoesNotFabricate:
    """A cut must never turn half a record into a whole one."""

    def test_gemtext_truncated_mid_link_does_not_invent_a_url(self):
        """A cut inside a "=> url text" line parsed as a COMPLETE link whose
        target was the surviving prefix, so the caller was handed a URL the
        server never sent and could not tell it from a real one."""
        from gopher_mcp.gemini_parse import _process_success_response

        text = "intro\n=> gemini://example.com/very/long/real/target.gmi A link\n"
        cap = len("intro\n") + len("=> gemini://example.com/very/lo")

        result = _process_success_response(
            "text/gemini; charset=utf-8",
            text.encode(),
            {"url": "gemini://example.com/"},
            max_rendered_chars=cap,
        )

        assert result.truncated is True
        urls = [
            line.link.url for line in result.document.lines if line.link is not None
        ]
        assert urls == [], f"a partial link was presented as whole: {urls}"
        assert "very/lo" not in result.raw_content

    def test_a_complete_link_before_the_cut_survives(self):
        """The rule drops the partial tail, not everything."""
        from gopher_mcp.gemini_parse import _process_success_response

        text = "=> /a First\n=> /b Second\n"
        result = _process_success_response(
            "text/gemini; charset=utf-8",
            text.encode(),
            {"url": "gemini://example.com/"},
            max_rendered_chars=len("=> /a First\n") + 5,
        )
        urls = [
            line.link.url for line in result.document.lines if line.link is not None
        ]
        assert urls == ["gemini://example.com/a"]


class TestQueryIsNotReflectedIntoLinks:
    """A Gemini query may be a SENSITIVE_INPUT secret."""

    def test_an_empty_reference_does_not_inherit_the_secret(self):
        """RFC 3986 s5.3 has an empty reference inherit the base query, so a
        capsule serving "=> " on a page fetched with a password in the query got
        that password handed back in a link URL."""
        from gopher_mcp.helpers import resolve_gemini_reference

        base = "gemini://example.com/login?hunter2secret"
        assert "hunter2secret" not in resolve_gemini_reference(base, "")
        assert "hunter2secret" not in resolve_gemini_reference(base, "#anchor")

    def test_a_reference_with_its_own_query_is_unaffected(self):
        """ "?x" replaces rather than inherits, so it was never a leak and must
        keep working."""
        from gopher_mcp.helpers import resolve_gemini_reference

        base = "gemini://example.com/login?hunter2secret"
        assert (
            resolve_gemini_reference(base, "?fresh")
            == "gemini://example.com/login?fresh"
        )

    def test_ordinary_relative_resolution_is_unchanged(self):
        from gopher_mcp.helpers import resolve_gemini_reference

        base = "gemini://example.com/dir/page?secret"
        assert resolve_gemini_reference(base, "/a") == "gemini://example.com/a"
        assert (
            resolve_gemini_reference(base, "b.gmi") == "gemini://example.com/dir/b.gmi"
        )
