# AI Assistant Guide

This guide helps AI assistants effectively use the Gopher & Gemini MCP Server to explore alternative internet protocols.

## Quick Start

The server provides two main tools:

- **`gopher_fetch`**: For exploring Gopherspace (vintage internet protocol)
- **`gemini_fetch`**: For exploring Geminispace (modern privacy-focused protocol)

## Understanding the Protocols

### Gopher Protocol

Gopher is a vintage internet protocol from 1991 that predates the Web:

- **Menu-based navigation**: Hierarchical directory structure
- **Simple text format**: Plain text with minimal markup
- **No encryption**: All traffic is unencrypted
- **Unique communities**: Active communities with vintage computing focus

### Gemini Protocol

Gemini is a modern protocol designed for privacy and simplicity:

- **Mandatory TLS**: All connections are encrypted
- **Gemtext markup**: Lightweight text format with basic formatting
- **Privacy-focused**: Minimal tracking and data collection
- **Certificate-based auth**: Uses client certificates for authentication

## Using `gopher_fetch`

### Basic Usage

```
gopher_fetch("gopher://gopher.floodgap.com/1/")
```

### Response Handling

Always check the `kind` field to determine response type:

```python
result = gopher_fetch(url)

if result["kind"] == "menu":
    # Handle menu items
    for item in result["items"]:
        print(f"{item['type']}: {item['display_text']}")

elif result["kind"] == "text":
    # Handle text content
    print(result["content"])

elif result["kind"] == "binary":
    # Handle binary file metadata
    print(f"Binary file: {result['description']}")

elif result["kind"] == "error":
    # Handle errors
    print(f"Error: {result['error']}")
```

### Gopher Item Types

| Type | Description | Action |
|------|-------------|--------|
| `0` | Text file | Fetch and display content |
| `1` | Menu/Directory | Browse submenu |
| `7` | Search server | Prompt for search terms |
| `4,5,6,9,g,I` | Binary files | Show metadata only |
| `h` | HTML file | Fetch and display |
| `i` | Info text | Display as-is |

### Navigation Patterns

1. **Start with root menu**: `gopher://hostname/1/`
2. **Follow menu items**: Use the `url` field from menu items
3. **Handle search servers**: Type 7 items require search terms
4. **Respect binary files**: Don't fetch large binary content

### Common Gopher Sites

- `gopher://gopher.floodgap.com/1/` - Floodgap (main Gopher site)
- `gopher://gopher.quux.org/1/` - Quux.org
- `gopher://sdf.org/1/` - SDF Public Access UNIX System
- `gopher://gopherpedia.com/1/` - Gopherpedia (Wikipedia mirror)

## Using `gemini_fetch`

### Basic Usage

```
gemini_fetch("gemini://geminiprotocol.net/")
```

### Response Handling

Handle different response types based on `kind`:

```python
result = gemini_fetch(url)

if result["kind"] == "gemtext":
    # Handle gemtext content
    doc = result["document"]
    for line in doc["lines"]:
        if line["type"] == "heading1":
            print(f"# {line['text']}")
        elif line["type"] == "link":
            print(f"Link: {line['text']} -> {line['url']}")
        elif line["type"] == "text":
            print(line["text"])

elif result["kind"] == "success":
    # Handle other content types
    mime = result["mime_type"]
    if mime["is_text"]:
        print(result["content"])
    else:
        print(f"Binary content: {mime['full_type']}")

elif result["kind"] == "input":
    # Handle input requests
    print(f"Input required: {result['prompt']}")
    # Note: In MCP context, you cannot provide input

elif result["kind"] == "redirect":
    # Handle redirects
    new_url = result["url"]
    print(f"Redirected to: {new_url}")
    # Follow redirect if appropriate

elif result["kind"] == "error":
    # Handle errors
    print(f"Error {result['status']}: {result['message']}")
```

### Gemini Status Codes

| Range | Type | Handling |
|-------|------|----------|
| 10-11 | Input | Cannot provide input in MCP context |
| 20-29 | Success | Process content normally |
| 30-31 | Redirect | Follow redirect if appropriate |
| 40-49 | Temporary Error | May retry later |
| 50-59 | Permanent Error | Do not retry |
| 60-69 | Certificate Required | Cannot provide certificates in MCP context |

### Gemtext Format

Gemtext is a lightweight markup format:

```
# Heading 1
## Heading 2
### Heading 3

Regular paragraph text.

* List item
* Another list item

> Quoted text

```
Preformatted text block
```

=> gemini://example.org/ Link with text
=> gemini://example.org/
```

### Common Gemini Sites

