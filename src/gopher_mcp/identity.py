"""Pure decision and wording helpers for the Gemini trust and identity tools.

These are the parts of ``gemini_trust_update`` and ``gemini_client_cert_update``
that decide *what* happens and *how it is described* -- which stored pin the
caller named, which identity covers a scope, which narrower identities keep
winning underneath a new one, and the sentences reporting each outcome. They
touch no client, no store and no event loop, so they can be read and tested on
their own; the tools in :mod:`gopher_mcp.server` keep only the I/O around them.

Splitting them out is not tidying for its own sake: the scope-covering and
fingerprint-interlock rules below decide whether an unrecoverable private key
is deleted, and that decision used to be reachable only by driving the whole
FastMCP tool.
"""

import hmac

# The certificate store's own scope rule, imported rather than reimplemented:
# a tool that decided "covers this path" even slightly differently from the
# fetch path would refuse creations the fetch path cannot satisfy, or allow one
# that silently shadows an existing identity.
from .client_certs import _path_in_scope
from .gemini_parse import format_gemini_url
from .models import GeminiCertificateInfo, TOFUEntry
from .ssrf import normalize_host
from .tofu import canonicalize_fingerprint


def _filter_pins(
    entries: list[TOFUEntry], host: str | None, port: int | None = None
) -> list[TOFUEntry]:
    """Select the pins the caller asked about, ordered by host and port.

    Host matching mirrors the trust store's own normalization (case, trailing
    dot, IPv6 brackets), so ``Example.com`` finds the entry stored under
    ``example.com`` rather than silently reporting nothing pinned.
    """
    wanted = None if host is None else normalize_host(host)
    return sorted(
        (
            entry
            for entry in entries
            if (wanted is None or normalize_host(entry.host) == wanted)
            and (port is None or entry.port == port)
        ),
        key=lambda entry: (normalize_host(entry.host), entry.port),
    )


def _filter_client_certs(
    certs: list[GeminiCertificateInfo], host: str | None
) -> list[GeminiCertificateInfo]:
    """Select the stored certificates the caller asked about, ordered by scope.

    Host matching mirrors the certificate store's own normalization (case,
    trailing dot, IPv6 brackets), so ``Example.com`` finds the identity stored
    under ``example.com`` rather than reporting none.
    """
    wanted = None if host is None else normalize_host(host)
    return sorted(
        (
            cert
            for cert in certs
            if wanted is None or normalize_host(cert.host) == wanted
        ),
        key=lambda cert: (normalize_host(cert.host), cert.port, cert.path),
    )


def _covering_certificate(
    certs: list[GeminiCertificateInfo], host: str, port: int, path: str
) -> GeminiCertificateInfo | None:
    """Return the stored REGISTRY ENTRY whose scope covers ``path``.

    The longest in-scope path wins, as in the certificate store's own lookup,
    but this reads the registry alone: an entry whose certificate and key have
    gone missing still covers the scope here, so it can be named and cleared.
    Whether a request would actually present it is the separate question
    ``GeminiClient.get_client_certificate_info_for_scope`` answers, and that is
    what a creation must consult -- an entry with no key on disk authenticates
    nothing, so refusing to create over it would leave the scope permanently
    unusable.
    """
    wanted = normalize_host(host)
    best: GeminiCertificateInfo | None = None
    for cert in certs:
        if (
            normalize_host(cert.host) == wanted
            and cert.port == port
            and _path_in_scope(path, cert.path)
            and (best is None or len(cert.path) > len(best.path))
        ):
            best = cert
    return best


def _shadowing_certificates(
    certs: list[GeminiCertificateInfo], host: str, port: int, path: str
) -> list[GeminiCertificateInfo]:
    """Return the stored identities scoped strictly below ``path``.

    Attachment picks the longest matching scope, so each of these keeps winning
    underneath its own prefix. A new, wider identity therefore does not take
    over what they cover, and a result claiming it did would be false.
    """
    wanted = normalize_host(host)
    return sorted(
        (
            cert
            for cert in certs
            if normalize_host(cert.host) == wanted
            and cert.port == port
            and cert.path != path
            and _path_in_scope(cert.path, path)
        ),
        key=lambda cert: cert.path,
    )


def _certificate_with_fingerprint(
    certs: list[GeminiCertificateInfo], canonical: str
) -> GeminiCertificateInfo | None:
    """Return the stored identity whose fingerprint the caller named, if any."""
    for cert in certs:
        if hmac.compare_digest(canonicalize_fingerprint(cert.fingerprint), canonical):
            return cert
    return None


def _created_identity_message(
    scope_url: str,
    created: GeminiCertificateInfo,
    shadowing: list[GeminiCertificateInfo],
) -> str:
    """Describe a created identity, including where it will NOT be the one sent.

    An identity stored below the new scope keeps winning underneath its own
    prefix, so an unqualified "everything below it" would be false exactly
    where it matters most: on the paths the user already has a different
    pseudonym on.
    """
    covers = (
        "It is attached automatically to every request to this capsule -- the "
        "scope is the whole of it, not one section"
        if created.path == "/"
        else "It is attached automatically to every request for that path and "
        "everything below it"
    )
    message = (
        f"Created a client identity for {scope_url} ({created.fingerprint}), "
        f"valid until {created.not_after}. {covers}, so this capsule can link "
        f"those visits to one another. Nothing else is affected: other "
        f"capsules, and other paths on this one, still see no identity."
    )
    if shadowing:
        scopes = ", ".join(
            format_gemini_url(cert.host, cert.port, cert.path) for cert in shadowing
        )
        message += (
            f" One exception: {scopes} already holds its own identity, so "
            f"requests there keep carrying that one rather than this."
        )
    return message


def _removed_identity_message(
    scope_url: str, removed_url: str, *, changed: bool, key_retained: bool
) -> str:
    """Describe a removal, claiming destruction only where it happened."""
    if not changed:
        return f"No client identity covers {scope_url}, so there is nothing to remove."
    if key_retained:
        return (
            f"Removed the client identity for {removed_url}: it is no longer "
            f"attached to any request. Its private key file could NOT be "
            f"deleted and is still in the certificate store, so do not tell "
            f"the user the key is gone -- it has to be removed by hand."
        )
    return (
        f"Removed the client identity for {removed_url} and deleted its "
        f"private key, which cannot be recovered. Requests to that scope now "
        f"carry no identity, and any account it authenticated is no longer "
        f"reachable from here."
    )


def _mismatch_next_step(certs: list[GeminiCertificateInfo], canonical: str) -> str:
    """Name the step that resolves a removal's fingerprint mismatch.

    The named fingerprint is usually one the list tool really did report, for a
    different scope -- so telling the caller to list the host and copy a
    fingerprint is telling it to repeat what it just did. Name the URL that
    fingerprint belongs to instead. The covering identity's own fingerprint
    stays unnamed either way: handing it back would let a caller that never
    read the store destroy it anyway.
    """
    named = _certificate_with_fingerprint(certs, canonical)
    if named is None:
        return (
            "No stored identity has that fingerprint. Call "
            "gemini_client_cert_list for this host and copy the `fingerprint` "
            "of the entry whose `url` is the scope you mean."
        )
    named_url = format_gemini_url(named.host, named.port, named.path)
    return (
        f"That fingerprint belongs to the identity for {named_url}: to remove "
        f"that one, call this tool again with `url` set to it."
    )
