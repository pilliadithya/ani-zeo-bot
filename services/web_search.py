"""
WebSearchService — cached, timeout-guarded web search for live anime knowledge.

Provider registry pattern
─────────────────────────
Providers self-register at module-load time via register_provider().
WebSearchService only knows about BaseWebSearchProvider — it never imports
a concrete class directly.  Adding a new provider requires zero changes to
this file or any other core file:

    # my_provider.py
    from services.web_search import BaseWebSearchProvider, register_provider, WebSearchQuery, WebSearchResult

    class BraveProvider(BaseWebSearchProvider):
        def is_configured(self) -> bool: ...
        async def search(self, wq: WebSearchQuery) -> list[WebSearchResult]: ...

    register_provider("brave", BraveProvider)   # self-registers on import

Then set  WEB_SEARCH_PROVIDER = "brave"  in config/ai_config.py.
No other file needs changing.

Public surface
──────────────
  register_provider(name, cls)   register a provider class under a string key
  BaseWebSearchProvider          ABC — implement search() + is_configured()
  WebSearchQuery                 structured query passed to provider.search()
  WebSearchResult                one result; safe to inject into AI context
  WebSearchService               facade — caching, flag checks, error isolation
  web_search_service             module singleton used by knowledge_router.py

Feature flags (config/ai_config.py)
────────────────────────────────────
  ENABLE_WEB_SEARCH = False       master switch — off by default
  WEB_SEARCH_PROVIDER = "serpapi" key used to look up the active provider
  WEB_SEARCH_MAX_RESULTS = 3      snippets per query
  WEB_SEARCH_TIMEOUT = 8          hard cap per HTTP request (seconds)
  WEB_SEARCH_CACHE_TTL = 1800     result TTL (seconds, 30 min default)

Required secret (only when ENABLE_WEB_SEARCH = True and provider = "serpapi"):
  SERPAPI_KEY — from serpapi.com
"""
from __future__ import annotations

import hashlib
import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Type

import httpx

from config.ai_config import (
    ENABLE_WEB_SEARCH,
    WEB_SEARCH_CACHE_TTL,
    WEB_SEARCH_MAX_RESULTS,
    WEB_SEARCH_PROVIDER,
    WEB_SEARCH_TIMEOUT,
)

logger = logging.getLogger(__name__)


# ── Public data types ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class WebSearchResult:
    """
    One search result delivered to the AI context layer.

    All fields are prompt-safe — no raw API keys, internal IDs, or
    tracking parameters.  snippet is capped at ~220 chars before injection
    (enforced in ContextBuilder.to_text).
    """
    title:          str
    url:            str
    snippet:        str
    source:         str            # domain / publication, e.g. "crunchyroll.com"
    published_date: str | None     # ISO-like string when available, else None


@dataclass
class WebSearchQuery:
    """Structured query passed to BaseWebSearchProvider.search()."""
    query:       str
    max_results: int  = WEB_SEARCH_MAX_RESULTS
    news_mode:   bool = False   # True → provider should prefer recent/news results


# ── Provider interface ────────────────────────────────────────────────────────

class BaseWebSearchProvider(ABC):
    """
    Abstract interface for a web-search backend.

    To add a new provider:
      1. Subclass BaseWebSearchProvider and implement search() + is_configured().
      2. Call register_provider("yourkey", YourClass) at module level.
      3. Set WEB_SEARCH_PROVIDER = "yourkey" in config/ai_config.py.

    WebSearchService and KnowledgeRouter never import concrete provider classes —
    they only call this interface.
    """

    @abstractmethod
    async def search(self, wq: WebSearchQuery) -> list[WebSearchResult]:
        """
        Execute a search and return up to wq.max_results results.

        Contract:
          - Never raises — return [] on any error (timeout, HTTP, parse).
          - Honour wq.max_results as a hard upper bound on returned items.
          - Items must have non-empty title and snippet to be returned.
        """

    @abstractmethod
    def is_configured(self) -> bool:
        """Return True when the required credentials are present and valid."""

    @property
    def provider_name(self) -> str:
        """Human-readable name for logging.  Override to customise."""
        return type(self).__name__


# ── Provider registry ─────────────────────────────────────────────────────────
#
# Maps string keys (matching WEB_SEARCH_PROVIDER config value) to provider
# classes.  WebSearchService._resolve_provider() looks up this dict at
# startup — it never imports a concrete class directly.
#
# Populated by register_provider() calls at the bottom of this file (for
# built-in providers) and by any external provider module on import.

_PROVIDER_REGISTRY: dict[str, Type[BaseWebSearchProvider]] = {}