- `gemini://geminiprotocol.net/` - Gemini protocol homepage
- `gemini://warmedal.se/~antenna/` - Antenna (gemlog aggregator)
- `gemini://kennedy.gemi.dev/` - Kennedy (search engine)
- `gemini://rawtext.club/` - Rawtext Club (community)

## Best Practices

### For Both Protocols

1. **Always check response type**: Use the `kind` field to determine how to handle responses
2. **Handle errors gracefully**: Provide helpful error messages to users
3. **Respect rate limits**: Don't make too many requests in quick succession
4. **Follow redirects carefully**: Check for redirect loops
5. **Be mindful of content size**: Large responses may be truncated

### Gopher-Specific

1. **Start with menus**: Begin exploration with directory listings
2. **Understand item types**: Different types require different handling
3. **Handle search servers**: Type 7 items need search terms appended to URL
4. **Respect the vintage nature**: Gopher content often reflects historical computing

### Gemini-Specific

1. **Parse gemtext properly**: Use the structured document format
2. **Handle input requests**: Explain that input cannot be provided in MCP context
3. **Follow certificate requirements**: Some sites require client certificates
4. **Respect privacy focus**: Gemini emphasizes privacy and minimal tracking

## Common Use Cases

### Content Discovery

```python
# Explore a Gopher menu
result = gopher_fetch("gopher://gopher.floodgap.com/1/")
if result["kind"] == "menu":
    for item in result["items"]:
        if item["type"] == "1":  # Submenu
            print(f"Directory: {item['display_text']}")
        elif item["type"] == "0":  # Text file
            print(f"Text file: {item['display_text']}")

# Browse Gemini content
result = gemini_fetch("gemini://geminiprotocol.net/")
if result["kind"] == "gemtext":
    # Show headings and links
    for heading in result["document"]["headings"]:
        print(f"Section: {heading['text']}")
    for link in result["document"]["links"]:
        print(f"Link: {link['text']} -> {link['url']}")
```

### Search Operations

```python
# Gopher search (Veronica-2)
search_url = "gopher://gopher.floodgap.com/7/v2/vs?python"
result = gopher_fetch(search_url)
if result["kind"] == "menu":
    print(f"Found {len(result['items'])} results for 'python'")

# Note: Gemini doesn't have built-in search, but some sites provide search pages
```

### Content Analysis

```python
# Analyze gemtext structure
result = gemini_fetch("gemini://example.org/article")
if result["kind"] == "gemtext":
    doc = result["document"]
    print(f"Article has {len(doc['headings'])} sections")
    print(f"Contains {len(doc['links'])} links")
    print(f"Total lines: {len(doc['lines'])}")
```

## Error Handling

### Common Errors

1. **Connection timeouts**: Server not responding
2. **Invalid URLs**: Malformed protocol URLs
3. **Certificate issues**: TLS/TOFU problems (Gemini only)
4. **Content too large**: Response exceeds size limits
5. **Host restrictions**: Server not in allowlist

### Error Recovery

```python
def safe_fetch(url, protocol="auto"):
    try:
        if protocol == "gopher" or url.startswith("gopher://"):
            return gopher_fetch(url)
        elif protocol == "gemini" or url.startswith("gemini://"):
            return gemini_fetch(url)
    except Exception as e:
        return {
            "kind": "error",
            "error": str(e),
            "suggestions": [
                "Check if the URL is correct",
                "Verify the server is online",
                "Try again later if it's a temporary issue"
            ]
        }
```

## Tips for AI Assistants

1. **Explain the protocols**: Help users understand what Gopher and Gemini are
2. **Provide context**: Explain the vintage/modern nature of the protocols
3. **Suggest starting points**: Recommend good sites for exploration
4. **Handle limitations**: Explain when input or certificates are required
5. **Encourage exploration**: These protocols have unique communities and content
6. **Respect the culture**: Both protocols have distinct communities and etiquette

## Troubleshooting

### Common Issues

1. **"Host not allowed"**: Server not in configured allowlist
2. **"Certificate validation failed"**: TOFU or TLS certificate issues
3. **"Input required"**: Site needs user input (not possible in MCP)
4. **"Client certificate required"**: Site needs client authentication
5. **"Content too large"**: Response exceeds configured size limit

### Solutions

1. Check server configuration and allowlists
2. Verify TLS/certificate settings
3. Explain limitations to users
4. Try alternative sites or content
5. Adjust size limits if appropriate

Remember: These protocols offer unique perspectives on internet content and communities. Encourage exploration while respecting the distinct cultures and technical constraints of each protocol.
