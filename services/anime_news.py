"""
AnimeNewsService — multi-source anime news with TTL caching.

Fetch modes
───────────
  latest   → MAL RSS → Anime Corner RSS → AniList trending (graceful fallback)
  trending → AniList trending → MAL RSS → Anime Corner RSS (graceful fallback)

Why these sources?
  MAL RSS        — stable, reliable; 20 items with thumbnails and dates.
  Anime Corner   — editorial anime news; different editorial angle.
  AniList        — authoritative for currently-airing trending titles;
                   used as a structured fallback when RSS sources are down.

Parsing:  stdlib xml.etree.ElementTree — no extra dependencies.
HTTP:     requests in asyncio.to_thread — consistent with the rest of the codebase.
Cache:    15-minute TTL (short enough to stay fresh, long enough to avoid hammering).

What callers receive
────────────────────
  Always a NewsResult dataclass.  Callers check `result.found` before iterating
  `result.items`.  Every field on NewsItem except `title` and `source_name` is
  Optional — callers must guard before displaying.
"""
from __future__ import annotations

import asyncio
import hashlib
import html as _html
import logging
import re
import time
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

import requests

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

_MAL_RSS_URL      = "https://myanimelist.net/rss/news.xml"
_ANIME_CORNER_URL = "https://animecorner.me/feed/"
_ANILIST_URL      = "https://graphql.anilist.co"

_CACHE_TTL        = 900    # 15 minutes (news freshness window)
_REQUEST_TIMEOUT  = 15     # seconds per HTTP call
_DEFAULT_LIMIT    = 8

_RSS_HEADERS = {
    "User-Agent": "Ani-Zeo-Bot/3.0 (anime companion; +https://replit.com)",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}

# AniList GraphQL for trending currently-airing anime.
# Used both as a "trending" primary source and an RSS fallback.
_ANILIST_TRENDING_QUERY = """
query ($limit: Int) {
  Page(page: 1, perPage: $limit) {
    media(type: ANIME, sort: [TRENDING_DESC], status: RELEASING, isAdult: false) {
      title { romaji english }
      siteUrl
      coverImage { large }
      description(asHtml: false)
    }
  }
}
"""


# ── Result dataclasses ─────────────────────────────────────────────────────────

@dataclass
class NewsItem:
    """
    A single anime news article or trending entry.

    `title` and `source_name` are always present.  Every other field is
    Optional — guard against None before rendering.

    `image_url` is set only when the upstream source provides a thumbnail.
    `published` is a formatted human-readable string (e.g. "20 Jul 2026"),
    never a raw datetime object.
    """
    title:       str
    source_name: str           # "MAL", "Anime Corner", "AniList Trending"

    summary:     str | None = None   # Plain-text excerpt (HTML stripped)
    published:   str | None = None   # e.g. "20 Jul 2026"
    url:         str | None = None   # Article or AniList page link
    image_url:   str | None = None   # Thumbnail / cover image URL


@dataclass
class NewsResult:
    """
    Collection result returned by AnimeNewsService.fetch_*().

    Always returned — callers check `found` before iterating `items`.
    When `found` is False, `items` is empty and `source` is "none".
    """
    found:  bool
    mode:   str              # "latest" | "trending"
    source: str              # first source that succeeded, or "none"
    cached: bool = False

    items: list[NewsItem] = field(default_factory=list)

    @property
    def count(self) -> int:
        """Number of news items returned."""
        return len(self.items)


# ── Cache ──────────────────────────────────────────────────────────────────────