def register_provider(name: str, cls: Type[BaseWebSearchProvider]) -> None:
    """
    Register a web-search provider class under a string key.

    Call this at module level in the provider's own file so it self-registers
    on import.  Registering the same key twice replaces the previous entry
    (last registration wins — useful for testing overrides).

    Args:
        name:  The key that WEB_SEARCH_PROVIDER must be set to in order to
               activate this provider.  Case-sensitive, lowercase recommended.
        cls:   Concrete subclass of BaseWebSearchProvider.  Must be a class,
               not an instance — WebSearchService instantiates it on demand.

    Example:
        register_provider("brave", BraveSearchProvider)
    """
    if not (isinstance(cls, type) and issubclass(cls, BaseWebSearchProvider)):
        raise TypeError(
            f"register_provider: {cls!r} must be a subclass of BaseWebSearchProvider"
        )
    if name in _PROVIDER_REGISTRY:
        logger.debug("WebSearch | provider %r re-registered (replacing previous)", name)
    _PROVIDER_REGISTRY[name] = cls
    logger.debug("WebSearch | provider %r registered → %s", name, cls.__name__)


def list_providers() -> dict[str, str]:
    """Return {key: class_name} for every registered provider (read-only view)."""
    return {k: v.__name__ for k, v in _PROVIDER_REGISTRY.items()}


# ── In-process TTL cache ──────────────────────────────────────────────────────

class _WebSearchCache:
    """
    Lightweight TTL cache for web search results.

    Key  = SHA-256(intent_name + ":" + normalised_query).
    Entries expire lazily on the next get() call for that key.
    """

    def __init__(self, ttl: int = WEB_SEARCH_CACHE_TTL) -> None:
        self._ttl   = ttl
        self._store: dict[str, tuple[list[WebSearchResult], float]] = {}

    @staticmethod
    def make_key(intent_name: str, query: str) -> str:
        raw = f"{intent_name}:{query.lower().strip()}"
        return hashlib.sha256(raw.encode()).hexdigest()

    def get(self, key: str) -> list[WebSearchResult] | None:
        entry = self._store.get(key)
        if entry is None:
            return None
        results, expires_at = entry
        if time.monotonic() > expires_at:
            del self._store[key]
            return None
        return results

    def set(self, key: str, results: list[WebSearchResult]) -> None:
        self._store[key] = (results, time.monotonic() + self._ttl)

    def clear(self) -> None:
        self._store.clear()


# ── WebSearchService facade ───────────────────────────────────────────────────

class WebSearchService:
    """
    Facade over the active web-search provider.

    Responsibilities:
      - Check ENABLE_WEB_SEARCH flag (zero-cost early exit when disabled).
      - Resolve the active provider from the registry at startup.
      - Cache results with TTL to avoid duplicate API calls.
      - Isolate callers from all provider errors — always returns list[WebSearchResult].

    The KnowledgeRouter only ever calls search() on this object.  It has
    no knowledge of which concrete provider is active.

    Usage:
        from services.web_search import web_search_service
        results = await web_search_service.search(
            "Demon Slayer season 4 release date",
            intent_name="ANIME_NEWS",
            news_mode=True,
        )
    """

    def __init__(self) -> None:
        self._cache    = _WebSearchCache()
        self._provider: BaseWebSearchProvider | None = self._resolve_provider()

    # ── Public API ─────────────────────────────────────────────────────────────

    def is_configured(self) -> bool:
        """True when the master flag is on AND the active provider has its key."""
        return (
            ENABLE_WEB_SEARCH
            and self._provider is not None
            and self._provider.is_configured()
        )

    def active_provider_name(self) -> str:
        """Return the name of the active provider, or 'none' when unavailable."""
        if self._provider is None:
            return "none"
        return self._provider.provider_name

    async def search(
        self,
        query:       str,
        intent_name: str = "UNKNOWN",
        *,
        news_mode:   bool = False,
        max_results: int  = WEB_SEARCH_MAX_RESULTS,
    ) -> list[WebSearchResult]:
        """
        Search the web for *query*.  Returns up to *max_results* results.

        Silently returns [] when:
          - ENABLE_WEB_SEARCH is False
          - No provider is registered or the provider lacks its API key
          - The provider times out or returns an error

        Args:
            query:        Search query string (may be refined before passing here).
            intent_name:  Intent enum name — used for cache keying and logging.
            news_mode:    True → provider should prefer recent/news-style results.
            max_results:  Upper bound on returned results.
        """
        if not ENABLE_WEB_SEARCH:
            return []

        if self._provider is None or not self._provider.is_configured():
            return []

        cache_key = _WebSearchCache.make_key(intent_name, query)
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.debug(
                "WebSearch | cache hit | provider=%s | intent=%s | %r",
                self._provider.provider_name, intent_name, query,
            )
            return cached

        wq      = WebSearchQuery(query=query, max_results=max_results, news_mode=news_mode)
        results = await self._provider.search(wq)

        if results:
            self._cache.set(cache_key, results)
            logger.info(
                "WebSearch | %d results | provider=%s | intent=%s | %r",
                len(results), self._provider.provider_name, intent_name, query,
            )
        else:
            logger.debug(
                "WebSearch | no results | provider=%s | intent=%s | %r",
                self._provider.provider_name, intent_name, query,
            )

        return results

    # ── Internal ───────────────────────────────────────────────────────────────

    @staticmethod
    def _resolve_provider() -> BaseWebSearchProvider | None:
        """
        Instantiate the provider named by WEB_SEARCH_PROVIDER from the registry.

        Never references a concrete class directly — purely a registry lookup.
        Returns None when the key is not registered (logs a warning).
        """
        cls = _PROVIDER_REGISTRY.get(WEB_SEARCH_PROVIDER)
        if cls is None:
            known = list(_PROVIDER_REGISTRY.keys()) or ["(none registered yet)"]
            logger.warning(
                "WebSearch | provider %r not in registry. Known providers: %s. "
                "Web search will be disabled until a matching provider is registered.",
                WEB_SEARCH_PROVIDER, ", ".join(known),
            )
            return None

        try:
            instance = cls()
            logger.debug(
                "WebSearch | active provider: %r → %s (configured=%s)",
                WEB_SEARCH_PROVIDER, cls.__name__, instance.is_configured(),
            )
            return instance
        except Exception as exc:
            logger.error(
                "WebSearch | failed to instantiate provider %r: %s",
                WEB_SEARCH_PROVIDER, exc,
            )
            return None


