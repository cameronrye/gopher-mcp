"""Shared TTL + LRU cache behaviour for the protocol clients.

The Gopher and Gemini clients previously carried a character-for-character
identical cache implementation (only the entry class differed), so any fix had
to be applied twice. This mixin holds the one implementation; each client mixes
it in, exposes the required attributes, and sets ``_cache_entry_cls`` to its
concrete :class:`~gopher_mcp.models._BaseCacheEntry` subclass.
"""

import time
from typing import TYPE_CHECKING, Generic, TypeVar

if TYPE_CHECKING:
    from collections import OrderedDict

    from .models import _BaseCacheEntry

V = TypeVar("V")


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

    def _get_cached_response(self, url: str) -> V | None:
        """Return a cached, non-expired response for ``url`` (LRU touch)."""
        if not self.cache_enabled or url not in self._cache:
            return None

        entry = self._cache[url]
        if entry.is_expired(time.time()):
            del self._cache[url]
            return None

        # Move to end to mark as recently used (LRU)
        self._cache.move_to_end(url)
        return entry.value

    def _cache_response(self, url: str, response: V) -> None:
        """Cache ``response`` for ``url`` with LRU eviction when full."""
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
            timestamp=time.time(),
            ttl=self.cache_ttl_seconds,
        )
        self._cache.move_to_end(url)
