"""
Ani Zeo — Anime News Service Test
==================================
Tests the AnimeNewsService in isolation.

  No Telegram.  No bot.  No AI calls.
  All tests hit the real RSS / API endpoints.

Run:
    python scripts/test_anime_news.py
"""
from __future__ import annotations

import asyncio
import sys
import time

# ── Bootstrap path so we can run from project root ────────────────────────────
sys.path.insert(0, ".")

from services.anime_news import (
    AnimeNewsService,
    NewsItem,
    NewsResult,
    _NewsCache,
    _MALRSSClient,
    _AnimeCornerClient,
    _AniListTrendingClient,
    news_service,
)

# ── Tiny test harness (no pytest dependency) ───────────────────────────────────

_passed = 0
_failed = 0

def _check(label: str, condition: bool, detail: str = "") -> None:
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"  PASS ✓  {label}")
    else:
        _failed += 1
        extra = f"  ({detail})" if detail else ""
        print(f"  FAIL ✗  {label}{extra}")

def _section(title: str) -> None:
    print(f"\n{'─'*90}")
    print(f"  {title}")
    print(f"{'─'*90}")

# ── Helpers ────────────────────────────────────────────────────────────────────

def _has_no_html(text: str | None) -> bool:
    """True when text contains no HTML tags."""
    if text is None:
        return True
    import re
    return not bool(re.search(r"<[a-zA-Z/][^>]*>", text))

def _is_url(value: str | None) -> bool:
    if value is None:
        return True   # Optional field — None is valid
    return value.startswith("http://") or value.startswith("https://")


# ── A1 — Dataclass structure ───────────────────────────────────────────────────

def test_dataclass_structure() -> None:
    _section("A1 — Dataclass structure")

    # NewsItem
    item = NewsItem(
        title="Test Title",
        source_name="MAL",
        summary="Short summary.",
        published="20 Jul 2026",
        url="https://myanimelist.net/news/12345",
        image_url="https://cdn.myanimelist.net/thumb.jpg",
    )
    _check("NewsItem: title set",       item.title == "Test Title")
    _check("NewsItem: source_name set", item.source_name == "MAL")
    _check("NewsItem: summary set",     item.summary == "Short summary.")
    _check("NewsItem: published set",   item.published == "20 Jul 2026")
    _check("NewsItem: url set",         item.url is not None)
    _check("NewsItem: image_url set",   item.image_url is not None)

    # NewsItem minimal (only required fields)
    minimal = NewsItem(title="Minimal", source_name="Test")
    _check("NewsItem minimal: summary=None",   minimal.summary is None)
    _check("NewsItem minimal: published=None", minimal.published is None)
    _check("NewsItem minimal: url=None",       minimal.url is None)
    _check("NewsItem minimal: image_url=None", minimal.image_url is None)

    # NewsResult
    result = NewsResult(
        found=True, mode="latest", source="MAL",
        items=[item],
    )
    _check("NewsResult: found=True",     result.found is True)
    _check("NewsResult: mode set",       result.mode == "latest")
    _check("NewsResult: source set",     result.source == "MAL")
    _check("NewsResult: cached=False",   result.cached is False)
    _check("NewsResult: count == 1",     result.count == 1)
    _check("NewsResult: items list",     isinstance(result.items, list))

    # NewsResult empty
    empty = NewsResult(found=False, mode="latest", source="none")
    _check("NewsResult empty: found=False", empty.found is False)
    _check("NewsResult empty: count == 0",  empty.count == 0)
    _check("NewsResult empty: items == []", empty.items == [])


# ── A2 — Cache ─────────────────────────────────────────────────────────────────

