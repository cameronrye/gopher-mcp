"""Gemtext parsing and rendering helpers.

Parses ``text/gemini`` content into the structured ``GemtextDocument`` model
(headings, links, lists, quotes, preformatted blocks). Depends only on the
models, so it sits below the protocol parsers in the import graph.
"""

from typing import Optional

from .helpers import resolve_gemini_reference, sanitize_display_text
from .models import (
    GemtextDocument,
    GemtextLine,
    GemtextLineType,
    GemtextLink,
)


def _detect_language_from_alt_text(alt_text: str | None) -> str | None:
    """Detect programming language from preformat alt-text.

    Args:
        alt_text: Alt-text from preformat block

    Returns:
        Detected language or None

    """
    if not alt_text:
        return None

    # Normalize alt-text for comparison
    alt_lower = alt_text.lower().strip()

    # Common programming language mappings
    language_map = {
        "python": "python",
        "py": "python",
        "javascript": "javascript",
        "js": "javascript",
        "typescript": "typescript",
        "ts": "typescript",
        "rust": "rust",
        "rs": "rust",
        "go": "go",
        "golang": "go",
        "c": "c",
        "cpp": "cpp",
        "c++": "cpp",
        "java": "java",
        "kotlin": "kotlin",
        "swift": "swift",
        "ruby": "ruby",
        "rb": "ruby",
        "php": "php",
        "html": "html",
        "css": "css",
        "sql": "sql",
        "bash": "bash",
        "sh": "bash",
        "shell": "bash",
        "json": "json",
        "xml": "xml",
        "yaml": "yaml",
        "yml": "yaml",
        "toml": "toml",
        "markdown": "markdown",
        "md": "markdown",
        "text": "text",
        "txt": "text",
    }

    return language_map.get(alt_lower)


def _parse_gemtext_link_line(
    line: str, base_url: str | None = None
) -> Optional["GemtextLink"]:
    """Parse a gemtext link line.

    Format: =>[whitespace]<URL>[whitespace]<link-text>

    Args:
        line: Raw link line starting with '=>'
        base_url: URL the document was fetched from, used to resolve a relative
            reference into an absolute URL the caller can actually fetch.
            Relative references are the norm in gemtext.

    Returns:
        The parsed link, or None if the line carries no usable URL

    """
    if not line.startswith("=>"):
        return None

    # Remove the '=>' prefix
    content = line[2:]

    # Split on whitespace to separate URL from text
    parts = content.split(None, 1)  # Split on any whitespace, max 1 split

    if not parts:
        return None  # No URL found

    url = sanitize_display_text(parts[0].strip(), keep_whitespace=False)
    if not url:
        return None  # Empty URL

    if base_url:
        url = resolve_gemini_reference(base_url, url)

    # Extract link text if present
    text = None
    if len(parts) > 1:
        text = sanitize_display_text(parts[1].strip(), keep_whitespace=False)
        if not text:  # Empty text after whitespace
            text = None

    return GemtextLink(url=url, text=text)


def _create_gemtext_line(
    line_type: "GemtextLineType",
    content: str,
    *,
    link: Optional["GemtextLink"] = None,
    text: str | None = None,
    level: int | None = None,
    alt_text: str | None = None,
    language: str | None = None,
) -> "GemtextLine":
    """Build a ``GemtextLine``, defaulting the fields this line type doesn't use.

    ``GemtextLine`` declares its optional fields as ``Field(None, ...)``, whose
    default mypy does not see through ``dataclass_transform`` -- it treats all
    of them as required. This wrapper is the one place that spells them all out,
    so a caller passes only the fields its line type populates.

    Args:
        line_type: Type of the line
        content: Raw line content, marker included
        link: Link target and text if this is a link line
        text: Marker-stripped text for a heading, list item or quote
        level: Heading level if this is a heading line
        alt_text: Alt text of a preformat block, on its opening toggle
        language: Language recognised from the alt text, on the same toggle

    Returns:
        GemtextLine object
    """

    return GemtextLine(
        type=line_type,
        content=content,
        text=text,
        link=link,
        level=level,
        alt_text=alt_text,
        language=language,
    )


