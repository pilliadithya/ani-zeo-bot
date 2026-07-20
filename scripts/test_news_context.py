"""
Ani Zeo — News Context Flow Test
==================================
Tests the complete pipeline:
  AnimeNewsService → ContextBuilder.from_news_result() → ContextBuilder.to_text()

  No Telegram.  No bot.  No AI calls.
  Live API calls to MAL RSS and AniList (for the integration tests).

Run:
    python scripts/test_news_context.py
"""
from __future__ import annotations

import asyncio
import sys

sys.path.insert(0, ".")

from services.intent import Intent
from services.anime_news import NewsItem, NewsResult, AnimeNewsService
from services.context_builder import ContextBuilder, AIContext, UserContext

# ── Tiny test harness ──────────────────────────────────────────────────────────

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


def _has_no_html(text: str) -> bool:
    import re
    return not bool(re.search(r"<[a-zA-Z/][^>]*>", text))


def _has_no_json(text: str) -> bool:
    """True when the text contains no JSON-like constructs."""
    return "{" not in text and "}" not in text


# ── A — should_fetch_news() routing ───────────────────────────────────────────

def test_should_fetch_news() -> None:
    _section("A — should_fetch_news() routing")

    _check("ANIME_NEWS → True",      ContextBuilder.should_fetch_news(Intent.ANIME_NEWS))
    _check("TRENDING   → True",      ContextBuilder.should_fetch_news(Intent.TRENDING))

    # Must NOT trigger news for anime-search intents
    for intent in (
        Intent.SEARCH_ANIME, Intent.GET_DETAILS, Intent.CHARACTER_LOOKUP,
        Intent.WATCH_ORDER, Intent.DUB_INFO, Intent.LORE_QUESTION,
        Intent.EXPLANATION, Intent.OPEN_QUESTION,
    ):
        _check(f"{intent.name} → False", not ContextBuilder.should_fetch_news(intent))

    # Must NOT trigger news for conversational intents
    for intent in (
        Intent.GREETING, Intent.HELP, Intent.RECOMMENDATIONS,
        Intent.SEASON_INFO, Intent.UNKNOWN,
    ):
        _check(f"{intent.name} → False", not ContextBuilder.should_fetch_news(intent))

    # should_search and should_fetch_news must be mutually exclusive
    for intent in Intent:
        both = ContextBuilder.should_search(intent) and ContextBuilder.should_fetch_news(intent)
        _check(f"No overlap: {intent.name}", not both,
               "intent cannot be in both ANIME_CONTEXT and NEWS_CONTEXT sets")


# ── B — from_news_result(): found result ──────────────────────────────────────

def test_from_news_result_found() -> None:
    _section("B — from_news_result() with found result")

    items = [
        NewsItem(
            title="Attack on Titan Final Season Announced",
            source_name="MAL",
            summary="The final season of AoT has been officially announced.",
            published="20 Jul 2026",
            url="https://myanimelist.net/news/12345",
            image_url="https://cdn.myanimelist.net/thumb.jpg",
        ),
        NewsItem(
            title="One Piece Chapter 1000 Recap",
            source_name="Anime Corner",
            summary="A recap of the landmark chapter.",
            published="19 Jul 2026",
            url="https://animecorner.me/one-piece-1000/",
            image_url=None,
        ),
    ]
    news_result = NewsResult(found=True, mode="latest", source="MAL", items=items)
    profile     = {"nickname": "Karan", "language": "English"}

    ctx = ContextBuilder.from_news_result(news_result, Intent.ANIME_NEWS, profile)

    _check("returns AIContext",          isinstance(ctx, AIContext))
    _check("found == True",              ctx.found is True)
    _check("anime is None",             ctx.anime is None)
    _check("news_mode == 'latest'",      ctx.news_mode == "latest")
    _check("news_items has 2 items",     len(ctx.news_items) == 2)
    _check("query is empty string",      ctx.query == "")
    _check("user.nickname == 'Karan'",   ctx.user.nickname == "Karan")
    _check("user.language == 'English'", ctx.user.language == "English")
    _check("user.intent_label set",      ctx.user.intent_label != "Unknown")

    # Items preserved correctly
    _check("item[0].title preserved",    ctx.news_items[0].title == items[0].title)
    _check("item[0].source_name preserved", ctx.news_items[0].source_name == "MAL")
    _check("item[1].title preserved",    ctx.news_items[1].title == items[1].title)


def test_from_news_result_cap() -> None:
    _section("B2 — from_news_result() caps at 5 items")

    items = [
        NewsItem(title=f"News {i}", source_name="MAL")
        for i in range(10)
    ]
    result = NewsResult(found=True, mode="latest", source="MAL", items=items)
    ctx    = ContextBuilder.from_news_result(result, Intent.ANIME_NEWS)

    _check("10 input items → 5 in context", len(ctx.news_items) == 5)
    _check("first 5 preserved in order",    ctx.news_items[0].title == "News 0")
    _check("item 5 excluded",               all(
        it.title != "News 5" for it in ctx.news_items
    ))