def test_cache() -> None:
    _section("A2 — Cache (in-process, no network)")

    cache = _NewsCache()
    _check("Empty cache size == 0", cache.size() == 0)
    _check("Miss returns None",     cache.get("latest", 8) is None)

    result = NewsResult(found=True, mode="latest", source="MAL",
                        items=[NewsItem(title="X", source_name="MAL")])
    cache.set("latest", 8, result)
    _check("Cache size == 1 after set",   cache.size() == 1)

    hit = cache.get("latest", 8)
    _check("Cache hit returns result",    hit is not None)
    _check("Cache hit found == True",     hit is not None and hit.found is True)

    # Different limit → different slot
    miss = cache.get("latest", 5)
    _check("Different limit → cache miss", miss is None)

    # Different mode → different slot
    miss2 = cache.get("trending", 8)
    _check("Different mode → cache miss",  miss2 is None)

    # Expiry simulation
    cache2 = _NewsCache()
    cache2.set("latest", 8, result)
    # Manually expire the entry
    key = cache2._key("latest", 8)
    r, _ = cache2._store[key]
    cache2._store[key] = (r, time.monotonic() - 1)
    _check("Expired entry → miss",         cache2.get("latest", 8) is None)
    _check("Cache size 0 after expiry",    cache2.size() == 0)


# ── B1 — MAL RSS live fetch ────────────────────────────────────────────────────

async def test_mal_rss() -> None:
    _section("B1 — MAL RSS client (live)")

    client = _MALRSSClient()
    items  = await client.fetch(limit=5)

    _check("MAL RSS: returned a list",       isinstance(items, list))
    _check("MAL RSS: non-empty",             len(items) > 0,
           f"got {len(items)} items")
    _check("MAL RSS: ≤ 5 items",             len(items) <= 5)

    if items:
        item = items[0]
        _check("MAL item: has title",        bool(item.title))
        _check("MAL item: source_name='MAL'", item.source_name == "MAL")
        _check("MAL item: title is str",     isinstance(item.title, str))
        _check("MAL item: url is valid",     _is_url(item.url))
        _check("MAL item: image_url valid",  _is_url(item.image_url))
        _check("MAL item: no HTML in summary", _has_no_html(item.summary))
        _check("MAL item: published str or None",
               item.published is None or isinstance(item.published, str))
        if item.published:
            _check("MAL item: published human-readable",
                   any(m in item.published for m in [
                       "Jan","Feb","Mar","Apr","May","Jun",
                       "Jul","Aug","Sep","Oct","Nov","Dec"
                   ]))
        if item.summary:
            _check("MAL item: summary ≤ 300 chars", len(item.summary) <= 303)

    # Consistency across all items
    for i, it in enumerate(items):
        _check(f"MAL item[{i}]: title non-empty",       bool(it.title))
        _check(f"MAL item[{i}]: source_name == 'MAL'",  it.source_name == "MAL")
        _check(f"MAL item[{i}]: url valid or None",      _is_url(it.url))
        _check(f"MAL item[{i}]: no HTML in summary",     _has_no_html(it.summary))


# ── B2 — Anime Corner RSS live fetch ──────────────────────────────────────────

async def test_anime_corner() -> None:
    _section("B2 — Anime Corner RSS client (live)")

    client = _AnimeCornerClient()
    items  = await client.fetch(limit=5)

    _check("Anime Corner: returned a list", isinstance(items, list))
    _check("Anime Corner: non-empty",       len(items) > 0,
           f"got {len(items)} items")
    _check("Anime Corner: ≤ 5 items",       len(items) <= 5)

    if items:
        item = items[0]
        _check("Corner item: has title",             bool(item.title))
        _check("Corner item: source_name correct",   item.source_name == "Anime Corner")
        _check("Corner item: url valid",             _is_url(item.url))
        _check("Corner item: no HTML in summary",    _has_no_html(item.summary))
        _check("Corner item: image_url is None",     item.image_url is None,
               "Anime Corner feed has no thumbnail element")
        _check("Corner item: published str or None",
               item.published is None or isinstance(item.published, str))

    for i, it in enumerate(items):
        _check(f"Corner item[{i}]: title non-empty",        bool(it.title))
        _check(f"Corner item[{i}]: source_name='Anime Corner'",
               it.source_name == "Anime Corner")
        _check(f"Corner item[{i}]: no HTML in summary",     _has_no_html(it.summary))


# ── B3 — AniList Trending live fetch ──────────────────────────────────────────

