"""
Context Builder test — scripts/test_context_builder.py

Run from the project root:
    python scripts/test_context_builder.py

Tests the ContextBuilder in isolation — no Telegram, no bot, no AI calls.

Test plan
─────────
  Part A — Unit tests (synthetic data, no network)
    A1. should_search()           — correct intents trigger search
    A2. from_search_result()      — real AnimeSearchResult → AIContext
    A3. not-found result          — not_found propagates correctly
    A4. build_user_only()         — user-only context (no anime)
    A5. to_text() format          — section headers, field labels, omissions
    A6. empty values omitted      — None / empty list → absent from output
    A7. source-agnostic output    — AniList and Jikan produce identical structure

  Part B — Integration test (real AniList call)
    B1. Live search → context → to_text()
        Confirms the full pipeline works end-to-end.
"""
from __future__ import annotations

import asyncio
import dataclasses
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.intent import Intent
from services.anime_search import AnimeSearchResult
from services.context_builder import (
    ContextBuilder,
    AIContext,
    AnimeContext,
    UserContext,
)

# ── Formatting helpers ─────────────────────────────────────────────────────────

_W = 90
_PASS = "PASS ✓"
_FAIL = "FAIL ✗"

_results: list[tuple[str, bool, str]] = []   # (label, ok, note)


def _check(label: str, cond: bool, note: str = "") -> None:
    _results.append((label, cond, note))
    mark = _PASS if cond else _FAIL
    suffix = f"  ({note})" if note else ""
    print(f"  {mark}  {label}{suffix}")


def _hr(char: str = "─") -> None:
    print(char * _W)


def _section(title: str) -> None:
    print()
    _hr()
    print(f"  {title}")
    _hr()


# ── Synthetic fixture builders ─────────────────────────────────────────────────

def _make_anilist_result(query: str = "Attack on Titan") -> AnimeSearchResult:
    """Build a realistic AnimeSearchResult as AniList would return it."""
    return AnimeSearchResult(
        found=True,
        query=query,
        source="anilist",
        cached=False,
        title_romaji="Shingeki no Kyojin",
        title_english="Attack on Titan",
        title_native="進撃の巨人",
        score=90.0,              # AniList 0-100 scale
        rank="#12",
        popularity=250_000,
        episodes=25,
        status="Finished",
        season="Spring 2013",
        source_material="Manga",
        duration="24 min/ep",
        synopsis=(
            "Several hundred years ago, humans were nearly wiped out by titans. "
            "Titans are typically several stories tall, seem to have no intelligence, "
            "devour human beings and, worst of all, seem to do it for the pleasure "
            "rather than as a food source. A small percentage of humanity survived "
            "by walling themselves in a city protected by extremely high walls."
        ),
        trailer_url="https://www.youtube.com/watch?v=MGRm4IzK1SQ",
        genres=["Action", "Drama", "Fantasy", "Military", "Mystery"],
        studios=["Wit Studio"],
        streaming_platforms=["Crunchyroll", "Hulu", "Netflix"],
        relations=[
            {"type": "SEQUEL", "title": "Attack on Titan Season 2"},
        ],
    )


def _make_jikan_result(query: str = "Attack on Titan") -> AnimeSearchResult:
    """Build the same anime as Jikan would return it (different source, same data)."""
    return dataclasses.replace(
        _make_anilist_result(query),
        source="jikan",
        cached=False,
        # Jikan scores are 0-10, multiplied ×10 on ingestion → same 0-100 scale
        score=90.0,
    )


def _make_not_found_result(query: str = "xyzzy9999") -> AnimeSearchResult:
    return AnimeSearchResult(found=False, query=query, source="not_found")


def _profile_full() -> dict:
    return {"nickname": "Karan", "language": "Tenglish"}


def _profile_partial() -> dict:
    return {"nickname": "Anika"}   # no language key


def _profile_empty() -> dict:
    return {}


# ═══════════════════════════════════════════════════════════════════════════════
# Part A — Unit tests (no network)
# ═══════════════════════════════════════════════════════════════════════════════