def test_from_news_result_not_found() -> None:
    _section("B3 — from_news_result() with not-found result")

    empty_result = NewsResult(found=False, mode="latest", source="none")
    ctx = ContextBuilder.from_news_result(empty_result, Intent.ANIME_NEWS)

    _check("found == False",         ctx.found is False)
    _check("news_items == []",       ctx.news_items == [])
    _check("news_mode == 'latest'",  ctx.news_mode == "latest")
    _check("anime is None",          ctx.anime is None)


def test_from_news_result_trending() -> None:
    _section("B4 — from_news_result() with trending result")

    items = [
        NewsItem(
            title="Demon Slayer Season 4",
            source_name="AniList Trending",
            summary="Currently the most-watched anime.",
            published=None,   # trending items have no publication date
            url="https://anilist.co/anime/12345",
        )
    ]
    result = NewsResult(found=True, mode="trending", source="AniList Trending", items=items)
    ctx    = ContextBuilder.from_news_result(result, Intent.TRENDING)

    _check("news_mode == 'trending'",    ctx.news_mode == "trending")
    _check("found == True",              ctx.found is True)
    _check("item count == 1",            len(ctx.news_items) == 1)


# ── C — to_text() news rendering ──────────────────────────────────────────────

def test_to_text_latest_news() -> None:
    _section("C1 — to_text() renders [Latest Anime News] section")

    items = [
        NewsItem(
            title="Fate Series Gets New Movie",
            source_name="MAL",
            summary="The Fate franchise is expanding with a new theatrical film.",
            published="20 Jul 2026",
            url="https://myanimelist.net/news/99999",
        ),
        NewsItem(
            title="Blue Lock S2 Confirmed",
            source_name="Anime Corner",
            summary="Studio 8bit confirmed production of season two.",
            published="18 Jul 2026",
            url="https://animecorner.me/blue-lock-s2/",
        ),
    ]
    result = NewsResult(found=True, mode="latest", source="MAL", items=items)
    ctx    = ContextBuilder.from_news_result(result, Intent.ANIME_NEWS)
    text   = ContextBuilder.to_text(ctx)

    print("\n── Generated news context block ──")
    print(text)
    print("──────────────────────────────────")

    _check("Has context header",             "=== Ani Zeo Context ===" in text)
    _check("Has footer marker",              "=== End Context ===" in text)
    _check("Has [Latest Anime News] header", "[Latest Anime News]" in text)
    _check("NOT [Trending Anime] header",    "[Trending Anime]" not in text)
    _check("Has item 1 title",               "Fate Series Gets New Movie" in text)
    _check("Has item 2 title",               "Blue Lock S2 Confirmed" in text)
    _check("Has Source field",               "Source:" in text)
    _check("Has MAL source label",           "MAL" in text)
    _check("Has Anime Corner source label",  "Anime Corner" in text)
    _check("Has published date",             "20 Jul 2026" in text)
    _check("Has Summary field",              "Summary:" in text)
    _check("Has URL field",                  "URL:" in text)
    _check("Has correct URL",                "myanimelist.net" in text)
    _check("No JSON braces",                 _has_no_json(text))
    _check("No HTML tags",                   _has_no_html(text))
    _check("No raw 'rss' word",              "rss" not in text.lower())
    _check("No raw 'xml' word",              "xml" not in text.lower())
    _check("No raw 'not_found' value",       "not_found" not in text)
    _check("No 'anilist' raw key",           "anilist" not in text.lower()
           or "AniList" in text)   # display label OK; raw key is not


def test_to_text_trending() -> None:
    _section("C2 — to_text() renders [Trending Anime] section")

    items = [
        NewsItem(
            title="Solo Leveling Season 2",
            source_name="AniList Trending",
            summary="The hit manhwa adaptation continues its second season.",
            published=None,
            url="https://anilist.co/anime/170942",
        )
    ]
    result = NewsResult(found=True, mode="trending", source="AniList Trending", items=items)
    ctx    = ContextBuilder.from_news_result(result, Intent.TRENDING)
    text   = ContextBuilder.to_text(ctx)

    _check("Has [Trending Anime] header",    "[Trending Anime]" in text)
    _check("NOT [Latest Anime News] header", "[Latest Anime News]" not in text)
    _check("Has title",                      "Solo Leveling Season 2" in text)
    _check("Has AniList Trending label",     "AniList Trending" in text)
    _check("No published date row",          "20 Jul" not in text,
           "trending items have no publication date")
    _check("Has Summary",                    "manhwa adaptation" in text)
    _check("No JSON braces",                 _has_no_json(text))
    _check("No HTML tags",                   _has_no_html(text))


