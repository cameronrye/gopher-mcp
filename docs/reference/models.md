# Data Models

Authoritative, auto-generated reference for the Pydantic models that define tool
inputs and outputs. These are generated directly from
[`gopher_mcp.models`](https://github.com/cameronrye/gopher-mcp/blob/main/src/gopher_mcp/models.py),
so they never drift from the code. For usage examples and error-handling
recipes, see the [API Reference](../api-reference.md).

## Request Models

::: gopher_mcp.models.GopherFetchRequest

::: gopher_mcp.models.GeminiFetchRequest

## Gopher Result Models

::: gopher_mcp.models.GopherMenuItem

::: gopher_mcp.models.MenuResult

::: gopher_mcp.models.TextResult

::: gopher_mcp.models.BinaryResult

::: gopher_mcp.models.ErrorResult

## Gemini Result Models

::: gopher_mcp.models.GeminiSuccessResult

::: gopher_mcp.models.GeminiGemtextResult

::: gopher_mcp.models.GeminiInputResult

::: gopher_mcp.models.GeminiRedirectResult

::: gopher_mcp.models.GeminiErrorResult

::: gopher_mcp.models.GeminiCertificateResult

## Gemtext Document Models

::: gopher_mcp.models.GemtextDocument

::: gopher_mcp.models.GemtextLine

::: gopher_mcp.models.GemtextLink

::: gopher_mcp.models.GemtextHeading

::: gopher_mcp.models.GemtextList

::: gopher_mcp.models.GemtextQuote

::: gopher_mcp.models.GemtextPreformat

::: gopher_mcp.models.GemtextLineType

## MIME and Protocol Types

::: gopher_mcp.models.GeminiMimeType

::: gopher_mcp.models.GeminiStatusCode

::: gopher_mcp.models.GeminiResponse

## URL Models

::: gopher_mcp.models.GopherURL

::: gopher_mcp.models.GeminiURL

## Caching and Security Models

::: gopher_mcp.models.CacheEntry

::: gopher_mcp.models.GeminiCacheEntry

::: gopher_mcp.models.GeminiCertificateInfo

::: gopher_mcp.models.TOFUEntry