def test_should_search() -> None:
    _section("A1 — should_search() intent routing")

    yes_intents = [
        Intent.SEARCH_ANIME,
        Intent.GET_DETAILS,
        Intent.CHARACTER_LOOKUP,
        Intent.WATCH_ORDER,
        Intent.DUB_INFO,
        Intent.LORE_QUESTION,
        Intent.EXPLANATION,
        Intent.OPEN_QUESTION,
    ]
    no_intents = [
        Intent.RECOMMENDATIONS,
        Intent.TOP_ANIME,
        Intent.TRENDING,
        Intent.SEASON_INFO,
        Intent.GENRE_BROWSE,
        Intent.ANIME_NEWS,
        Intent.GREETING,
        Intent.HELP,
        Intent.UNKNOWN,
        Intent.WATCHLIST_ACTION,
    ]

    for intent in yes_intents:
        _check(
            f"should_search({intent.name}) → True",
            ContextBuilder.should_search(intent),
        )

    for intent in no_intents:
        _check(
            f"should_search({intent.name}) → False",
            not ContextBuilder.should_search(intent),
        )


def test_from_search_result() -> None:
    _section("A2 — from_search_result() with AniList result")
    result = _make_anilist_result()
    ctx = ContextBuilder.from_search_result(result, Intent.SEARCH_ANIME, _profile_full())

    _check("ctx.found is True", ctx.found)
    _check("ctx.query == 'Attack on Titan'", ctx.query == "Attack on Titan")
    _check("ctx.anime is not None", ctx.anime is not None)

    a = ctx.anime
    assert a is not None

    # Titles
    _check("title_english == 'Attack on Titan'",   a.title_english == "Attack on Titan")
    _check("title_romaji == 'Shingeki no Kyojin'",  a.title_romaji  == "Shingeki no Kyojin")
    _check("title_native == '進撃の巨人'",           a.title_native  == "進撃の巨人")

    # Score conversion: 90 → "9.0/10"
    _check("rating == '9.0/10'",                   a.rating == "9.0/10")

    # Internal score must NOT be on AnimeContext
    _check("raw score field absent from AnimeContext",
           not hasattr(a, "score"),
           "no raw 0-100 field leaks through")

    # Internal IDs must NOT be on AnimeContext
    for internal in ("id", "mal_id", "cover_url", "popularity", "rank", "cached"):
        _check(f"field '{internal}' absent from AnimeContext",
               not hasattr(a, internal))

    # Episodes
    _check("episodes == '25'",                 a.episodes == "25")

    # Season + year extraction
    _check("season == 'Spring 2013'",          a.season == "Spring 2013")
    _check("year extracted → '2013'",          a.year   == "2013")

    # Studio — primary only
    _check("studio == 'Wit Studio'",           a.studio == "Wit Studio")

    # Relations — formatted strings not raw dicts
    _check("relations is list[str]",           isinstance(a.relations, list))
    _check("sequel formatted correctly",
           any("Sequel" in r for r in a.relations))
    for rel in a.relations:
        _check(f"relation is str not dict: {rel[:30]}",
               isinstance(rel, str), "no raw dict leaks through")

    # Source label — human-readable
    _check("data_source == 'AniList'",         a.data_source == "AniList")

    # User context
    u = ctx.user
    _check("user.nickname == 'Karan'",         u.nickname == "Karan")
    _check("user.language == 'Tenglish'",      u.language == "Tenglish")
    _check("user.intent_label != 'Unknown'",   u.intent_label != "Unknown")


def test_not_found_result() -> None:
    _section("A3 — from_search_result() with not-found result")
    result = _make_not_found_result()
    ctx = ContextBuilder.from_search_result(result, Intent.SEARCH_ANIME, _profile_full())

    _check("ctx.found is False",   not ctx.found)
    _check("ctx.anime is None",    ctx.anime is None)
    _check("ctx.query preserved",  ctx.query == "xyzzy9999")


def test_build_user_only() -> None:
    _section("A4 — build_user_only() (no anime context)")
    ctx = ContextBuilder.build_user_only(
        intent=Intent.RECOMMENDATIONS,
        user_profile=_profile_full(),
        query="recommend me a romance anime",
    )

    _check("ctx.found is False",   not ctx.found)
    _check("ctx.anime is None",    ctx.anime is None)
    _check("user.nickname set",    ctx.user.nickname == "Karan")
    _check("user.language set",    ctx.user.language == "Tenglish")
    _check("query preserved",      ctx.query == "recommend me a romance anime")


