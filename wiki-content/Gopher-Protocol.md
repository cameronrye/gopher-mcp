# Gopher Protocol Guide

Understanding the Gopher protocol and how it's implemented in the MCP server.

## What is Gopher?

The Gopher protocol is a TCP-based document retrieval protocol designed in 1991 at the University of Minnesota. It predates the World Wide Web and provides a simple, hierarchical menu-based interface for accessing documents and services.

## Protocol Basics

### Connection

- **Protocol**: TCP
- **Default Port**: 70
- **Encryption**: None (standard Gopher)

### Request Format

```
<selector><TAB><search><CR><LF>
```

- Selector: Path to the resource
- Search: Optional search query (for type 7)
- CR LF: Carriage return and line feed

### Response Format

Gopher servers return raw data without headers. The format depends on the item type.

## Gopher Item Types

| Type | Description    | Example              |
| ---- | -------------- | -------------------- |
| 0    | Text file      | Plain text documents |
| 1    | Directory/Menu | Hierarchical menus   |
| 2    | CSO phone book | Name server          |
| 3    | Error          | Error message        |
| 4    | BinHex file    | Macintosh file       |
| 5    | DOS binary     | PC binary file       |
| 6    | UUEncoded file | Unix file            |
| 7    | Search server  | Full-text search     |
| 8    | Telnet session | Telnet link          |
| 9    | Binary file    | Generic binary       |
| g    | GIF image      | GIF file             |
| I    | Image file     | Other image          |
| h    | HTML file      | HTML document        |
| i    | Info line      | Non-selectable text  |
| s    | Sound file     | Audio file           |

## Menu Format

Gopher menus (type 1) use a specific line format:

```
<type><display text><TAB><selector><TAB><host><TAB><port><CR><LF>
```

Example:

```
0Welcome Text /welcome.txt gopher.example.com 70
1Subdirectory /subdir gopher.example.com 70
iInformation line fake null 0
```

## URL Format

Gopher URLs follow this format:

```
gopher://<host>[:<port>]/<type><selector>[?<search>]
```

Examples:

```
gopher://gopher.floodgap.com/1/
gopher://gopher.floodgap.com:70/0/gopher/welcome
gopher://gopher.floodgap.com/7/v2/vs?python
```

## Implementation in MCP Server

### Supported Features

- **Menu Browsing** (type 1): Full menu parsing and navigation
- **Text Files** (type 0): Complete text file retrieval
- **Search** (type 7): Search server support with queries
- **Binary Metadata** (types 4, 5, 6, 9, g, I): Metadata without download

### URL Parsing

The server parses Gopher URLs into components:

```python
{
    "host": "gopher.floodgap.com",
    "port": 70,
    "gopher_type": "1",
    "selector": "/",
    "search": None
}
```

### Response Processing

#### Menu Response (Type 1)

Returns structured menu items:

```json
{
  "kind": "menu",
  "items": [
    {
      "type": "1",
      "title": "Directory Name",
      "selector": "/path",
      "host": "gopher.example.com",
      "port": 70,
      "nextUrl": "gopher://gopher.example.com:70/1/path"
    }
  ]
}
```

#### Text Response (Type 0)

Returns text content:

```json
{
  "kind": "text",
  "content": "File content here...",
  "metadata": {
    "size": 1234,
    "encoding": "utf-8"
  }
}
```

#### Binary Response (Types 4, 5, 6, 9, g, I)

Returns metadata only:

```json
{
  "kind": "binary",
  "metadata": {
    "type": "9",
    "size": 5678,
    "description": "Binary file"
  }
}
```

## Security Considerations

### Input Validation

- URL format validation
- Selector length limits (max 1024 characters)
- Search query length limits (max 256 characters)
- Host allowlist support

### Resource Limits

- Maximum response size (default 1MB)
- Connection timeout (default 30 seconds)
- Read timeout enforcement

### Binary File Protection

Binary files return metadata only to prevent:

- Memory exhaustion
- Malicious file downloads
- Unnecessary bandwidth usage

## Popular Gopher Servers

### Floodgap Systems

```
gopher://gopher.floodgap.com/1/
```

The most well-known Gopher server, maintained by Cameron Kaiser. Contains extensive Gopher resources and information.

### Quux.org

```
gopher://quux.org/1/
```

Long-running Gopher server with various content.

### Gopher Lawn

```
gopher://gopherlawn.net/1/
```

Community Gopher server with user-contributed content.

## Best Practices

### For Users

1. Start with main menus (type 1)
2. Follow menu structure hierarchically
3. Use search (type 7) for finding content
4. Be patient with slow servers

### For Developers

1. Always validate URLs before requests
2. Implement proper timeout handling
3. Parse menu items carefully
4. Handle errors gracefully
5. Respect server resources

## Common Issues

### Empty Menus

Some servers return empty menus for certain paths. This is normal behavior.

### Slow Responses

Gopher servers may be slow or intermittent. Use appropriate timeouts.

### Character Encoding

Gopher predates Unicode. Most content is ASCII or ISO-8859-1.

## Further Reading

- [RFC 1436](https://tools.ietf.org/html/rfc1436) - The Gopher Protocol
- [Gopher Wikipedia](<https://en.wikipedia.org/wiki/Gopher_(protocol)>)
- [Floodgap Gopher](https://gopher.floodgap.com/gopher/)

---

Made with ❤️ by [Cameron Rye](https://rye.dev/)