async def test_anilist_trending() -> None:
    _section("B3 — AniList Trending client (live)")

    client = _AniListTrendingClient()
    items  = await client.fetch(limit=5)

    _check("AniList: returned a list",  isinstance(items, list))
    _check("AniList: non-empty",        len(items) > 0,
           f"got {len(items)} items")
    _check("AniList: ≤ 5 items",        len(items) <= 5)

    if items:
        item = items[0]
        _check("AniList item: has title",           bool(item.title))
        _check("AniList item: source_name correct", item.source_name == "AniList Trending")
        _check("AniList item: url valid",           _is_url(item.url))
        _check("AniList item: image_url valid",     _is_url(item.image_url))
        _check("AniList item: published is None",   item.published is None,
               "Trending anime have no news publication date")
        _check("AniList item: no HTML in summary",  _has_no_html(item.summary))
        if item.summary:
            _check("AniList item: summary ≤ 300 chars", len(item.summary) <= 303)

    for i, it in enumerate(items):
        _check(f"AniList item[{i}]: title non-empty",  bool(it.title))
        _check(f"AniList item[{i}]: no HTML in summary", _has_no_html(it.summary))


# ── C1 — Service: fetch_latest ────────────────────────────────────────────────

async def test_fetch_latest() -> None:
    _section("C1 — AnimeNewsService.fetch_latest() (live)")

    svc    = AnimeNewsService()
    result = await svc.fetch_latest(limit=6)

    _check("fetch_latest: returns NewsResult",  isinstance(result, NewsResult))
    _check("fetch_latest: mode == 'latest'",    result.mode == "latest")
    _check("fetch_latest: cached == False",     result.cached is False,
           "first call must not be cached")
    _check("fetch_latest: found is bool",       isinstance(result.found, bool))

    if result.found:
        _check("fetch_latest: items non-empty",  result.count > 0)
        _check("fetch_latest: ≤ 6 items",        result.count <= 6)
        _check("fetch_latest: source set",       bool(result.source))
        _check("fetch_latest: source != 'none'", result.source != "none")

        for i, item in enumerate(result.items):
            _check(f"latest item[{i}]: title non-empty",     bool(item.title))
            _check(f"latest item[{i}]: source_name non-empty", bool(item.source_name))
            _check(f"latest item[{i}]: url valid",           _is_url(item.url))
            _check(f"latest item[{i}]: no HTML in summary",  _has_no_html(item.summary))

    # Cache hit on second call
    result2 = await svc.fetch_latest(limit=6)
    _check("fetch_latest 2nd call: cached == True",  result2.cached is True)
    _check("fetch_latest 2nd call: same item count", result2.count == result.count)


# ── C2 — Service: fetch_trending ──────────────────────────────────────────────

async def test_fetch_trending() -> None:
    _section("C2 — AnimeNewsService.fetch_trending() (live)")

    svc    = AnimeNewsService()
    result = await svc.fetch_trending(limit=6)

    _check("fetch_trending: returns NewsResult", isinstance(result, NewsResult))
    _check("fetch_trending: mode == 'trending'", result.mode == "trending")
    _check("fetch_trending: cached == False",    result.cached is False)
    _check("fetch_trending: found is bool",      isinstance(result.found, bool))

    if result.found:
        _check("fetch_trending: items non-empty", result.count > 0)
        _check("fetch_trending: ≤ 6 items",       result.count <= 6)
        _check("fetch_trending: source set",      bool(result.source))

        for i, item in enumerate(result.items):
            _check(f"trending item[{i}]: title non-empty",      bool(item.title))
            _check(f"trending item[{i}]: source_name non-empty", bool(item.source_name))
            _check(f"trending item[{i}]: url valid",            _is_url(item.url))
            _check(f"trending item[{i}]: no HTML in summary",   _has_no_html(item.summary))

    # Cache hit on second call
    result2 = await svc.fetch_trending(limit=6)
    _check("fetch_trending 2nd call: cached == True", result2.cached is True)


# ── C3 — Service: graceful failure (bad URL injection) ────────────────────────

