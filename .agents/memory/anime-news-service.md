---
name: Anime News Service
description: Architecture decisions and source reliability notes for AnimeNewsService in services/anime_news.py
---

## Source reliability (probed July 2026)

| Source | URL | Status | Notes |
|---|---|---|---|
| MAL RSS | https://myanimelist.net/rss/news.xml | ✅ Working | 20 items, has thumbnail, pubDate, description |
| Anime Corner | https://animecorner.me/feed/ | ✅ Working | 25 items, no thumbnail element in feed |
| ANN | https://www.animenewsnetwork.com/all/rss.xml?cat=news | ❌ 403 | Cloudflare blocks all bot UA; skip |
| Crunchyroll | https://www.crunchyroll.com/newsrss | ❌ 404 | Feed removed |
| LiveChart episodes | https://www.livechart.me/feeds/episodes | ✅ Working | Episode data, not news articles |
| AniList GraphQL | https://graphql.anilist.co | ✅ Working | Used for trending (TRENDING_DESC sort) |

## Coroutine leak fix

**Rule:** `_try_sources` must receive **bound method callables**, not pre-created coroutines.

Pre-creating `self._mal.fetch(limit)` in a list causes:
- Unused coroutines abandoned (RuntimeWarning) when an earlier source succeeds.
- Mock patches applied after coroutine creation have no effect.

**Fix:** pass `self._mal.fetch` (callable), call `await fetch_fn(limit)` inside the loop.

**Why:** Python coroutines are created at call time. Lazy calling means only the needed sources are ever awaited, and `patch.object` patches applied before the call take effect.

## Cache design

- Key: `SHA256("{mode}:{limit}")[:16]` — separate cache slot per mode+limit combination.
- TTL: 15 min for successful results, 5 min for empty (all-sources-fail) results.
- Empty result TTL is set by directly writing `_store[key]` with `monotonic() + 300`.

## Test isolation note

When testing all-sources-fail followed by partial-fail in the same test function,
create a **fresh** `AnimeNewsService()` for the partial-fail sub-test. The all-fail
block caches `found=False` for the key, which would mask the partial-fail result
if both sub-tests share the same service instance.
