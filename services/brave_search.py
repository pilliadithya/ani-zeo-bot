"""
BraveSearchProvider — web and news search via Brave Search API.

This module self-registers under the key "brave" on import.
No other file needs to reference BraveSearchProvider by name.

Activation:
    1. Set  WEB_SEARCH_PROVIDER = "brave"  in config/ai_config.py
    2. Set  ENABLE_WEB_SEARCH   = True     in config/ai_config.py
    3. Add  BRAVE_API_KEY                  as a Replit secret

API reference:
    https://api.search.brave.com/app/documentation/web-search/get-started

Endpoints
─────────
  Web  : GET https://api.search.brave.com/res/v1/web/search
             ?q=<query>&count=<n>
  News : GET https://api.search.brave.com/res/v1/news/search
             ?q=<query>&count=<n>
  Auth header: X-Subscription-Token: <BRAVE_API_KEY>

Response shapes
───────────────
  Web  → data["web"]["results"][i]  { title, url, description, page_age, profile.name }
  News → data["results"][i]         { title, url, description, age, meta_url.hostname }
"""
from __future__ import annotations

import logging
import os
from urllib.parse import urlparse

import httpx

from config.ai_config import WEB_SEARCH_TIMEOUT
from services.web_search import (
    BaseWebSearchProvider,
    WebSearchQuery,
    WebSearchResult,
    register_provider,
)

logger = logging.getLogger(__name__)


class BraveSearchProvider(BaseWebSearchProvider):
    """
    Web and news search via Brave Search API.

    Registration key : "brave"
    Required secret  : BRAVE_API_KEY  (environment variable / Replit secret)

    When news_mode=True the news endpoint is used, which returns results
    sorted by recency — ideal for ANIME_NEWS and TRENDING intents.
    """

    _WEB_ENDPOINT  = "https://api.search.brave.com/res/v1/web/search"
    _NEWS_ENDPOINT = "https://api.search.brave.com/res/v1/news/search"
    _PROV_NAME     = "BraveSearch"

    def __init__(self) -> None:
        self._api_key: str | None = os.environ.get("BRAVE_API_KEY")
        if self._api_key:
            logger.debug("BraveSearchProvider | initialised — key present")
        else:
            logger.warning(
                "BraveSearchProvider | BRAVE_API_KEY not set. "
                "Add it as a Replit secret and set ENABLE_WEB_SEARCH=True to activate."
            )

    # ── Interface ──────────────────────────────────────────────────────────────

    @property
    def provider_name(self) -> str:
        return self._PROV_NAME

    def is_configured(self) -> bool:
        return bool(self._api_key)

    async def search(self, wq: WebSearchQuery) -> list[WebSearchResult]:
        """
        Execute a Brave web or news search.

        Logs its own entry and result at INFO level so the routing trace is
        visible without enabling DEBUG.  Always returns [] on any error.
        """
        logger.info(
            "BraveSearchProvider.search() called | mode=%s | query=%r | max=%d | configured=%s",
            "news" if wq.news_mode else "web",
            wq.query,
            wq.max_results,
            self.is_configured(),
        )

        if not self._api_key:
            logger.warning(
                "BraveSearchProvider.search() | BRAVE_API_KEY missing — returning []"
            )
            return []

        endpoint = self._NEWS_ENDPOINT if wq.news_mode else self._WEB_ENDPOINT
        params   = {"q": wq.query, "count": wq.max_results + 2}  # fetch extra; filter below
        headers  = {
            "Accept":               "application/json",
            "Accept-Encoding":      "gzip",
            "X-Subscription-Token": self._api_key,
        }

        try:
            async with httpx.AsyncClient(timeout=WEB_SEARCH_TIMEOUT) as client:
                resp = await client.get(endpoint, params=params, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except httpx.TimeoutException:
            logger.warning(
                "BraveSearchProvider | timeout (>%ds) | query=%r", WEB_SEARCH_TIMEOUT, wq.query
            )
            return []
        except httpx.HTTPStatusError as exc:
            logger.warning(
                "BraveSearchProvider | HTTP %d | query=%r",
                exc.response.status_code, wq.query,
            )
            return []
        except Exception as exc:
            logger.warning("BraveSearchProvider | unexpected error: %s", exc)
            return []

        results = self._parse(data, wq.max_results, news_mode=wq.news_mode)
        logger.info(
            "BraveSearchProvider.search() | %d results returned | query=%r",
            len(results), wq.query,
        )
        return results

    # ── Parsing ────────────────────────────────────────────────────────────────

    @staticmethod
    def _parse(data: dict, limit: int, *, news_mode: bool) -> list[WebSearchResult]:
        results: list[WebSearchResult] = []

        if news_mode:
            # News endpoint returns a flat "results" list
            for item in data.get("results", [])[:limit]:
                results.append(WebSearchResult(
                    title          = item.get("title", ""),
                    url            = item.get("url", ""),
                    snippet        = item.get("description", ""),
                    source         = item.get("meta_url", {}).get("hostname", ""),
                    published_date = item.get("age"),
                ))
        else:
            # Web endpoint nests results under "web" → "results"
            for item in data.get("web", {}).get("results", [])[:limit]:
                profile_name = item.get("profile", {}).get("name", "")
                results.append(WebSearchResult(
                    title          = item.get("title", ""),
                    url            = item.get("url", ""),
                    snippet        = item.get("description", ""),
                    source         = profile_name or _bare_domain(item.get("url", "")),
                    published_date = item.get("page_age"),
                ))

        # Drop entries that have neither title nor snippet
        return [r for r in results if r.title and r.snippet][:limit]


def _bare_domain(url: str) -> str:
    """Extract bare domain from a URL, e.g. 'https://crunchyroll.com/…' → 'crunchyroll.com'."""
    try:
        return urlparse(url).netloc.lstrip("www.") or url
    except Exception:
        return url


# ── Self-registration ─────────────────────────────────────────────────────────
# Executed once at import time.  KnowledgeRouter and WebSearchService only
# ever call register_provider() — they never reference BraveSearchProvider directly.
register_provider("brave", BraveSearchProvider)
logger.debug("brave_search | BraveSearchProvider registered under 'brave'")