class _NewsCache:
    """
    In-process TTL cache for NewsResult objects.

    Key: mode + limit (e.g. "latest:8").  15-minute TTL per entry.
    Separate keys per limit value so a 5-item and 8-item request don't
    collide.
    """

    def __init__(self) -> None:
        # value: (result, expires_at_monotonic)
        self._store: dict[str, tuple[NewsResult, float]] = {}

    @staticmethod
    def _key(mode: str, limit: int) -> str:
        raw = f"{mode}:{limit}"
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def get(self, mode: str, limit: int) -> NewsResult | None:
        key   = self._key(mode, limit)
        entry = self._store.get(key)
        if entry is None:
            return None
        result, expires_at = entry
        if time.monotonic() > expires_at:
            del self._store[key]
            return None
        return result

    def set(self, mode: str, limit: int, result: NewsResult) -> None:
        key = self._key(mode, limit)
        self._store[key] = (result, time.monotonic() + _CACHE_TTL)

    def size(self) -> int:
        """Number of live (non-expired) cache entries."""
        now = time.monotonic()
        return sum(1 for _, exp in self._store.values() if exp > now)


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _strip_html(text: str) -> str:
    """Remove HTML tags, unescape entities, collapse whitespace."""
    if not text:
        return ""
    text = _html.unescape(text)
    text = re.sub(r"<br\s*/?>", " ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return re.sub(r"\s+", " ", text).strip()


def _fmt_date(rfc2822: str) -> str | None:
    """
    Parse an RSS pubDate string (RFC 2822) and return a readable label.

    e.g. "Mon, 20 Jul 2026 02:00:35 -0700" → "20 Jul 2026"
    Returns None on parse failure rather than raising.
    """
    try:
        dt = parsedate_to_datetime(rfc2822)
        return dt.strftime("%-d %b %Y")
    except Exception:
        return None


def _local_tag(element: ET.Element) -> str:
    """Strip the Clark-notation namespace from an element tag."""
    tag = element.tag
    return tag.split("}")[-1] if "}" in tag else tag


# ── MAL RSS client ─────────────────────────────────────────────────────────────

class _MALRSSClient:
    """
    Fetches and parses the MyAnimeList news RSS feed.

    Feed URL: https://myanimelist.net/rss/news.xml
    Fields used: title, description, link, pubDate, thumbnail (media namespace).
    """

    def _fetch_sync(self) -> list[NewsItem]:
        r = requests.get(
            _MAL_RSS_URL,
            headers=_RSS_HEADERS,
            timeout=_REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        root = ET.fromstring(r.content)

        items: list[NewsItem] = []
        for item in root.findall(".//item"):
            fields: dict[str, str] = {}
            for child in item:
                local = _local_tag(child)
                if local == "thumbnail":
                    # <media:thumbnail url="..."/> — attribute, not text
                    url_attr = child.get("url")
                    if url_attr:
                        fields["thumbnail"] = url_attr
                elif child.text:
                    fields.setdefault(local, child.text.strip())

            title = fields.get("title", "").strip()
            if not title:
                continue

            summary_raw = fields.get("description", "")
            summary = _strip_html(summary_raw) or None
            if summary and len(summary) > 300:
                summary = summary[:300].rstrip() + "…"

            items.append(NewsItem(
                title=title,
                source_name="MAL",
                summary=summary,
                published=_fmt_date(fields["pubDate"]) if "pubDate" in fields else None,
                url=fields.get("link") or fields.get("guid"),
                image_url=fields.get("thumbnail"),
            ))

        return items

    async def fetch(self, limit: int) -> list[NewsItem]:
        """
        Return up to `limit` news items from MAL RSS.
        Returns [] on any error — never raises.
        """
        try:
            items = await asyncio.to_thread(self._fetch_sync)
            logger.info("MAL RSS | fetched %d items", len(items))
            return items[:limit]
        except requests.Timeout:
            logger.warning("MAL RSS | timeout")
        except requests.HTTPError as exc:
            logger.warning("MAL RSS | HTTP error | %s", exc)
        except requests.RequestException as exc:
            logger.warning("MAL RSS | request error | %s", exc)
        except ET.ParseError as exc:
            logger.warning("MAL RSS | XML parse error | %s", exc)
        except Exception as exc:
            logger.error("MAL RSS | unexpected error | %s: %s", type(exc).__name__, exc)
        return []


# ── Anime Corner RSS client ────────────────────────────────────────────────────

class _AnimeCornerClient:
    """
    Fetches and parses the Anime Corner WordPress RSS feed.

    Feed URL: https://animecorner.me/feed/
    Fields used: title, description, link, pubDate.
    Note: description is sometimes empty for short news items.
    """

    def _fetch_sync(self) -> list[NewsItem]:
        r = requests.get(
            _ANIME_CORNER_URL,
            headers=_RSS_HEADERS,
            timeout=_REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        root = ET.fromstring(r.content)

        items: list[NewsItem] = []
        for item in root.findall(".//item"):
            fields: dict[str, str] = {}
            for child in item:
                local = _local_tag(child)
                if child.text and local not in fields:
                    fields[local] = child.text.strip()

            title = fields.get("title", "").strip()
            if not title:
                continue

            # `encoded` is the full content:encoded body; fall back to description
            raw_summary = fields.get("encoded") or fields.get("description") or ""
            summary = _strip_html(raw_summary) or None
            if summary and len(summary) > 300:
                summary = summary[:300].rstrip() + "…"

            items.append(NewsItem(
                title=title,
                source_name="Anime Corner",
                summary=summary if summary else None,
                published=_fmt_date(fields["pubDate"]) if "pubDate" in fields else None,
                url=fields.get("link") or fields.get("guid"),
                image_url=None,   # Anime Corner feed has no thumbnail element
            ))

        return items

    async def fetch(self, limit: int) -> list[NewsItem]:
        """
        Return up to `limit` news items from Anime Corner.
        Returns [] on any error — never raises.
        """
        try:
            items = await asyncio.to_thread(self._fetch_sync)
            logger.info("Anime Corner | fetched %d items", len(items))
            return items[:limit]
        except requests.Timeout:
            logger.warning("Anime Corner | timeout")
        except requests.HTTPError as exc:
            logger.warning("Anime Corner | HTTP error | %s", exc)
        except requests.RequestException as exc:
            logger.warning("Anime Corner | request error | %s", exc)
        except ET.ParseError as exc:
            logger.warning("Anime Corner | XML parse error | %s", exc)
        except Exception as exc:
            logger.error("Anime Corner | unexpected error | %s: %s", type(exc).__name__, exc)
        return []


# ── AniList trending client ────────────────────────────────────────────────────

class _AniListTrendingClient:
    """
    Fetches currently-trending airing anime from AniList GraphQL.

    Used as the primary source for fetch_trending() and as a last-resort
    fallback for fetch_latest() when both RSS feeds fail.

    Each result is returned as a NewsItem with:
      source_name = "AniList Trending"
      title       = best available title (English or Romaji)
      summary     = synopsis excerpt (max 300 chars)
      url         = AniList page
      image_url   = cover image
      published   = None  (trending shows have no publication date)
    """

    def _fetch_sync(self, limit: int) -> list[dict]:
        r = requests.post(
            _ANILIST_URL,
            json={"query": _ANILIST_TRENDING_QUERY, "variables": {"limit": limit}},
            timeout=_REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        return (data.get("data") or {}).get("Page", {}).get("media") or []

    async def fetch(self, limit: int) -> list[NewsItem]:
        """
        Return up to `limit` trending anime as NewsItems.
        Returns [] on any error — never raises.
        """
        try:
            media_list = await asyncio.to_thread(self._fetch_sync, limit)
            logger.info("AniList Trending | fetched %d items", len(media_list))
        except requests.Timeout:
            logger.warning("AniList Trending | timeout")
            return []
        except requests.HTTPError as exc:
            logger.warning("AniList Trending | HTTP error | %s", exc)
            return []
        except requests.RequestException as exc:
            logger.warning("AniList Trending | request error | %s", exc)
            return []
        except Exception as exc:
            logger.error("AniList Trending | unexpected | %s: %s", type(exc).__name__, exc)
            return []

        items: list[NewsItem] = []
        for media in media_list:
            title_obj = media.get("title") or {}
            title = (
                title_obj.get("english")
                or title_obj.get("romaji")
                or "Unknown Title"
            )
            raw_desc = media.get("description") or ""
            summary  = _strip_html(raw_desc) or None
            if summary and len(summary) > 300:
                summary = summary[:300].rstrip() + "…"

            cover = (media.get("coverImage") or {}).get("large")

            items.append(NewsItem(
                title=title,
                source_name="AniList Trending",
                summary=summary,
                published=None,
                url=media.get("siteUrl"),
                image_url=cover,
            ))

        return items


# ── Service ────────────────────────────────────────────────────────────────────

class AnimeNewsService:
    """
    Aggregates anime news from multiple sources with TTL caching.

    Public API
    ──────────
      await news_service.fetch_latest(limit=8)   → NewsResult
      await news_service.fetch_trending(limit=8) → NewsResult

    Both methods:
      - Check the cache first (15-minute TTL).
      - Try sources in priority order; skip silently on failure.
      - Return a structured NewsResult(found=False) if all sources fail.
      - Never raise.

    Source priority
    ───────────────
      latest   : MAL RSS → Anime Corner → AniList Trending
      trending : AniList Trending → MAL RSS → Anime Corner
    """

    def __init__(self) -> None:
        self._cache   = _NewsCache()
        self._mal     = _MALRSSClient()
        self._corner  = _AnimeCornerClient()
        self._anilist = _AniListTrendingClient()

    # ── Public methods ─────────────────────────────────────────────────────────

    async def fetch_latest(self, limit: int = _DEFAULT_LIMIT) -> NewsResult:
        """
        Fetch the latest anime news articles.

        Priority: MAL RSS → Anime Corner → AniList Trending (fallback).
        Returns a cached result if one exists within the TTL window.
        """
        cached = self._cache.get("latest", limit)
        if cached is not None:
            logger.debug("News cache HIT | mode=latest | limit=%d", limit)
            return NewsResult(
                found=cached.found,
                mode=cached.mode,
                source=cached.source,
                cached=True,
                items=cached.items,
            )

        # Pass bound methods (callables), not pre-created coroutines.
        # _try_sources calls each one lazily so unused sources are never awaited
        # and mock patches applied before the call take effect correctly.
        sources: list[tuple[str, object]] = [
            ("MAL",              self._mal.fetch),
            ("Anime Corner",     self._corner.fetch),
            ("AniList Trending", self._anilist.fetch),
        ]
        return await self._try_sources("latest", limit, sources)

    async def fetch_trending(self, limit: int = _DEFAULT_LIMIT) -> NewsResult:
        """
        Fetch currently-trending anime (not traditional articles).

        Priority: AniList Trending → MAL RSS → Anime Corner.
        Returns a cached result if one exists within the TTL window.
        """
        cached = self._cache.get("trending", limit)
        if cached is not None:
            logger.debug("News cache HIT | mode=trending | limit=%d", limit)
            return NewsResult(
                found=cached.found,
                mode=cached.mode,
                source=cached.source,
                cached=True,
                items=cached.items,
            )

        sources: list[tuple[str, object]] = [
            ("AniList Trending", self._anilist.fetch),
            ("MAL",              self._mal.fetch),
            ("Anime Corner",     self._corner.fetch),
        ]
        return await self._try_sources("trending", limit, sources)

    # ── Private helpers ────────────────────────────────────────────────────────

    async def _try_sources(
        self,
        mode: str,
        limit: int,
        sources: list[tuple[str, object]],
    ) -> NewsResult:
        """
        Try each (name, fetch_callable) pair in order.

        `fetch_callable` is a bound method accepting a single `limit: int`
        argument and returning a coroutine that resolves to list[NewsItem].
        Calling it here (lazily) means unused sources are never invoked, no
        coroutines are abandoned, and mock patches applied before this call
        take effect correctly.

        Returns the first non-empty result, or NewsResult(found=False) if all
        sources return empty lists.
        """
        for source_name, fetch_fn in sources:
            try:
                items = await fetch_fn(limit)  # type: ignore[operator]
            except Exception as exc:
                logger.warning("News source %r raised unexpectedly | %s", source_name, exc)
                items = []

            if items:
                result = NewsResult(
                    found=True,
                    mode=mode,
                    source=source_name,
                    items=items,
                )
                self._cache.set(mode, limit, result)
                logger.info(
                    "News fetch OK | mode=%s | source=%s | items=%d",
                    mode, source_name, len(items),
                )
                return result

            logger.info("News source %r returned no items — trying next", source_name)

        logger.warning("All news sources exhausted | mode=%s", mode)
        empty = NewsResult(found=False, mode=mode, source="none")
        # Cache the empty result briefly (5 min) to avoid hammering all sources
        # simultaneously when they are all down.
        key = self._cache._key(mode, limit)
        self._cache._store[key] = (empty, time.monotonic() + 300)
        return empty

    def cache_size(self) -> int:
        """Number of live cache entries (for diagnostics)."""
        return self._cache.size()


# ── Module-level singleton ─────────────────────────────────────────────────────

news_service = AnimeNewsService()
"""
Shared AnimeNewsService instance.  Import this; don't construct your own.
One instance = one shared cache = fewer redundant API calls.
"""