def _parse_heading(line_content: str) -> Optional["GemtextLine"]:
    """Parse a heading line.

    Args:
        line_content: Raw line content

    Returns:
        GemtextLine object if this is a heading, None otherwise
    """

    if not line_content.startswith("#"):
        return None

    # Gemtext defines H1-H3 only, so the marker run is capped at three: a 4th
    # consecutive '#' is the first character of the heading text, not a deeper
    # level, and must be kept ("####note" is an H3 reading "#note").
    marker_length = len(line_content) - len(line_content.lstrip("#"))
    level = min(marker_length, 3)
    heading_text = line_content[level:].strip()
    line_type = {
        1: GemtextLineType.HEADING_1,
        2: GemtextLineType.HEADING_2,
        3: GemtextLineType.HEADING_3,
    }[level]

    return _create_gemtext_line(line_type, line_content, text=heading_text, level=level)


def _parse_link(
    line_content: str, base_url: str | None = None
) -> tuple["GemtextLine", Optional["GemtextLink"]] | None:
    """Parse a link line.

    Args:
        line_content: Raw line content
        base_url: URL the document was fetched from, used to resolve a relative
            link reference

    Returns:
        Tuple of (GemtextLine, GemtextLink) if this is a valid link, (GemtextLine as text, None) if invalid link syntax, None if not a link
    """

    if not line_content.startswith("=>"):
        return None

    link_obj = _parse_gemtext_link_line(line_content, base_url)
    if link_obj is None:
        # Invalid link line, treat as text
        return (_create_gemtext_line(GemtextLineType.TEXT, line_content), None)

    line = _create_gemtext_line(GemtextLineType.LINK, line_content, link=link_obj)
    return (line, link_obj)


def _parse_list_item(line_content: str) -> Optional["GemtextLine"]:
    """Parse a list item line.

    Args:
        line_content: Raw line content

    Returns:
        GemtextLine object if this is a list item, None otherwise
    """

    if line_content.startswith("* "):
        list_text = line_content[2:].strip()
        return _create_gemtext_line(
            GemtextLineType.LIST_ITEM, line_content, text=list_text
        )

    return None


def _parse_quote(line_content: str) -> Optional["GemtextLine"]:
    """Parse a quote line.

    Args:
        line_content: Raw line content

    Returns:
        GemtextLine object if this is a quote, None otherwise
    """

    if line_content.startswith(">"):
        # Remove at most a single space after '>', preserving any intentional
        # inner indentation of the quoted text (the gemtext convention).
        quote_text = line_content[1:].removeprefix(" ")
        return _create_gemtext_line(
            GemtextLineType.QUOTE, line_content, text=quote_text
        )

    return None


def gemtext_state_at(text: str, offset: int) -> tuple[bool, bool]:
    """Return the parse state a window of ``text`` starting at ``offset`` resumes in.

    A continuation window is not the top of a document, but
    :func:`parse_gemtext` classifies from the top of whatever it is handed. Two
    bits of state decide what the resumed lines mean, and both are recoverable
    from the surrounding document: whether the resume point sits inside a
    preformat block, and whether it sits inside a line.

    This takes the whole text rather than just the prefix because a cut can land
    INSIDE a fence marker. Given "```\\n=> url text" cut at 1, the prefix is a
    single backtick, which starts no fence -- but the line it belongs to does,
    and judging it by its prefix alone reports "not in a preformat block" and
    lets the window parse the fenced link as a real one. The line the cut lands
    in has to be judged whole, so the toggle is read from ``text`` at the line's
    real start.

    Returns:
        ``(in_preformat, starts_mid_line)``

    """
    offset = min(max(offset, 0), len(text))
    if offset == 0:
        return False, False

    # Start of the line the cut lands in. Bare CR is a terminator here for the
    # same reason it is in the parser: a legacy capsule can use it alone.
    line_start = max(text.rfind("\n", 0, offset), text.rfind("\r", 0, offset)) + 1
    starts_mid_line = line_start < offset

    # Every ``` line toggles, in both directions, so parity over the completed
    # lines is the whole state.
    head = text[:line_start]
    completed = head.replace("\r\n", "\n").replace("\r", "\n").split("\n")[:-1]
    toggles = sum(line.startswith("```") for line in completed)
    # ... plus the straddling line itself, whose marker sits in the prefix and
    # whose tail is the window's first fragment: the toggle belongs to the line,
    # and by the time the window resumes, that line has already happened.
    if starts_mid_line and text.startswith("```", line_start):
        toggles += 1

    return toggles % 2 == 1, starts_mid_line