def test_to_text_format() -> None:
    _section("A5 — to_text() format and structure")

    result = _make_anilist_result()
    ctx    = ContextBuilder.from_search_result(result, Intent.GET_DETAILS, _profile_full())
    text   = ContextBuilder.to_text(ctx)

    print()
    print("── Generated context block ──")
    print(text)
    print("── End of block ──")
    print()

    # Structure checks
    _check("Has header marker",       "=== Ani Zeo Context ===" in text)
    _check("Has footer marker",       "=======================" in text or "=== End" in text.replace("=== Ani Zeo Context ===", ""))

    # User section
    _check("Has [User] section",      "[User]" in text)
    _check("Has Nickname field",      "Nickname:" in text)
    _check("Has Language field",      "Language:" in text)
    _check("Has Intent field",        "Intent:" in text)

    # Anime section
    _check("Has [Anime: ...] section", "[Anime:" in text)
    _check("Has English title",       "English:" in text)
    _check("Has Romaji title",        "Romaji:" in text)
    _check("Has Native title",        "Native:" in text)
    _check("Has Status field",        "Status:" in text)
    _check("Has Episodes field",      "Episodes:" in text)
    _check("Has Rating field",        "Rating:" in text)
    _check("Has Season field",        "Season:" in text)
    _check("Has Studio field",        "Studio:" in text)
    _check("Has Genres field",        "Genres:" in text)
    _check("Has Streaming field",     "Streaming:" in text)
    _check("Has Trailer field",       "Trailer:" in text)
    _check("Has Related field",       "Related:" in text)
    _check("Has Synopsis field",      "Synopsis:" in text)
    _check("Has Data source field",   "Data:" in text)

    # No raw API artefacts
    _check("No 'cover_url' in output",  "cover_url"  not in text)
    _check("No 'mal_id' in output",     "mal_id"     not in text)
    _check("No 'anilist' raw source",   '"anilist"'  not in text)
    _check("No 'not_found' raw source", '"not_found"' not in text)
    _check("No JSON braces in output",  "{" not in text and "}" not in text,
           "clean text, no JSON")

    # Rating formatted correctly
    _check("Rating shows '9.0/10'",     "9.0/10" in text)


def test_empty_values_omitted() -> None:
    _section("A6 — Empty values are omitted from to_text() output")

    # Result with minimal fields
    sparse = AnimeSearchResult(
        found=True,
        query="some anime",
        source="jikan",
        title_english="Some Anime",
        # No romaji, no native, no synopsis, no genres, no streaming, no trailer
    )
    ctx  = ContextBuilder.from_search_result(sparse, None, {})
    text = ContextBuilder.to_text(ctx)

    print()
    print("── Sparse context block ──")
    print(text)
    print()

    _check("No 'Romaji:' when absent",    "Romaji:"    not in text)
    _check("No 'Native:' when absent",    "Native:"    not in text)
    _check("No 'Synopsis:' when absent",  "Synopsis:"  not in text)
    _check("No 'Genres:' when absent",    "Genres:"    not in text)
    _check("No 'Streaming:' when absent", "Streaming:" not in text)
    _check("No 'Trailer:' when absent",   "Trailer:"   not in text)
    _check("No 'User' section when no profile",
           "[User]" not in text,
           "no nickname/language → section absent")


