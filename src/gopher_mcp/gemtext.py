"""Gemtext parsing and rendering helpers.

Parses ``text/gemini`` content into the structured ``GemtextDocument`` model
(headings, links, lists, quotes, preformatted blocks). Depends only on the
models, so it sits below the protocol parsers in the import graph.
"""

from typing import Any, Optional

from .models import (
    GemtextDocument,
    GemtextHeading,
    GemtextLine,
    GemtextLineType,
    GemtextLink,
    GemtextList,
    GemtextPreformat,
    GemtextQuote,
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


def _extract_preformat_metadata(alt_text: str | None, content: str) -> dict[str, Any]:
    """Extract metadata from preformat block.

    Args:
        alt_text: Alt-text from preformat block
        content: Preformat content

    Returns:
        Metadata dictionary

    """
    metadata = {
        "language": _detect_language_from_alt_text(alt_text),
        "alt_text": alt_text,
        "line_count": len(content.splitlines()) if content else 0,
        "char_count": len(content) if content else 0,
        "is_code": False,
        "is_data": False,
    }

    # Determine content type based on language
    if metadata["language"]:
        code_languages = {
            "python",
            "javascript",
            "typescript",
            "rust",
            "go",
            "c",
            "cpp",
            "java",
            "kotlin",
            "swift",
            "ruby",
            "php",
            "bash",
        }
        data_languages = {"json", "xml", "yaml", "toml", "sql"}

        if metadata["language"] in code_languages:
            metadata["is_code"] = True
        elif metadata["language"] in data_languages:
            metadata["is_data"] = True

    return metadata


def _parse_gemtext_link_line(line: str) -> dict[str, str | None] | None:
    """Parse a gemtext link line.

    Format: =>[whitespace]<URL>[whitespace]<link-text>

    Args:
        line: Raw link line starting with '=>'

    Returns:
        Dict with 'url' and 'text' keys, or None if invalid

    """
    if not line.startswith("=>"):
        return None

    # Remove the '=>' prefix
    content = line[2:]

    # Split on whitespace to separate URL from text
    parts = content.split(None, 1)  # Split on any whitespace, max 1 split

    if not parts:
        return None  # No URL found

    url = parts[0].strip()
    if not url:
        return None  # Empty URL

    # Extract link text if present
    text = None
    if len(parts) > 1:
        text = parts[1].strip()
        if not text:  # Empty text after whitespace
            text = None

    return {"url": url, "text": text}


def _create_gemtext_line(
    line_type: "GemtextLineType",
    content: str,
    link: Optional["GemtextLink"] = None,
    heading: Optional["GemtextHeading"] = None,
    list_item: Optional["GemtextList"] = None,
    quote: Optional["GemtextQuote"] = None,
    preformat: Optional["GemtextPreformat"] = None,
    level: int | None = None,
    alt_text: str | None = None,
) -> "GemtextLine":
    """Create a GemtextLine object with the given parameters.

    Args:
        line_type: Type of the line
        content: Raw line content
        link: Link object if this is a link line
        heading: Heading object if this is a heading line
        list_item: List object if this is a list item line
        quote: Quote object if this is a quote line
        preformat: Preformat object if this is a preformat line
        level: Heading level if this is a heading line
        alt_text: Alt text for preformat blocks

    Returns:
        GemtextLine object
    """

    return GemtextLine(
        type=line_type,
        content=content,
        link=link,
        level=level,
        alt_text=alt_text,
        heading=heading,
        list_item=list_item,
        quote=quote,
        preformat=preformat,
    )


def _parse_heading(line_content: str) -> Optional["GemtextLine"]:
    """Parse a heading line.

    Args:
        line_content: Raw line content

    Returns:
        GemtextLine object if this is a heading, None otherwise
    """

    # Strip the leading marker run, then any extra '#'s (a 4th '#' is content,
    # not a 4th level -- gemtext only defines H1-H3), then surrounding space.
    if line_content.startswith("###"):
        heading_text = line_content[3:].lstrip("#").strip()
        heading_obj = GemtextHeading(
            level=3, text=heading_text, raw_content=line_content
        )
        return _create_gemtext_line(
            GemtextLineType.HEADING_3, line_content, heading=heading_obj, level=3
        )
    elif line_content.startswith("##"):
        heading_text = line_content[2:].lstrip("#").strip()
        heading_obj = GemtextHeading(
            level=2, text=heading_text, raw_content=line_content
        )
        return _create_gemtext_line(
            GemtextLineType.HEADING_2, line_content, heading=heading_obj, level=2
        )
    elif line_content.startswith("#"):
        heading_text = line_content[1:].lstrip("#").strip()
        heading_obj = GemtextHeading(
            level=1, text=heading_text, raw_content=line_content
        )
        return _create_gemtext_line(
            GemtextLineType.HEADING_1, line_content, heading=heading_obj, level=1
        )

    return None


def _parse_link(
    line_content: str,
) -> tuple["GemtextLine", Optional["GemtextLink"]] | None:
    """Parse a link line.

    Args:
        line_content: Raw line content

    Returns:
        Tuple of (GemtextLine, GemtextLink) if this is a valid link, (GemtextLine as text, None) if invalid link syntax, None if not a link
    """

    if not line_content.startswith("=>"):
        return None

    link_data = _parse_gemtext_link_line(line_content)
    if link_data and link_data["url"]:
        link_obj = GemtextLink(url=link_data["url"], text=link_data["text"])
        line = _create_gemtext_line(GemtextLineType.LINK, line_content, link=link_obj)
        return (line, link_obj)
    else:
        # Invalid link line, treat as text
        line = _create_gemtext_line(GemtextLineType.TEXT, line_content)
        return (line, None)


def _parse_list_item(line_content: str) -> Optional["GemtextLine"]:
    """Parse a list item line.

    Args:
        line_content: Raw line content

    Returns:
        GemtextLine object if this is a list item, None otherwise
    """

    if line_content.startswith("* "):
        list_text = line_content[2:].strip()
        list_obj = GemtextList(text=list_text, raw_content=line_content)
        return _create_gemtext_line(
            GemtextLineType.LIST_ITEM, line_content, list_item=list_obj
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
        quote_obj = GemtextQuote(text=quote_text, raw_content=line_content)
        return _create_gemtext_line(
            GemtextLineType.QUOTE, line_content, quote=quote_obj
        )

    return None


def _parse_text(line_content: str) -> "GemtextLine":
    """Parse a text line.

    Args:
        line_content: Raw line content

    Returns:
        GemtextLine object for text
    """

    return _create_gemtext_line(GemtextLineType.TEXT, line_content)


def parse_gemtext(content: str) -> "GemtextDocument":
    """Parse gemtext content into structured format.

    Args:
        content: Raw gemtext content

    Returns:
        Parsed gemtext document

    """

    lines = []
    links = []
    in_preformat = False
    current_alt_text = None

    # Split on CRLF/LF only. ``str.splitlines()`` also breaks on \v, \f, NEL,
    # U+2028/U+2029 etc., which are NOT gemtext line terminators and would
    # corrupt line structure. Drop a single trailing empty element so a final
    # newline doesn't synthesize an extra blank line (matching splitlines).
    normalized = content.replace("\r\n", "\n")
    raw_lines = normalized.split("\n")
    if raw_lines and raw_lines[-1] == "":
        raw_lines.pop()

    for raw_line in raw_lines:
        # Preformatted content must be preserved verbatim; only rstrip lines we
        # are about to classify in normal mode.
        line_content = raw_line if in_preformat else raw_line.rstrip()

        # Handle preformat mode
        if in_preformat:
            # Check for preformat toggle (end)
            if line_content.startswith("```"):
                # End preformat block
                in_preformat = False
                current_alt_text = None
                preformat_obj = GemtextPreformat(
                    content=line_content,
                    alt_text=None,
                    is_toggle=True,
                    language=None,
                    metadata={},
                )
                lines.append(
                    _create_gemtext_line(
                        GemtextLineType.PREFORMAT,
                        line_content,
                        preformat=preformat_obj,
                        alt_text=current_alt_text,
                    )
                )
                continue
            else:
                # Regular preformat content
                metadata = _extract_preformat_metadata(current_alt_text, line_content)
                preformat_obj = GemtextPreformat(
                    content=line_content,
                    alt_text=current_alt_text,
                    is_toggle=False,
                    language=metadata["language"],
                    metadata=metadata,
                )
                lines.append(
                    _create_gemtext_line(
                        GemtextLineType.PREFORMAT,
                        line_content,
                        preformat=preformat_obj,
                        alt_text=current_alt_text,
                    )
                )
                continue

        # Normal mode - recognize line types
        if line_content.startswith("```"):
            # Start preformat block
            in_preformat = True
            # Extract alt text (everything after ``` and optional whitespace)
            alt_text_part = line_content[3:].strip()
            current_alt_text = alt_text_part if alt_text_part else None
            metadata = _extract_preformat_metadata(current_alt_text, line_content)
            preformat_obj = GemtextPreformat(
                content=line_content,
                alt_text=current_alt_text,
                is_toggle=True,
                language=metadata["language"],
                metadata=metadata,
            )
            lines.append(
                _create_gemtext_line(
                    GemtextLineType.PREFORMAT,
                    line_content,
                    preformat=preformat_obj,
                    alt_text=current_alt_text,
                )
            )

        elif line_content.startswith("=>"):
            # Link line
            result = _parse_link(line_content)
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
            lines.append(_parse_text(line_content))

    return GemtextDocument(lines=lines, links=links)
