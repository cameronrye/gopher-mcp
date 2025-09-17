# Gopher Protocol Complete Specification for LLMs

> **Comprehensive reference for Large Language Models to become experts on the Gopher protocol**
>
> Based on RFC 1436 (The Internet Gopher Protocol) and RFC 4266 (The gopher URI Scheme)

## Table of Contents

1. [Protocol Overview](#protocol-overview)
2. [Core Protocol Mechanics](#core-protocol-mechanics)
3. [URI Scheme Specification](#uri-scheme-specification)
4. [Item Types and Data Formats](#item-types-and-data-formats)
5. [Protocol Transactions](#protocol-transactions)
6. [Gopher+ Extensions](#gopher-extensions)
7. [Technical Implementation Details](#technical-implementation-details)
8. [Security and Practical Considerations](#security-and-practical-considerations)
9. [Examples and Use Cases](#examples-and-use-cases)
10. [Complete BNF Grammar](#complete-bnf-grammar)

---

## Protocol Overview

### What is Gopher?

The Internet Gopher protocol is a **distributed document search and retrieval protocol** designed for simplicity and efficiency. It follows a strict **client-server model** using **TCP connections** on **port 70** (default).

### Key Characteristics

- **Stateless**: No state retained between transactions
- **Simple**: Text-based protocol, easily debuggable with telnet
- **Hierarchical**: File system-like organization of documents and directories
- **Distributed**: Documents can reside on multiple autonomous servers
- **Extensible**: Type system allows for different document and service types

### Basic Model

```
Client connects → Sends selector string → Server responds with data → Connection closes
```

**Core Principle**: Client sends a selector string (line of text, may be empty) terminated by CRLF. Server responds with data terminated by a line containing only "." and closes connection.

---

## Core Protocol Mechanics

### Connection Process

1. **Client** opens TCP connection to server on port 70
2. **Server** accepts connection but sends nothing initially
3. **Client** sends selector string + CRLF (`\r\n`)
4. **Server** sends response data + termination marker
5. **Connection** closed by server (typically)

### Selector Strings

- **Format**: Sequence of octets (may be empty)
- **Restrictions**: Cannot contain:
  - `0x09` (TAB character)
  - `0x0A` (Line Feed)
  - `0x0D` (Carriage Return)
- **Maximum length**: 255 characters (recommended)
- **Empty selector**: Refers to top-level directory

### Response Termination

- **Text/Menu responses**: Terminated by line containing only "." followed by CRLF
- **Binary responses**: Connection close indicates end of data
- **Line escaping**: Lines beginning with "." must be prepended with extra "." (client strips it)

---

## URI Scheme Specification

### Basic Syntax

```
gopher://<host>:<port>/<gopher-path>
```

Where `<gopher-path>` is one of:
- `<gophertype><selector>`
- `<gophertype><selector>%09<search>`
- `<gophertype><selector>%09<search>%09<gopher+_string>`

### Components

- **host**: Fully qualified domain name
- **port**: TCP port number (default: 70, omit `:70` in URLs)
- **gophertype**: Single character indicating item type
- **selector**: Gopher selector string (URL-encoded if necessary)
- **search**: Search string for type 7 items (preceded by `%09`)
- **gopher+_string**: Gopher+ extensions (preceded by `%09`)

### Default Behaviors

- **Missing port**: Defaults to 70
- **Empty path**: Defaults to gophertype "1" (directory)
- **Missing gophertype**: Defaults to "1" when path is empty

### URL Encoding

- **TAB character**: Encoded as `%09`
- **Special characters**: Standard URL encoding applies
- **Selector restrictions**: Same as protocol (no unencoded TAB, CR, LF)

---

## Item Types and Data Formats

### Core Item Types

| Type | Description | Transaction Type |
|------|-------------|------------------|
| `0` | Text file | TextFile Transaction |
| `1` | Directory/Menu | Menu Transaction |
| `2` | CSO phone book server | CSO Protocol |
| `3` | Error | Error message |
| `4` | BinHexed Macintosh file | Binary Transaction |
| `5` | DOS binary archive | Binary Transaction |
| `6` | UNIX uuencoded file | Binary Transaction |
| `7` | Index-Search server | Search Transaction |
| `8` | Text-based telnet session | Telnet |
| `9` | Binary file | Binary Transaction |
| `+` | Redundant server | Same as primary |
| `T` | Text-based tn3270 session | TN3270 |
| `g` | GIF graphics file | Binary Transaction |
| `I` | Image file (generic) | Binary Transaction |

### Menu Format

Each menu line follows this exact format:
```
<type><display_string><TAB><selector><TAB><host><TAB><port><CRLF>
```

**Components:**
- **type**: Single character item type
- **display_string**: Human-readable name (≤70 characters recommended)
- **selector**: Selector string for retrieving this item
- **host**: Hostname where item resides
- **port**: Port number (typically 70)

**Character encoding**: ASCII recommended, ISO Latin1 acceptable for display strings

### Text File Format

```
<text_content>
.
```

- Content can be any text
- Lines starting with "." must be escaped with additional "."
- Terminated by line containing only "."
- Client should handle server closing connection without terminator

---

## Protocol Transactions

### Menu Transaction (Type 1)

**Client Request:**
```
<selector><CRLF>
```

**Server Response:**
```
<type><display><TAB><selector><TAB><host><TAB><port><CRLF>
<type><display><TAB><selector><TAB><host><TAB><port><CRLF>
...
.<CRLF>
```

### Text File Transaction (Type 0)

**Client Request:**
```
<selector><CRLF>
```

**Server Response:**
```
<text_content>
.<CRLF>
```

### Search Transaction (Type 7)

**Client Request:**
```
<selector><TAB><search_string><CRLF>
```

**Server Response:**
```
<menu_format_results>
.<CRLF>
```

**Search Logic:**
- Spaces typically treated as Boolean AND
- Returns virtual directory listing of matching documents
- Search string follows selector with TAB separator

### Binary Transaction (Types 4, 5, 6, 9, g, I)

**Client Request:**
```
<selector><CRLF>
```

**Server Response:**
```
<binary_data>
<connection_closes>
```

**Important**: No termination marker - connection close indicates end of data.

---

## Gopher+ Extensions

### Overview

Gopher+ provides upward-compatible extensions to base Gopher protocol, supporting:
- Item attributes
- Alternate data representations
- Electronic forms
- Enhanced metadata

### Gopher+ Item Identification

In directory listings, Gopher+ items are tagged:
- `+`: Standard Gopher+ item
- `?`: Gopher+ item with electronic form (+ASK)

### Attribute Access

**All attributes**: `gopher://host/1selector%09%09!`
**Specific attribute**: `gopher://host/1selector%09%09!+ABSTRACT`
**Multiple attributes**: `gopher://host/1selector%09%09!+ABSTRACT%20+SMELL`

### Alternate Views

**Syntax**: `gopher://host/1selector%09%09+<view_name>%20<language>`
**Example**: `gopher://host/1selector%09%09+application/postscript%20Es_ES`

### Electronic Forms

**URL Format**: Complex encoded form data
**Protocol**: Client fetches +ASK attribute, presents form, submits responses

---

## Technical Implementation Details

### Character Encoding

- **Protocol**: ASCII for control characters
- **Display strings**: ASCII recommended, ISO Latin1 acceptable
- **Selectors**: Byte sequences (no encoding specified)
- **Text content**: Typically ASCII or ISO Latin1

### Connection Handling

- **Client**: Must handle server closing connection
- **Server**: Should close connection after sending response
- **Timeouts**: Implement reasonable connection timeouts
- **Errors**: Type 3 items indicate error conditions

### Practical Limits

- **Display strings**: ≤70 characters (screen width considerations)
- **Selectors**: ≤255 characters (recommended)
- **Port range**: 0-65535 (standard TCP range)
- **Line length**: No hard limit, but reasonable limits recommended

### Error Handling

- **Type 3 items**: Error messages in menu format
- **Connection failures**: Handle gracefully
- **Malformed responses**: Implement defensive parsing
- **Unknown types**: Ignore or display as unknown

---

## Security and Practical Considerations

### Security Limitations

⚠️ **Critical Security Issues:**
- **No encryption**: All data transmitted in plaintext
- **No authentication**: Passwords (if used) sent in clear
- **No privacy**: Assume all communications are public
- **No integrity**: No protection against data modification

### Recommended Practices

- **Public data only**: Never transmit sensitive information
- **Input validation**: Sanitize all selector strings
- **Resource limits**: Implement timeouts and size limits
- **Access control**: Use external mechanisms if needed

### Implementation Considerations

- **Caching**: Content is typically static, cache aggressively
- **Load balancing**: Use DNS or client-side redundancy
- **Monitoring**: Log all requests for debugging
- **Compatibility**: Support both Gopher and Gopher+ clients

---

## Examples and Use Cases

### Basic Directory Listing

**Request:**
```
<empty_line>
```

**Response:**
```
0About Gopher	about	gopher.example.com	70
1Documents	docs/	gopher.example.com	70
7Search	search	search.example.com	70
.
```

### Search Example

**Request:**
```
search	python programming
```

**Response:**
```
0Python Tutorial	tutorials/python.txt	docs.example.com	70
0Python Reference	ref/python.txt	docs.example.com	70
.
```

### Gopher+ Attribute Request

**Request:**
```
document.txt		!+ABSTRACT
```

**Response:**
```
+ABSTRACT: This document contains programming examples
.
```

---

## Complete BNF Grammar

### Basic Elements

```bnf
CR-LF     ::= ASCII_CR ASCII_LF
Tab       ::= ASCII_TAB
NUL       ::= ASCII_NUL
UNASCII   ::= ASCII - [Tab CR-LF NUL]
Lastline  ::= '.' CR-LF
TextBlock ::= Block_of_ASCII_text_not_containing_Lastline_pattern
Type      ::= UNASCII
RedType   ::= '+'
User_Name ::= {UNASCII}
Selector  ::= {UNASCII}
Host      ::= {{UNASCII - ['.']} '.'} {UNASCII - ['.']}
Digit     ::= '0' | '1' | '2' | '3' | '4' | '5' | '6' | '7' | '8' | '9'
DigitSeq  ::= Digit {Digit}
Port      ::= DigitSeq
```

### Directory Entities

```bnf
DirEntity ::= Type User_Name Tab Selector Tab Host Tab Port CR-LF
              {RedType User_Name Tab Selector Tab Host Tab Port CR-LF}
Menu      ::= {DirEntity} Lastline
```

### Text Files

```bnf
TextFile  ::= {TextBlock} Lastline
```

### Search

```bnf
Word      ::= {UNASCII - ' '}
BoolOp    ::= 'and' | 'or' | 'not' | SPACE
SearchStr ::= Word {{SPACE BoolOp} SPACE Word}
```

---

## Implementation Checklist

### Client Implementation

- [ ] TCP connection handling
- [ ] Selector string formatting
- [ ] Response parsing (menu vs text vs binary)
- [ ] Item type recognition and handling
- [ ] Search functionality
- [ ] Error handling
- [ ] Gopher+ support (optional)

### Server Implementation

- [ ] TCP server on port 70
- [ ] Selector string parsing
- [ ] Menu generation
- [ ] File serving
- [ ] Search functionality (if applicable)
- [ ] Proper response termination
- [ ] Error responses
- [ ] Security considerations

---

*This specification provides complete technical details for implementing Gopher protocol clients and servers. It combines information from RFC 1436 and RFC 4266 into a single, LLM-optimized reference document.*