def test_source_agnostic() -> None:
    _section("A7 — Source-agnostic: AniList and Jikan produce same structure")

    al_result   = _make_anilist_result()
    jk_result   = _make_jikan_result()
    profile     = _profile_full()

    al_ctx = ContextBuilder.from_search_result(al_result, Intent.SEARCH_ANIME, profile)
    jk_ctx = ContextBuilder.from_search_result(jk_result, Intent.SEARCH_ANIME, profile)

    al_text = ContextBuilder.to_text(al_ctx)
    jk_text = ContextBuilder.to_text(jk_ctx)

    # Both should have the same field labels — only data_source line differs
    def _field_labels(text: str) -> list[str]:
        labels = []
        for line in text.splitlines():
            stripped = line.strip()
            if ":" in stripped:
                labels.append(stripped.split(":")[0].strip())
        return labels

    al_labels = _field_labels(al_text)
    jk_labels = _field_labels(jk_text)

    _check("Same field labels regardless of source", al_labels == jk_labels,
           f"AniList fields: {al_labels} | Jikan fields: {jk_labels}")
    _check("AniList shows 'AniList' data source",  "AniList"     in al_text)
    _check("Jikan shows 'MAL (Jikan)' data source", "MAL (Jikan)" in jk_text)
    _check("'anilist' raw value never appears in output", "\"anilist\"" not in al_text)
    _check("'jikan'   raw value never appears in output", "\"jikan\""   not in jk_text)

    # Not-found path
    nf_ctx  = ContextBuilder.from_search_result(_make_not_found_result(), None, {})
    nf_text = ContextBuilder.to_text(nf_ctx)
    _check("Not-found includes honest note",      "No anime data found" in nf_text)
    _check("Not-found includes anti-hallucination warning",
           "hallucinate" in nf_text.lower())

    # Empty context → empty string
    empty_ctx = AIContext(user=UserContext())
    empty_text = ContextBuilder.to_text(empty_ctx)
    _check("Fully empty AIContext → empty string", empty_text == "")


# ═══════════════════════════════════════════════════════════════════════════════
# Part B — Integration test (real API call)
# ═══════════════════════════════════════════════════════════════════════════════

async def test_live_pipeline() -> None:
    _section("B1 — Live pipeline: search → context → to_text()")
    print("  Calling AniList for 'Demon Slayer'...")

    from services.anime_search import AnimeSearchService

    service = AnimeSearchService()   # fresh instance (isolated cache)
    result  = await service.search("Demon Slayer")

    profile = {"nickname": "Tanjiro_Fan", "language": "English"}
    ctx     = ContextBuilder.from_search_result(result, Intent.SEARCH_ANIME, profile)
    text    = ContextBuilder.to_text(ctx)

    print()
    print("── Live context block for 'Demon Slayer' ──")
    print(text)
    print()

    _check("Live result found",           result.found)
    _check("ctx.found is True",           ctx.found)
    _check("ctx.anime is not None",       ctx.anime is not None)
    _check("to_text() non-empty",         bool(text.strip()))
    _check("Has [Anime: ...] header",     "[Anime:" in text)
    _check("Has Rating field",            "Rating:" in text)
    _check("No raw JSON in output",       "{" not in text)
    _check("Source is readable label",
           "AniList" in text or "MAL" in text,
           "never raw 'anilist'/'jikan'")

    if ctx.anime:
        _check("raw score absent from AnimeContext",
               not hasattr(ctx.anime, "score"))
        _check("cover_url absent from AnimeContext",
               not hasattr(ctx.anime, "cover_url"))
        _check("popularity absent from AnimeContext",
               not hasattr(ctx.anime, "popularity"))
        _check("AnimeContext.rating is formatted string",
               ctx.anime.rating is None or "/" in ctx.anime.rating)


# ═══════════════════════════════════════════════════════════════════════════════
# Runner
# ═══════════════════════════════════════════════════════════════════════════════

async def _run_all() -> int:
    print()
    print("=" * _W)
    print("  Ani Zeo — Context Builder Test")
    print("=" * _W)
    print("  No Telegram, no bot, no AI calls — pure service layer.")

    # Part A: unit tests (no network)
    test_should_search()
    test_from_search_result()
    test_not_found_result()
    test_build_user_only()
    test_to_text_format()
    test_empty_values_omitted()
    test_source_agnostic()

    # Part B: live integration test
    await test_live_pipeline()

    # Summary
    _section("Summary")
    passed = sum(1 for _, ok, _ in _results if ok)
    failed = sum(1 for _, ok, _ in _results if not ok)

    for label, ok, note in _results:
        mark = "✓" if ok else "✗"
        suffix = f"  ({note})" if note else ""
        print(f"  {mark}  {label}{suffix}")

    print()
    total = passed + failed
    if failed:
        print(f"  {passed}/{total} passed  |  {failed} FAILED ✗")
    else:
        print(f"  {passed}/{total} passed — all tests passed ✓")

    return failed


def main() -> None:
    failures = asyncio.run(_run_all())
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
