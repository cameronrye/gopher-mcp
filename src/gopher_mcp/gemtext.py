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


def parse_gemtext(content: str, base_url: str | None = None) -> "GemtextDocument":
    """Parse gemtext content into structured format.

    Args:
        content: Raw gemtext content
        base_url: URL the content was fetched from. Relative link references are
            resolved against it so every returned link is directly fetchable;
            without it they are returned as written.

    Returns:
        Parsed gemtext document

    """

    lines = []
    links = []
    in_preformat = False

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
