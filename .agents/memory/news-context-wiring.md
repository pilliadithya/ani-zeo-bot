---
name: News Context Wiring
description: How ANIME_NEWS and TRENDING intents are routed through the news service and context builder into the AI.
---

## Intent routing table (as of July 2026)

| Intent | should_search | should_fetch_news | Fetch call | Context method |
|---|---|---|---|---|
| SEARCH_ANIME, GET_DETAILS, … | True | False | search_service.search() | from_search_result() |
| ANIME_NEWS | False | True | news_service.fetch_latest() | from_news_result() |
| TRENDING | False | True | news_service.fetch_trending() | from_news_result() |
| Everything else | False | False | — | build_user_only() |

**Why:** The two sets (_ANIME_CONTEXT_INTENTS, _NEWS_CONTEXT_INTENTS) in context_builder.py must be mutually exclusive — a test verifies no overlap for every Intent value.

## AIContext fields for news

Two fields added to AIContext:
- `news_items: list[NewsItem]` — populated by from_news_result(), capped at 5
- `news_mode: str` — "latest" | "trending" | "" (empty for non-news paths)

**Why cap at 5:** Keeps the context block within a reasonable token budget while still giving the AI enough articles to produce a useful response.

## to_text() section order

1. [User] — always (if any user data exists)
2. [Latest Anime News] or [Trending Anime] — if news_mode is set
   OR [Anime: …] — if anime search found a title
   OR [Note] — if anime search found nothing OR news fetch returned no items
3. Footer

The news and anime sections are mutually exclusive (elif chain). A context built from from_news_result() will never show the anime not-found note because news_mode is set and the elif for news comes first.

## Graceful failure path

When all news sources fail (NewsResult.found=False):
- from_news_result() returns AIContext with news_items=[], news_mode="latest/trending"
- to_text() renders a [Note] telling the AI live news is unavailable and to use training knowledge
- The AI still responds — never crashes, never blocks

## Files modified

- services/context_builder.py — import NewsItem/NewsResult, _NEWS_CONTEXT_INTENTS frozenset, should_fetch_news(), from_news_result() implementation, news section in to_text()
- ai/message_handler.py — import news_service, elif branch in _build_context_for_route()