def test_to_text_summary_truncation() -> None:
    _section("C3 — to_text() truncates long summaries at 200 chars")

    long_summary = "A" * 300
    items  = [NewsItem(title="Long Summary Test", source_name="MAL", summary=long_summary)]
    result = NewsResult(found=True, mode="latest", source="MAL", items=items)
    ctx    = ContextBuilder.from_news_result(result, Intent.ANIME_NEWS)
    text   = ContextBuilder.to_text(ctx)

    # Find the summary line
    for line in text.splitlines():
        if "Summary:" in line:
            summary_part = line.split("Summary:")[1].strip()
            _check("Truncated summary ≤ 204 chars",
                   len(summary_part) <= 204,   # 200 + "…" + small margin
                   f"got {len(summary_part)}")
            _check("Truncated summary ends with ellipsis", summary_part.endswith("…"))
            break
    else:
        _check("Summary line present", False, "Summary: line not found")


def test_to_text_no_news_available() -> None:
    _section("C4 — to_text() no-news note when all sources fail")

    empty_result = NewsResult(found=False, mode="latest", source="none")
    ctx  = ContextBuilder.from_news_result(empty_result, Intent.ANIME_NEWS,
                                           {"nickname": "Tester"})
    text = ContextBuilder.to_text(ctx)

    _check("Context block non-empty",        bool(text))
    _check("Has context header",             "=== Ani Zeo Context ===" in text)
    _check("Has [Note] section",             "[Note]" in text)
    _check("Has no-news message",            "No anime news" in text)
    _check("Has fallback instruction",       "training knowledge" in text)
    _check("Has [Latest Anime News]? No",    "[Latest Anime News]" not in text)
    _check("No JSON braces",                 _has_no_json(text))


def test_to_text_optional_fields_omitted() -> None:
    _section("C5 — to_text() omits optional fields when None")

    items = [NewsItem(
        title="Minimal Item",
        source_name="MAL",
        summary=None,     # no summary
        published=None,   # no date
        url=None,         # no URL
        image_url=None,
    )]
    result = NewsResult(found=True, mode="latest", source="MAL", items=items)
    ctx    = ContextBuilder.from_news_result(result, Intent.ANIME_NEWS)
    text   = ContextBuilder.to_text(ctx)

    _check("Has title",              "Minimal Item" in text)
    _check("No 'Summary:' row",      "Summary:" not in text)
    _check("No 'URL:' row",          "URL:" not in text)
    _check("Source row present",     "Source:" in text)


def test_anime_section_unchanged() -> None:
    _section("C6 — Existing anime context section still renders correctly")
    from services.anime_search import AnimeSearchResult

    result = AnimeSearchResult(
        found=True, query="Naruto", source="anilist",
        title_english="Naruto", title_romaji="Naruto",
        score=79.0, episodes=220, status="Finished",
        season="Fall 2002", studios=["Pierrot"],
        genres=["Action", "Adventure"],
    )
    ctx  = ContextBuilder.from_search_result(result, Intent.SEARCH_ANIME)
    text = ContextBuilder.to_text(ctx)

    _check("Anime section: has [Anime:] header", "[Anime:" in text)
    _check("Anime section: no [Latest Anime News]", "[Latest Anime News]" not in text)
    _check("Anime section: no [Trending Anime]",    "[Trending Anime]" not in text)
    _check("Anime section: has title",              "Naruto" in text)
    _check("Anime section: has rating",             "7.9/10" in text)
    _check("Anime section: has genres",             "Action" in text)


def test_not_found_note_unchanged() -> None:
    _section("C7 — Anime not-found note still renders (not masked by news_mode)")
    from services.anime_search import AnimeSearchResult

    nf_result = AnimeSearchResult(found=False, query="xyzzy123", source="not_found")
    ctx  = ContextBuilder.from_search_result(nf_result, Intent.SEARCH_ANIME)
    text = ContextBuilder.to_text(ctx)

    _check("Not-found: has [Note] section",          "[Note]" in text)
    _check("Not-found: mentions query",              "xyzzy123" in text)
    _check("Not-found: has hallucination warning",   "Do not hallucinate" in text)
    _check("Not-found: no [Latest Anime News]",      "[Latest Anime News]" not in text)
    _check("Not-found: no 'No anime news' message",  "No anime news" not in text)


# ── D — Live integration: full pipeline ───────────────────────────────────────