async def test_graceful_failure() -> None:
    _section("C3 — Graceful failure (source failure simulation)")
    from unittest.mock import AsyncMock, patch

    svc = AnimeNewsService()

    # Patch all three source clients to return []
    with (
        patch.object(svc._mal,     "fetch", new=AsyncMock(return_value=[])),
        patch.object(svc._corner,  "fetch", new=AsyncMock(return_value=[])),
        patch.object(svc._anilist, "fetch", new=AsyncMock(return_value=[])),
    ):
        result = await svc.fetch_latest(limit=8)

    _check("All-source-fail: returns NewsResult",   isinstance(result, NewsResult))
    _check("All-source-fail: found == False",        result.found is False)
    _check("All-source-fail: source == 'none'",      result.source == "none")
    _check("All-source-fail: items is empty list",   result.items == [])
    _check("All-source-fail: count == 0",            result.count == 0)

    # Partial failure: only first source fails.
    # Use a FRESH service so the cache from the all-fail block above
    # (which stores found=False for "latest:8") doesn't mask this test.
    svc2 = AnimeNewsService()
    good_items = [NewsItem(title="Good", source_name="Anime Corner")]
    with (
        patch.object(svc2._mal,    "fetch", new=AsyncMock(return_value=[])),
        patch.object(svc2._corner, "fetch", new=AsyncMock(return_value=good_items)),
    ):
        result2 = await svc2.fetch_latest(limit=8)

    _check("Partial-fail: found == True",           result2.found is True)
    _check("Partial-fail: source == 'Anime Corner'", result2.source == "Anime Corner")
    _check("Partial-fail: items returned",          result2.count == 1)


# ── C4 — Singleton ────────────────────────────────────────────────────────────

async def test_singleton() -> None:
    _section("C4 — Module-level singleton")

    from services.anime_news import news_service as ns
    _check("Singleton: is AnimeNewsService",      isinstance(ns, AnimeNewsService))
    _check("Singleton: has fetch_latest attr",    hasattr(ns, "fetch_latest"))
    _check("Singleton: has fetch_trending attr",  hasattr(ns, "fetch_trending"))
    _check("Singleton: has cache_size attr",      hasattr(ns, "cache_size"))

    # Using the singleton for a real fetch
    result = await ns.fetch_latest(limit=3)
    _check("Singleton fetch_latest: returns NewsResult", isinstance(result, NewsResult))
    _check("Singleton fetch_latest: mode == 'latest'",   result.mode == "latest")


# ── D1 — services/__init__.py exports ─────────────────────────────────────────

def test_package_exports() -> None:
    _section("D1 — services package exports")

    import services
    _check("services exports NewsItem",          hasattr(services, "NewsItem"))
    _check("services exports NewsResult",        hasattr(services, "NewsResult"))
    _check("services exports AnimeNewsService",  hasattr(services, "AnimeNewsService"))
    _check("services exports news_service",      hasattr(services, "news_service"))

    # Previously exported symbols must remain
    _check("services still exports Intent",          hasattr(services, "Intent"))
    _check("services still exports IntentClassifier", hasattr(services, "IntentClassifier"))
    _check("services still exports search_service",  hasattr(services, "search_service"))
    _check("services still exports ContextBuilder",  hasattr(services, "ContextBuilder"))


# ── Entry point ────────────────────────────────────────────────────────────────

async def main() -> None:
    width = 90
    print("\n" + "=" * width)
    print("  Ani Zeo — Anime News Service Test")
    print("=" * width)
    print("  No Telegram, no bot, no AI calls — pure service layer + live API calls.\n")

    # Sync tests (no network)
    test_dataclass_structure()
    test_cache()
    test_package_exports()

    # Async tests (live network)
    await test_mal_rss()
    await test_anime_corner()
    await test_anilist_trending()
    await test_fetch_latest()
    await test_fetch_trending()
    await test_graceful_failure()
    await test_singleton()

    # Summary
    total = _passed + _failed
    print(f"\n{'=' * width}")
    if _failed == 0:
        print(f"  {total}/{total} passed — all tests passed ✓")
    else:
        print(f"  {_passed}/{total} passed  |  {_failed} FAILED ✗")
    print("=" * width + "\n")

    if _failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
