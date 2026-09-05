"""Shared TTL + LRU cache behaviour for the protocol clients.

The Gopher and Gemini clients previously carried a character-for-character
identical cache implementation (only the entry class differed), so any fix had
to be applied twice. This mixin holds the one implementation; the shared
:class:`~gopher_mcp.client_base.FetchClientBase` mixes it in and supplies the
required attributes, and each client sets ``_cache_entry_cls`` to its concrete
:class:`~gopher_mcp.models._BaseCacheEntry` subclass.
"""

import time
from typing import TYPE_CHECKING, Generic, TypeVar

if TYPE_CHECKING:
    from collections import OrderedDict

    from .models import _BaseCacheEntry

V = TypeVar("V")

#: What a per-window cache key appends to the key for the whole resource.
#: A rendered window is stored under ``f"{base}{OFFSET_KEY_PREFIX}{offset}"``,
#: so this is both how the clients build that key and how
#: :meth:`TTLCacheMixin._evict_cached_family` finds every window cut from one
#: resource. It lives here so the two cannot drift: a separator changed at the
#: build site but not the eviction site would leave windows behind that
#: ``refresh`` is supposed to drop, and the staleness would be silent. NUL
#: cannot appear in a URL, so a window key can never collide with the key
#: another resource formats to.
OFFSET_KEY_PREFIX = "\x00offset="


class TTLCacheMixin(Generic[V]):
    """LRU + TTL cache get/put over ``self._cache``.

    Hosting classes must provide ``_cache`` (an ``OrderedDict``), the
    ``cache_enabled`` / ``max_cache_entries`` / ``cache_ttl_seconds`` settings,
    and ``_cache_entry_cls`` (the entry model to construct). Subclasses inherit
    these annotations rather than re-declaring ``_cache`` (``OrderedDict`` is
    invariant in its value type, so a narrower re-declaration would not be
    assignment-compatible).
    """

    _cache: "OrderedDict[str, _BaseCacheEntry[V]]"
    cache_enabled: bool
    max_cache_entries: int
    cache_ttl_seconds: int
    _cache_entry_cls: "type[_BaseCacheEntry[V]]"

    def _get_cached_entry(self, url: str) -> "_BaseCacheEntry[V] | None":
        """Return the cached, non-expired entry for ``url`` (LRU touch).

        The entry rather than the bare value, because its ``timestamp`` is when
        the copy was actually fetched -- the provenance a caller has to attach
        to a cache hit before handing it to the model.
        """
        if not self.cache_enabled or url not in self._cache:
            return None

        entry = self._cache[url]
        if entry.is_expired(time.time()):
            del self._cache[url]
            return None

        # Move to end to mark as recently used (LRU)
        self._cache.move_to_end(url)
        return entry

    def _get_cached_response(self, url: str) -> V | None:
        """Return a cached, non-expired response for ``url`` (LRU touch).

        The stored value as-is, with no cache-provenance marking; use
        :meth:`_get_cached_entry` where the caller has to tell the model that a
        response is a replay and how old it is.
        """
        entry = self._get_cached_entry(url)
        return None if entry is None else entry.value

    def _evict_cached_family(self, base_url: str) -> int:
        """Drop the entry for ``base_url`` and every window cut from it.

        A windowed read caches each rendered window separately, under the base
        key plus :data:`OFFSET_KEY_PREFIX` and the offset. Those entries are
        siblings of one download, so anything that invalidates the resource has
        to reach all of them: dropping only the key the caller happened to ask
        for leaves the rest of the walk serving pre-invalidation bytes while
        reporting ``cached: true``, which reads as "old but from this resource"
        rather than "from the version you just replaced".

        Returns the number of entries dropped, which is what the tests assert
        on -- a fix here is invisible from the outside except as a re-fetch.
        """
        if not self._cache:
            return 0

        window_prefix = base_url + OFFSET_KEY_PREFIX
        # Materialised before deleting: mutating an OrderedDict while iterating
        # it raises RuntimeError.
        doomed = [
            key
            for key in self._cache
            if key == base_url or key.startswith(window_prefix)
        ]
        for key in doomed:
            del self._cache[key]
        return len(doomed)

    def _cache_response(
        self, url: str, response: V, fetched_at: float | None = None
    ) -> None:
        """Cache ``response`` for ``url`` with LRU eviction when full.

        ``fetched_at`` is when the CONTENT came off the wire, which is not
        always now: a continuation window is rendered from a body downloaded
        earlier, and stamping it with the current time would understate its age
        by however long the walk has been running -- so a later replay would
        report a snapshot as fresher than it is. Defaults to now, which is
        correct for anything fetched during this call.
        """
        if not self.cache_enabled:
            return

        # Evict least recently used entry if cache is full
        if (
            self._cache
            and len(self._cache) >= self.max_cache_entries
            and url not in self._cache
        ):
            self._cache.popitem(last=False)

        self._cache[url] = self._cache_entry_cls(
            key=url,
            value=response,
            timestamp=time.time() if fetched_at is None else fetched_at,
            ttl=self.cache_ttl_seconds,
        )
        self._cache.move_to_end(url)