async def test_live_latest_pipeline() -> None:
    _section("D1 — Live integration: fetch_latest → from_news_result → to_text")

    svc    = AnimeNewsService()
    result = await svc.fetch_latest(limit=5)
    ctx    = ContextBuilder.from_news_result(result, Intent.ANIME_NEWS,
                                             {"nickname": "TestUser", "language": "English"})
    text   = ContextBuilder.to_text(ctx)

    _check("Pipeline: NewsResult received",       isinstance(result, NewsResult))
    _check("Pipeline: AIContext built",           isinstance(ctx, AIContext))
    _check("Pipeline: to_text non-empty",         bool(text))
    _check("Pipeline: context header present",    "=== Ani Zeo Context ===" in text)
    _check("Pipeline: footer present",            "=== End Context ===" in text)

    if result.found:
        _check("Pipeline: [Latest Anime News] header",    "[Latest Anime News]" in text)
        _check("Pipeline: at least 1 item title shown",   result.items[0].title in text)
        _check("Pipeline: no JSON in output",             _has_no_json(text))
        _check("Pipeline: no HTML in output",             _has_no_html(text))
        _check("Pipeline: items capped at 5 in context",  len(ctx.news_items) <= 5)
        _check("Pipeline: news_mode == 'latest'",         ctx.news_mode == "latest")

        # Verify no internal fields leak through
        _check("Pipeline: no 'not_found' in output",  "not_found" not in text)
        _check("Pipeline: no raw 'anilist' key",       "anilist:" not in text)
        _check("Pipeline: no raw 'jikan' key",         "jikan:" not in text)

        # All items in context have no HTML
        for i, item in enumerate(ctx.news_items):
            _check(f"Pipeline: item[{i}] summary clean", _has_no_html(item.summary or ""))
    else:
        _check("Pipeline: no-news note present", "No anime news" in text)


async def test_live_trending_pipeline() -> None:
    _section("D2 — Live integration: fetch_trending → from_news_result → to_text")

    svc    = AnimeNewsService()
    result = await svc.fetch_trending(limit=5)
    ctx    = ContextBuilder.from_news_result(result, Intent.TRENDING,
                                             {"nickname": "TestUser"})
    text   = ContextBuilder.to_text(ctx)

    _check("Pipeline: NewsResult received",    isinstance(result, NewsResult))
    _check("Pipeline: AIContext built",        isinstance(ctx, AIContext))
    _check("Pipeline: to_text non-empty",      bool(text))
    _check("Pipeline: news_mode == 'trending'", ctx.news_mode == "trending")

    if result.found:
        _check("Pipeline: [Trending Anime] header", "[Trending Anime]" in text)
        _check("Pipeline: no JSON in output",        _has_no_json(text))
        _check("Pipeline: no HTML in output",        _has_no_html(text))


async def test_live_graceful_failure() -> None:
    _section("D3 — Live integration: graceful failure → clean no-news context")
    from unittest.mock import AsyncMock, patch

    svc = AnimeNewsService()
    with (
        patch.object(svc._mal,     "fetch", new=AsyncMock(return_value=[])),
        patch.object(svc._corner,  "fetch", new=AsyncMock(return_value=[])),
        patch.object(svc._anilist, "fetch", new=AsyncMock(return_value=[])),
    ):
        result = await svc.fetch_latest(limit=8)

    ctx  = ContextBuilder.from_news_result(result, Intent.ANIME_NEWS,
                                           {"nickname": "Tester"})
    text = ContextBuilder.to_text(ctx)

    _check("Graceful fail: result.found == False",     result.found is False)
    _check("Graceful fail: ctx.news_items == []",      ctx.news_items == [])
    _check("Graceful fail: to_text non-empty",         bool(text),
           "user section + note must still render")
    _check("Graceful fail: has [Note]",                "[Note]" in text)
    _check("Graceful fail: no-news message",           "No anime news" in text)
    _check("Graceful fail: fallback instruction",      "training knowledge" in text)
    _check("Graceful fail: no JSON",                   _has_no_json(text))
    _check("Graceful fail: no HTML",                   _has_no_html(text))
    _check("Graceful fail: no [Latest Anime News]",    "[Latest Anime News]" not in text)


# ── Entry point ────────────────────────────────────────────────────────────────

async def main() -> None:
    width = 90
    print("\n" + "=" * width)
    print("  Ani Zeo — News Context Flow Test")
    print("=" * width)
    print("  Pipeline: AnimeNewsService → ContextBuilder → to_text()")
    print("  No Telegram, no bot, no AI calls.\n")

    # Sync tests
    test_should_fetch_news()
    test_from_news_result_found()
    test_from_news_result_cap()
    test_from_news_result_not_found()
    test_from_news_result_trending()
    test_to_text_latest_news()
    test_to_text_trending()
    test_to_text_summary_truncation()
    test_to_text_no_news_available()
    test_to_text_optional_fields_omitted()
    test_anime_section_unchanged()
    test_not_found_note_unchanged()

    # Live async tests
    await test_live_latest_pipeline()
    await test_live_trending_pipeline()
    await test_live_graceful_failure()

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