def parse_gemtext(
    content: str,
    base_url: str | None = None,
    *,
    in_preformat: bool = False,
    starts_mid_line: bool = False,
) -> "GemtextDocument":
    """Parse gemtext content into structured format.

    Args:
        content: Raw gemtext content
        base_url: URL the content was fetched from. Relative link references are
            resolved against it so every returned link is directly fetchable;
            without it they are returned as written.
        in_preformat: Whether this content resumes inside a preformat block. A
            continuation window that starts inside one must not read its
            contents as live markup -- a fenced ``=>`` is sample text, and
            typing it as a link hands the caller a target the capsule never
            offered. Defaults to false, which is correct for a whole document.
        starts_mid_line: Whether the first line is the tail of a line that began
            before this content. Such a fragment is emitted verbatim and never
            classified, for the same reason the cut end of a window is not: half
            a ``=> url text`` line must never arrive as a whole link.

    Returns:
        Parsed gemtext document

    """

    lines = []
    links = []

    # Strip control characters before splitting: the body is server-controlled
    # and reaches the model (and often a terminal) verbatim, and the latin-1
    # decode fallback maps 0x80-0x9F to C1 controls (0x9B is a single-byte CSI).
    # Line-structural whitespace is preserved.
    content = sanitize_display_text(content)

    # Split on CRLF/LF/CR only. ``str.splitlines()`` also breaks on \v, \f, NEL,
    # U+2028/U+2029 etc., which are NOT gemtext line terminators and would
    # corrupt line structure; a legacy bare CR is one, and without normalizing it
    # a whole page would collapse into a single text line. Drop a single trailing
    # empty element so a final newline doesn't synthesize an extra blank line
    # (matching splitlines).
    normalized = content.replace("\r\n", "\n").replace("\r", "\n")
    raw_lines = normalized.split("\n")
    if raw_lines and raw_lines[-1] == "":
        raw_lines.pop()

    if starts_mid_line and raw_lines:
        # The tail of a line that began in an earlier window. Its opening
        # characters are not at a line start, so nothing in it is a marker: a
        # leading ``=>`` is the middle of a sentence, and a leading ``` cannot
        # toggle a block. Emit it verbatim, unclassified, so every character
        # still reaches the caller carrying no target.
        fragment = raw_lines.pop(0)
        lines.append(
            _create_gemtext_line(
                GemtextLineType.PREFORMAT if in_preformat else GemtextLineType.TEXT,
                fragment,
            )
        )

    for raw_line in raw_lines:
        # Preformatted content must be preserved verbatim; only rstrip lines we
        # are about to classify in normal mode.
        line_content = raw_line if in_preformat else raw_line.rstrip()

        # Handle preformat mode
        if in_preformat:
            # A line inside a block carries nothing but its verbatim content:
            # the alt text and the language it implies describe the block, and
            # belong on the opening toggle that declared them. Repeating them
            # (and, before that, a 6-key metadata dict) on every line was pure
            # serialized bloat, and ``type`` already says a ``` line is a
            # toggle.
            if line_content.startswith("```"):
                in_preformat = False
            lines.append(_create_gemtext_line(GemtextLineType.PREFORMAT, line_content))
            continue

        # Normal mode - recognize line types
        if line_content.startswith("```"):
            # Start preformat block
            in_preformat = True
            # Extract alt text (everything after ``` and optional whitespace)
            alt_text_part = line_content[3:].strip()
            alt_text = alt_text_part if alt_text_part else None
            lines.append(
                _create_gemtext_line(
                    GemtextLineType.PREFORMAT,
                    line_content,
                    alt_text=alt_text,
                    language=_detect_language_from_alt_text(alt_text),
                )
            )

        elif line_content.startswith("=>"):
            # Link line
            result = _parse_link(line_content, base_url)
            if result:
                line, link_obj = result
                lines.append(line)
                if link_obj:
                    links.append(link_obj)

        elif (heading_line := _parse_heading(line_content)) is not None:
            lines.append(heading_line)

        elif (list_line := _parse_list_item(line_content)) is not None:
            lines.append(list_line)

        elif (quote_line := _parse_quote(line_content)) is not None:
            lines.append(quote_line)

        else:
            # Default: text line
            lines.append(_create_gemtext_line(GemtextLineType.TEXT, line_content))

    return GemtextDocument(lines=lines, links=links)