# ── Built-in providers ────────────────────────────────────────────────────────
#
# Each provider is defined below and self-registers at the end of its class
# block.  To add a new built-in provider, copy the SerpAPIProvider pattern:
#   1. Define the class (subclass BaseWebSearchProvider).
#   2. Call register_provider("yourkey", YourClass) directly below it.
#
# External providers (in separate files) do the same in their own module —
# they just need to be imported before WebSearchService is instantiated.


class SerpAPIProvider(BaseWebSearchProvider):
    """
    Google search results via SerpAPI (https://serpapi.com).

    Registration key: "serpapi"
    Required secret:  SERPAPI_KEY environment variable

    Endpoint:
        GET https://serpapi.com/search.json
            ?q=<query>&api_key=<key>&engine=google&num=<n>[&tbm=nws]

    news_mode=True appends &tbm=nws to prefer recent news results.
    """

    _ENDPOINT  = "https://serpapi.com/search.json"
    _PROV_NAME = "SerpAPI"

    def __init__(self) -> None:
        self._api_key: str | None = os.environ.get("SERPAPI_KEY")
        if not self._api_key:
            logger.warning(
                "SerpAPIProvider | SERPAPI_KEY not set — "
                "set ENABLE_WEB_SEARCH=True and add the secret to activate."
            )

    @property
    def provider_name(self) -> str:
        return self._PROV_NAME

    def is_configured(self) -> bool:
        return bool(self._api_key)

    async def search(self, wq: WebSearchQuery) -> list[WebSearchResult]:
        if not self._api_key:
            return []

        params: dict[str, str | int] = {
            "q":       wq.query,
            "api_key": self._api_key,
            "engine":  "google",
            "num":     wq.max_results + 2,   # fetch a few extra; filter empties below
        }
        if wq.news_mode:
            params["tbm"] = "nws"

        try:
            async with httpx.AsyncClient(timeout=WEB_SEARCH_TIMEOUT) as client:
                resp = await client.get(self._ENDPOINT, params=params)
                resp.raise_for_status()
                data = resp.json()
        except httpx.TimeoutException:
            logger.warning(
                "SerpAPIProvider | timeout (>%ds) for %r", WEB_SEARCH_TIMEOUT, wq.query
            )
            return []
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "SerpAPIProvider | HTTP %d for %r", exc.response.status_code, wq.query
            )
            return []
        except Exception as exc:
            logger.warning("SerpAPIProvider | unexpected error: %s", exc)
            return []

        return self._parse(data, wq.max_results)

    @staticmethod
    def _parse(data: dict, limit: int) -> list[WebSearchResult]:
        results: list[WebSearchResult] = []

        # News results (present when tbm=nws)
        for item in data.get("news_results", [])[:limit]:
            results.append(WebSearchResult(
                title          = item.get("title", ""),
                url            = item.get("link", ""),
                snippet        = item.get("snippet", ""),
                source         = item.get("source", ""),
                published_date = item.get("date"),
            ))

        # Organic results (standard search)
        remaining = limit - len(results)
        for item in data.get("organic_results", [])[:remaining]:
            results.append(WebSearchResult(
                title          = item.get("title", ""),
                url            = item.get("link", ""),
                snippet        = item.get("snippet", ""),
                source         = _extract_domain(item.get("link", "")),
                published_date = item.get("date"),
            ))

        # Drop entries missing both title and snippet
        return [r for r in results if r.title and r.snippet][:limit]


# SerpAPI self-registers — no other file references SerpAPIProvider by name
register_provider("serpapi", SerpAPIProvider)


# ── Utility ───────────────────────────────────────────────────────────────────

def _extract_domain(url: str) -> str:
    """Extract bare domain from a URL for use as a source label."""
    try:
        from urllib.parse import urlparse
        return urlparse(url).netloc.lstrip("www.") or url
    except Exception:
        return url


# ── Module-level singleton ────────────────────────────────────────────────────
# Instantiated after all built-in providers are registered above.
# KnowledgeRouter imports this object and calls .search() on it — never
# imports SerpAPIProvider or any other concrete class.
web_search_service = WebSearchService()
