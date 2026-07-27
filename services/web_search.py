"""
WebSearchService — cached, timeout-guarded web search for live anime knowledge.

Architecture mirrors services/anime_search.py:
  BaseWebSearchProvider  abstract interface — swap providers without touching callers
  SerpAPIProvider        concrete implementation (reads SERPAPI_KEY from env)
  _WebSearchCache        in-process TTL cache, keyed by SHA-256(intent + query)
  WebSearchService       public facade — never raises, always returns list[WebSearchResult]

Feature flags (config/ai_config.py):
  ENABLE_WEB_SEARCH = False   master switch — off by default
  WEB_SEARCH_PROVIDER         "serpapi" (only provider in Sprint A)
  WEB_SEARCH_MAX_RESULTS      snippets per query (default 3)
  WEB_SEARCH_TIMEOUT          hard cap per HTTP request (default 8 s)
  WEB_SEARCH_CACHE_TTL        result lifetime (default 1 800 s / 30 min)

Required secret (only when ENABLE_WEB_SEARCH = True):
  SERPAPI_KEY   — from serpapi.com

Usage:
    from services.web_search import web_search_service
    results = await web_search_service.search("AoT 2026 release date", Intent.ANIME_NEWS)
    for r in results:
        print(r.title, r.snippet)
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

import httpx

from config.ai_config import (
    ENABLE_WEB_SEARCH,
    WEB_SEARCH_CACHE_TTL,
    WEB_SEARCH_MAX_RESULTS,
    WEB_SEARCH_TIMEOUT,
)

logger = logging.getLogger(__name__)

# ── Public data types ─────────────────────────────────────────────────────────


@dataclass(frozen=True)
class WebSearchResult:
    """
    One search result delivered to the AI context layer.

    All fields are safe to inject into a prompt — no raw API keys,
    internal IDs, or tracking parameters.  `snippet` is limited to
    ~220 characters before injection (see ContextBuilder.to_text).
    """
    title:          str
    url:            str
    snippet:        str
    source:         str         # domain / publication name, e.g. "crunchyroll.com"
    published_date: str | None  # ISO-like string if available, else None


@dataclass
class WebSearchQuery:
    """Structured query fed to a provider."""
    query:       str
    max_results: int  = WEB_SEARCH_MAX_RESULTS
    news_mode:   bool = False   # True → provider should prefer recent/news results


# ── Cache ─────────────────────────────────────────────────────────────────────


class _WebSearchCache:
    """
    Lightweight in-process TTL cache for web search results.

    Key = SHA-256(intent_name + ":" + normalised_query).
    Entries expire lazily on the next get() call.
    """

    def __init__(self, ttl: int = WEB_SEARCH_CACHE_TTL) -> None:
        self._ttl   = ttl
        self._store: dict[str, tuple[list[WebSearchResult], float]] = {}

    # ------------------------------------------------------------------
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


# ── Provider interface ────────────────────────────────────────────────────────


class BaseWebSearchProvider(ABC):
    """
    Abstract interface for a web-search backend.

    Subclass this to add a new provider (e.g. Google Custom Search, Serper,
    Brave Search).  Register the new provider in WebSearchService._make_provider().
    The routing core never needs to change.
    """

    @abstractmethod
    async def search(self, wq: WebSearchQuery) -> list[WebSearchResult]:
        """
        Execute a search and return up to wq.max_results results.

        Must never raise — return [] on any failure.
        Must honour wq.max_results as an upper bound.
        """

    @abstractmethod
    def is_configured(self) -> bool:
        """Return True when the required API key / credentials are present."""


# ── SerpAPI provider ──────────────────────────────────────────────────────────


class SerpAPIProvider(BaseWebSearchProvider):
    """
    Google search via SerpAPI (https://serpapi.com).

    Reads SERPAPI_KEY from the environment.
    Falls back to empty results when the key is absent.

    Endpoint used:
      GET https://serpapi.com/search.json
          ?q=<query>&api_key=<key>&engine=google&num=<n>[&tbm=nws]
    """

    _ENDPOINT = "https://serpapi.com/search.json"

    def __init__(self) -> None:
        self._api_key: str | None = os.environ.get("SERPAPI_KEY")
        if not self._api_key:
            logger.warning(
                "SerpAPIProvider | SERPAPI_KEY not set — web search disabled."
            )

    # ------------------------------------------------------------------
    def is_configured(self) -> bool:
        return bool(self._api_key)

    async def search(self, wq: WebSearchQuery) -> list[WebSearchResult]:
        if not self._api_key:
            return []

        params: dict[str, str | int] = {
            "q":       wq.query,
            "api_key": self._api_key,
            "engine":  "google",
            "num":     wq.max_results + 2,  # fetch a few extra; filter below
        }
        if wq.news_mode:
            params["tbm"] = "nws"

        try:
            async with httpx.AsyncClient(timeout=WEB_SEARCH_TIMEOUT) as client:
                resp = await client.get(self._ENDPOINT, params=params)
                resp.raise_for_status()
                data = resp.json()
        except httpx.TimeoutException:
            logger.warning("SerpAPIProvider | timeout (>%ds) for %r", WEB_SEARCH_TIMEOUT, wq.query)
            return []
        except httpx.HTTPStatusError as exc:
            logger.warning("SerpAPIProvider | HTTP %d for %r", exc.response.status_code, wq.query)
            return []
        except Exception as exc:
            logger.warning("SerpAPIProvider | unexpected error: %s", exc)
            return []

        return self._parse(data, wq.max_results)

    # ------------------------------------------------------------------
    @staticmethod
    def _parse(data: dict, limit: int) -> list[WebSearchResult]:
        results: list[WebSearchResult] = []

        # News results (tbm=nws)
        for item in data.get("news_results", [])[:limit]:
            results.append(WebSearchResult(
                title          = item.get("title", ""),
                url            = item.get("link", ""),
                snippet        = item.get("snippet", ""),
                source         = item.get("source", ""),
                published_date = item.get("date"),
            ))

        # Organic results (standard search)
        for item in data.get("organic_results", [])[:limit - len(results)]:
            results.append(WebSearchResult(
                title          = item.get("title", ""),
                url            = item.get("link", ""),
                snippet        = item.get("snippet", ""),
                source         = _domain(item.get("link", "")),
                published_date = item.get("date"),
            ))

        # Filter out empty or useless entries
        return [r for r in results if r.title and r.snippet][:limit]


def _domain(url: str) -> str:
    """Extract bare domain from a URL, e.g. 'https://crunchyroll.com/...' → 'crunchyroll.com'."""
    try:
        from urllib.parse import urlparse
        return urlparse(url).netloc.lstrip("www.") or url
    except Exception:
        return url


# ── Public facade ─────────────────────────────────────────────────────────────


class WebSearchService:
    """
    Public facade for web search.

    Checks the ENABLE_WEB_SEARCH feature flag before making any network call.
    Uses an in-process TTL cache to avoid repeat API calls for the same query.
    Never raises — callers always receive list[WebSearchResult] (may be empty).

    Example:
        results = await web_search_service.search(
            "Demon Slayer season 4 release date", intent_name="ANIME_NEWS"
        )
    """

    def __init__(self) -> None:
        self._cache    = _WebSearchCache()
        self._provider = self._make_provider()

    # ------------------------------------------------------------------
    def is_configured(self) -> bool:
        """True when ENABLE_WEB_SEARCH is on AND the provider has its key."""
        return ENABLE_WEB_SEARCH and self._provider.is_configured()

    async def search(
        self,
        query: str,
        intent_name: str = "UNKNOWN",
        *,
        news_mode: bool = False,
        max_results: int = WEB_SEARCH_MAX_RESULTS,
    ) -> list[WebSearchResult]:
        """
        Search the web for *query*.  Returns up to *max_results* results.

        Args:
            query:        Raw or refined search query string.
            intent_name:  Intent enum name (for cache keying + logging).
            news_mode:    True → prefer recent/news results (tbm=nws in SerpAPI).
            max_results:  Upper bound on returned results.

        Returns:
            List of WebSearchResult objects, or [] on any failure / flag off.
        """
        # ── Feature flag ─────────────────────────────────────────────────────
        if not ENABLE_WEB_SEARCH:
            return []

        if not self._provider.is_configured():
            return []

        # ── Cache check ───────────────────────────────────────────────────────
        cache_key = _WebSearchCache.make_key(intent_name, query)
        cached = self._cache.get(cache_key)
        if cached is not None:
            logger.debug("WebSearch | cache hit | intent=%s | %r", intent_name, query)
            return cached

        # ── Live fetch ────────────────────────────────────────────────────────
        wq = WebSearchQuery(query=query, max_results=max_results, news_mode=news_mode)
        results = await self._provider.search(wq)

        if results:
            self._cache.set(cache_key, results)
            logger.info(
                "WebSearch | fetched %d results | intent=%s | %r",
                len(results), intent_name, query,
            )
        else:
            logger.debug("WebSearch | no results | intent=%s | %r", intent_name, query)

        return results

    # ------------------------------------------------------------------
    @staticmethod
    def _make_provider() -> BaseWebSearchProvider:
        """
        Instantiate the configured provider.

        Add new providers here — no other file needs to change.
        """
        from config.ai_config import WEB_SEARCH_PROVIDER
        if WEB_SEARCH_PROVIDER == "serpapi":
            return SerpAPIProvider()
        logger.warning(
            "WebSearchService | unknown provider %r — falling back to SerpAPI",
            WEB_SEARCH_PROVIDER,
        )
        return SerpAPIProvider()


# ── Module-level singleton ────────────────────────────────────────────────────
# Imported by knowledge_router.py.  Instantiated once at module load.
web_search_service = WebSearchService()
