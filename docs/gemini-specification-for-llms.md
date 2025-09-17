# Gemini Protocol Complete Specification for LLMs

> **Comprehensive reference for Large Language Models to become experts on the Gemini protocol**
>
> Based on Gemini Network Protocol Specification v0.24.1 and Gemini Hypertext Format Specification v0.24.1

## Table of Contents

1. [Protocol Overview](#protocol-overview)
2. [Core Protocol Mechanics](#core-protocol-mechanics)
3. [URI Scheme Specification](#uri-scheme-specification)
4. [Status Codes and Response Types](#status-codes-and-response-types)
5. [MIME Types and Content Handling](#mime-types-and-content-handling)
6. [Gemtext Format Specification](#gemtext-format-specification)
7. [TLS and Security Requirements](#tls-and-security-requirements)
8. [Client and Server Behavior](#client-and-server-behavior)
9. [Examples and Use Cases](#examples-and-use-cases)
10. [Technical Implementation Details](#technical-implementation-details)
11. [Security and Privacy Considerations](#security-and-privacy-considerations)
12. [Complete Formal Grammar](#complete-formal-grammar)

---

## Protocol Overview

### What is Gemini?

The Gemini protocol is a **lightweight internet communication protocol** for accessing remote documents, designed as an incremental improvement over Gopher rather than a stripped-down HTTP. It emphasizes **simplicity, privacy, and security** while providing modern hypertext capabilities.

### Key Characteristics

- **Simple**: Easy to implement (few hundred lines of code, 1-2 days effort)
- **Secure**: Mandatory TLS encryption for all connections
- **Private**: Trust-on-first-use (TOFU) certificate model, no tracking
- **Fast**: Lightweight protocol with minimal overhead
- **Hypertext**: Native support for linking via gemtext format
- **Stateless**: No persistent connections or complex state management

### Basic Model

```
Client connects via TLS → Sends URL + CRLF → Server responds with status + meta + content → Connection closes
```

**Core Principle**: Client sends a single URL terminated by CRLF. Server responds with a status code, optional metadata, and optional content, then closes the connection.

### Design Philosophy

- **Simplicity over extensibility**: Deliberately not easily extensible to maintain simplicity
- **Privacy by default**: Mandatory encryption, self-signed certificates accepted
- **Alternative, not replacement**: Coexists with HTTP and Gopher, serves different use cases
- **User agency**: Clients control presentation, authors control content only

---

## Core Protocol Mechanics

### Connection Process

1. **Client** opens TCP connection to server on port 1965
2. **TLS handshake** establishes encrypted connection (TLS 1.2+ required)
3. **Client** sends absolute URI + CRLF (max 1024 bytes)
4. **Server** sends response header + optional content
5. **Server** closes connection using TLS close_notify

### Request Format

```
<absolute-URI><CRLF>
```

**Requirements:**
- URI MUST NOT exceed 1024 bytes
- MUST be absolute URI (no relative URIs)
- MUST NOT include userinfo portion
- MUST NOT include fragment
- Empty path and "/" are equivalent

### Response Format

```
<status><space><meta><CRLF>[<body>]
```

**Components:**
- **status**: Two-digit code (10-69)
- **meta**: Additional information (depends on status)
- **body**: Optional content (depends on status and MIME type)

### TLS Requirements

- **Minimum version**: TLS 1.2 (TLS 1.3 recommended)
- **SNI required**: Clients MUST include hostname in SNI
- **Close notification**: Servers MUST use TLS close_notify
- **Certificate validation**: TOFU strongly recommended

---

## URI Scheme Specification

### Basic Syntax

```
gemini://<host>[:<port>][/<path>][?<query>]
```

### Components

- **scheme**: Always "gemini"
- **host**: Hostname or IP address (hostname preferred)
- **port**: TCP port number (default: 1965, omit ":1965" in URLs)
- **path**: Resource path (empty path = "/")
- **query**: Optional query string for user input

### Default Behaviors

- **Missing port**: Defaults to 1965
- **Empty path**: Equivalent to "/"
- **IP addresses**: SHOULD NOT be used (hostnames preferred)

### URL Encoding

- **Standard encoding**: Per RFC 3986
- **Spaces in queries**: MUST be encoded as %20
- **Line breaks in input**: SHOULD be encoded as %0A

---

## Status Codes and Response Types

### Status Code Groups

| Range | Category | Description |
|-------|----------|-------------|
| 10-19 | Input expected | Server needs user input |
| 20-29 | Success | Request successful |
| 30-39 | Redirection | Content moved |
| 40-49 | Temporary failure | Try again later |
| 50-59 | Permanent failure | Don't retry |
| 60-69 | Client certificates | Authentication required |

### Input Expected (10-19)

**Format**: `1x <prompt>`

**Status 10 - Input**
- Server needs user input
- Client MUST prompt user with provided text
- Resubmit request with input as query string

**Status 11 - Sensitive Input**
- Same as 10 but for passwords/sensitive data
- Client SHOULD NOT echo input to screen

### Success (20-29)

**Format**: `2x <mimetype>`

**Status 20 - Success**
- Request successful
- Meta field contains MIME type
- Body contains requested content

### Redirection (30-39)

**Format**: `3x <new-URI>`

**Status 30 - Temporary Redirect**
- Content temporarily moved
- Continue using original URI for future requests

**Status 31 - Permanent Redirect**
- Content permanently moved
- Update bookmarks to new URI

### Temporary Failure (40-49)

**Format**: `4x [<error-message>]`

**Status 40** - Temporary failure
**Status 41** - Server unavailable
**Status 42** - CGI error
**Status 43** - Proxy error
**Status 44** - Slow down (rate limiting)

### Permanent Failure (50-59)

**Format**: `5x [<error-message>]`

**Status 50** - Permanent failure
**Status 51** - Not found
**Status 52** - Gone
**Status 53** - Proxy request refused
**Status 59** - Bad request

### Client Certificates (60-69)

**Format**: `6x [<certificate-info>]`

**Status 60** - Certificate required
**Status 61** - Certificate not authorized
**Status 62** - Certificate not valid

---

## MIME Types and Content Handling

### Required Support

**Clients MUST support:**
- `text/gemini; charset=utf-8` (native hypertext format)
- `text/plain; charset=utf-8` (plain text)
- `text/plain; charset=us-ascii` (ASCII text)

### Content Handling

- **Text types**: Line breaks may be CRLF or LF alone
- **Binary types**: Raw binary data, connection close indicates end
- **Character encoding**: UTF-8 default for text types
- **Compression**: Not supported
- **Chunking**: Not supported

### MIME Parameters

**For text/gemini:**
- `charset`: Character encoding (default: UTF-8)
- `lang`: Language tag per BCP47 (optional)

**Examples:**
```
text/gemini
text/gemini; charset=utf-8
text/gemini; lang=en
text/gemini; lang="en,fr"
text/plain; charset=utf-8
image/jpeg
application/pdf
```

---

## Gemtext Format Specification

### Overview

Gemtext is the native hypertext format for Gemini, designed for simplicity and accessibility. It's line-oriented with six distinct line types.

### Line Types

1. **Text lines** (default)
2. **Link lines** (`=>`)
3. **Heading lines** (`#`, `##`, `###`)
4. **List items** (`* `)
5. **Quote lines** (`>`)
6. **Preformat toggle** (` ``` `)

### Core Line Types (MUST Support)

**Text Lines**
- Default line type (no special prefix)
- Rendered as flowing text with wrapping
- Empty lines create vertical space

**Link Lines**
```
=>[<whitespace>]<URL>[<whitespace><link-text>]
```
Examples:
```
=> gemini://example.org/
=> gemini://example.org/ Example Site
=> /local/path Local Resource
=> mailto:user@example.org Email Link
```

**Preformat Toggle Lines**
```
```[<alt-text>]
```
- Toggles between normal and preformatted mode
- Alt text optional (for accessibility/syntax highlighting)
- Content between toggles rendered in monospace

### Optional Line Types (MAY Support)

**Heading Lines**
```
# Heading Level 1
## Heading Level 2
### Heading Level 3
```

**List Items**
```
* First item
* Second item
* Third item
```

**Quote Lines**
```
> This is a quote
> from another source
```

### Parser State

- **Normal mode**: Default state, recognizes all line types
- **Preformatted mode**: Only recognizes preformat toggles and text
- Parser MUST start in normal mode
- State toggles on preformat lines only

---

## TLS and Security Requirements

### TLS Version Requirements

- **Minimum**: TLS 1.2
- **Recommended**: TLS 1.3
- **Legacy versions**: TLS 1.1 and below MUST NOT be used

### Certificate Validation

**Trust on First Use (TOFU) - Strongly Recommended:**
1. Accept any certificate on first connection
2. Store certificate fingerprint and expiry
3. Verify fingerprint matches on subsequent connections
4. Warn user if fingerprint changes before expiry

**Alternative approaches:**
- Traditional CA validation
- DANE (DNS-Based Authentication of Named Entities)
- Manual certificate pinning

### Client Certificates

**Usage scenarios:**
- Access control to protected resources
- Maintaining server-side state
- User authentication

**Scope limitations:**
- Limited to specific host, port, and path
- MUST NOT be reused across different hosts
- User MUST be involved in certificate generation

### Connection Security

- **SNI required**: Clients MUST include hostname
- **Close notification**: Servers MUST use TLS close_notify
- **Certificate transparency**: TLS 1.2 sends certificates in clear
- **Perfect forward secrecy**: Recommended cipher suites

---

## Client and Server Behavior

### Client Requirements

**MUST:**
- Support TLS 1.2+
- Include SNI in TLS handshake
- Limit URI length to 1024 bytes
- Handle all defined status codes appropriately
- Support text/gemini and text/plain MIME types
- Limit redirections to 5 maximum

**SHOULD:**
- Implement TOFU certificate validation
- Warn users about TLS 1.2 certificate exposure
- Display error messages to users
- Support client certificate generation

**MAY:**
- Support additional MIME types
- Implement proxy support
- Provide certificate management UI

### Server Requirements

**MUST:**
- Support TLS 1.2+
- Use TLS close_notify to close connections
- Reject URIs exceeding 1024 bytes
- Reject requests with userinfo or fragments
- Send only defined status codes
- Handle both empty path and "/" equivalently

**SHOULD:**
- Support client certificates for access control
- Provide meaningful error messages
- Implement rate limiting (status 44)
- Log security events

**MAY:**
- Support dynamic content generation
- Implement proxy functionality
- Provide server-side state management

### Connection Handling

- **One request per connection**: No connection reuse
- **Timeout handling**: Implement reasonable timeouts
- **Error recovery**: Handle connection failures gracefully
- **Resource limits**: Prevent resource exhaustion attacks

---

## Examples and Use Cases

### Basic Content Request

**Client Request:**
```
gemini://example.org/document.gmi
```

**Server Response:**
```
20 text/gemini
# Welcome to Example.org

This is a sample gemtext document.

=> /about About this site
=> gemini://other.example/ External link
```

### User Input Example

**Initial Request:**
```
gemini://example.org/search
```

**Server Response:**
```
10 Enter search terms
```

**Follow-up Request:**
```
gemini://example.org/search?gemini%20protocol
```

**Server Response:**
```
20 text/gemini
# Search Results

=> /doc1.gmi Introduction to Gemini
=> /doc2.gmi Gemini vs HTTP
```

### Client Certificate Example

**Initial Request:**
```
gemini://example.org/private/
```

**Server Response:**
```
60 Certificate required for access
```

**Subsequent Request (with certificate):**
```
gemini://example.org/private/
```

**Server Response:**
```
20 text/gemini
# Private Area

Welcome to the protected section.
```

### Redirection Example

**Client Request:**
```
gemini://example.org/old-path
```

**Server Response:**
```
31 /new-path
```

**Follow-up Request:**
```
gemini://example.org/new-path
```

**Server Response:**
```
20 text/gemini
# New Location

Content has moved here permanently.
```

### Error Handling Example

**Client Request:**
```
gemini://example.org/nonexistent
```

**Server Response:**
```
51 The requested resource was not found
```

### Complex Application Example

**State Management with Client Certificates:**

1. **Certificate Request:**
```
Client: gemini://example.org/app/
Server: 60 Certificate required for state management
```

2. **First Input:**
```
Client: gemini://example.org/app/ (with certificate)
Server: 10 Enter first number (0-9000)
```

3. **Store First Value:**
```
Client: gemini://example.org/app/?42 (with certificate)
Server: 10 Enter second number (0-9000)
```

4. **Calculate Result:**
```
Client: gemini://example.org/app/?1923 (with certificate)
Server: 20 text/plain
42 plus 1923 equals 1965, have a nice day!
```

---

## Technical Implementation Details

### Character Encoding

- **Protocol**: ASCII for control characters
- **Headers**: UTF-8 encoding required
- **Content**: UTF-8 default, other encodings via charset parameter
- **BOM handling**: SHOULD NOT include BOM, clients SHOULD ignore if present

### Practical Limits

- **URI length**: 1024 bytes maximum
- **Status codes**: 10-69 inclusive
- **Redirection limit**: 5 redirections maximum
- **Connection timeout**: Implementation-dependent (reasonable limits)

### Error Handling

- **Malformed requests**: Status 59 (bad request)
- **Unknown status codes**: Handle by first digit (10→1x, 20→2x, etc.)
- **Connection failures**: Graceful degradation
- **Certificate errors**: User notification required

### Performance Considerations

- **No connection reuse**: Each request requires new connection
- **TLS overhead**: Handshake cost for every request
- **Caching**: Aggressive caching recommended (content typically static)
- **Compression**: Not supported at protocol level

---

## Security and Privacy Considerations

### Security Model

**Trust on First Use (TOFU):**
- Accept any certificate on first connection
- Detect certificate changes as potential attacks
- User involvement in trust decisions
- No reliance on Certificate Authorities

**Advantages:**
- Supports self-signed certificates
- Reduces dependency on CA infrastructure
- User control over trust decisions

**Limitations:**
- Vulnerable to first-connection attacks
- Requires user education
- Certificate management complexity

### Privacy Features

**Mandatory encryption:**
- All connections encrypted via TLS
- No plaintext fallback option
- Protection against passive surveillance

**No tracking mechanisms:**
- No cookies or persistent state
- No referrer headers
- Minimal metadata exposure

**Certificate privacy:**
- TLS 1.2 exposes certificates in handshake
- TLS 1.3 provides better certificate privacy
- Client certificates only when explicitly required

### Threat Model

**Protected against:**
- Passive network surveillance
- Content modification in transit
- Server impersonation (with TOFU)

**Not protected against:**
- Active attacks on first connection
- Compromised client or server
- Traffic analysis (connection patterns)
- Malicious proxy servers

### Best Practices

**For clients:**
- Implement TOFU certificate validation
- Warn users about certificate changes
- Provide certificate management interface
- Support TLS 1.3 when available

**For servers:**
- Use strong TLS configuration
- Implement rate limiting
- Monitor for suspicious activity
- Provide clear error messages

**For users:**
- Verify certificates on first connection
- Be cautious with client certificates
- Use trusted proxy servers only
- Keep software updated

---

## Complete Formal Grammar

### Network Protocol Grammar

```bnf
; Request format
request = absolute-URI CRLF

; Response format
reply    = input / success / redirect / tempfail / permfail / auth

input    = "1" DIGIT SP prompt        CRLF
success  = "2" DIGIT SP mimetype      CRLF body
redirect = "3" DIGIT SP URI-reference CRLF
tempfail = "4" DIGIT [SP errormsg]    CRLF
permfail = "5" DIGIT [SP errormsg]    CRLF
auth     = "6" DIGIT [SP errormsg]    CRLF

prompt   = 1*(SP / VCHAR)
mimetype = type "/" subtype *(";" parameter)
errormsg = 1*(SP / VCHAR)
body     = *OCTET

VCHAR    =/ UTF8-2v / UTF8-3 / UTF8-4
UTF8-2v  = %xC2 %xA0-BF UTF8-tail ; no C1 control set
         / %xC3-DF UTF8-tail
```

### Gemtext Format Grammar

```bnf
; Gemtext document structure
gemtext-document = 1*gemtext-line
gemtext-line     = text-line / link-line / preformat-toggle
gemtext-line     =/ heading / list-item / quote-line

; Core line types
text-line        = *(WSP / VCHAR) CRLF
link-line        = "=>" *WSP URI-reference [1*WSP 1*(SP / VCHAR)] *WSP CRLF
preformat-toggle = "```" text-line

; Optional line types
heading          = ( "#" / "##" / "###" ) text-line
list-item        = "*" SP text-line
quote-line       = ">" text-line

VCHAR    =/ UTF8-2v / UTF8-3 / UTF8-4
UTF8-2v  = %xC2 %xA0-BF UTF8-tail ; no C1 control set
         / %xC3-DF UTF8-tail
```

### URI Scheme Grammar

```bnf
; Gemini URI format
gemini-URI = "gemini://" authority [path-abempty] ["?" query]

authority  = host [":" port]
host       = hostname / IPv4address / "[" IPv6address "]"
port       = 1*5DIGIT ; 0-65535, default 1965
```

---

## Implementation Checklist

### Client Implementation

**Core Requirements:**
- [ ] TCP connection to port 1965
- [ ] TLS 1.2+ support with SNI
- [ ] URI validation (max 1024 bytes)
- [ ] Request formatting (URI + CRLF)
- [ ] Response parsing (status + meta + body)
- [ ] Status code handling (all categories)
- [ ] MIME type support (text/gemini, text/plain)
- [ ] Redirection handling (max 5)
- [ ] Error display to user

**Security Features:**
- [ ] TOFU certificate validation
- [ ] Certificate fingerprint storage
- [ ] Certificate change warnings
- [ ] Client certificate support
- [ ] TLS close_notify handling

**Gemtext Support:**
- [ ] Text line rendering
- [ ] Link line parsing and display
- [ ] Preformat toggle handling
- [ ] Optional: heading, list, quote support
- [ ] Parser state management

### Server Implementation

**Core Requirements:**
- [ ] TCP server on port 1965
- [ ] TLS 1.2+ support
- [ ] Request parsing and validation
- [ ] URI length checking (1024 bytes)
- [ ] Response formatting
- [ ] Status code generation
- [ ] MIME type handling
- [ ] Connection closing with TLS close_notify

**Content Serving:**
- [ ] Static file serving
- [ ] Directory listing (optional)
- [ ] Dynamic content support (optional)
- [ ] Client certificate handling
- [ ] User input processing

**Security Features:**
- [ ] Input validation
- [ ] Rate limiting (status 44)
- [ ] Access control
- [ ] Error logging
- [ ] Certificate validation

---

*This specification provides complete technical details for implementing Gemini protocol clients and servers. It combines information from the official Gemini Network Protocol Specification v0.24.1 and Gemini Hypertext Format Specification v0.24.1 into a single, LLM-optimized reference document.*
