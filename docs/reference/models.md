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

::: gopher_mcp.models.GeminiBinaryResult

::: gopher_mcp.models.GeminiGemtextResult

::: gopher_mcp.models.GeminiInputResult

::: gopher_mcp.models.GeminiRedirectResult

::: gopher_mcp.models.GeminiCertificateResult

!!! note "`GeminiErrorResult` is `ErrorResult`"
    There is no separate Gemini error model: `GeminiErrorResult` is an alias for the `ErrorResult` documented under [Gopher Result Models](#gopher-result-models) above, which both protocols return. Its `error` field is `dict[str, Any]` precisely so a Gemini failure can carry the numeric `status` and the boolean `temporary` beside the `code` and `message`; a Gopher failure omits those keys.

## Trust-Store Tool Results

Returned by the `gemini_trust_list` and `gemini_trust_update` tools. See the
[API Reference](../api-reference.md#gemini_trust_list) for the recovery
procedure they support.

::: gopher_mcp.models.TOFUTrustListResult

::: gopher_mcp.models.TOFUTrustUpdateResult

## Client-Certificate Tool Results

Returned by the `gemini_client_cert_list` and `gemini_client_cert_update` tools.
See the [API Reference](../api-reference.md#gemini_client_cert_list) for the
status-60 procedure they support. None of these models carries key material or
the certificate store's filesystem path. `GeminiClientCertificateEntry` is a
projection of the stored `GeminiCertificateInfo` (under
[Caching and Security Models](#caching-and-security-models)): it adds the scope
as a ready-to-use URL and the expiry resolved against the current time, and
leaves out the certificate's subject and issuer, which this server generated and
under which it stores the key pair.

::: gopher_mcp.models.GeminiClientCertificateEntry

::: gopher_mcp.models.GeminiClientCertListResult

::: gopher_mcp.models.GeminiClientCertUpdateResult

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
