"""
Anime Search Service test — scripts/test_anime_search.py

Run from the project root:
    python scripts/test_anime_search.py

Tests the AnimeSearchService with real API calls.
No Telegram, no bot — pure service layer.

Test cases:
  1. Naruto              — popular title, AniList primary expected
  2. One Piece           — long-running series
  3. Solo Levelling      — British spelling / alternative romanisation
  4. Dandadan            — recent 2024 title
  5. Narutoo             — intentional misspelling (fuzzy fallback test)
  6. Naruto (again)      — cache hit test
  7. xyzzy_fake_9999     — guaranteed not-found / structured error test
"""
from __future__ import annotations

import asyncio
import sys
import os
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.anime_search import AnimeSearchResult, AnimeSearchService

# ── Formatting helpers ─────────────────────────────────────────────────────────

_W = 110   # total line width

def _hr(char: str = "─") -> str:
    return char * _W

def _banner(text: str) -> None:
    print()
    print(_hr("═"))
    print(f"  {text}")
    print(_hr("═"))

def _section(label: str) -> None:
    print()
    print(f"  ── {label} {'─' * (_W - len(label) - 6)}")

def _field(name: str, value, indent: int = 4) -> None:
    pad = " " * indent
    val = str(value) if value is not None else "N/A"
    if len(val) > 80:
        val = val[:77] + "…"
    print(f"{pad}{name:<22} {val}")

def _result_block(label: str, result: AnimeSearchResult, elapsed_ms: float) -> None:
    status_icon = "✓" if result.found else "✗"
    cache_tag   = " [CACHE HIT]" if result.cached else ""
    source_tag  = f"[{result.source.upper()}]"

    print()
    print(_hr())
    print(f"  {status_icon}  {label}{cache_tag}  {source_tag}  ({elapsed_ms:.0f} ms)")
    print(_hr())

    if not result.found:
        print(f"    NOT FOUND — query={result.query!r}")
        print(f"    source={result.source}")
        return

    _field("Display title",    result.display_title)
    _field("Romaji",           result.title_romaji)
    _field("English",          result.title_english)
    _field("Native",           result.title_native)
    _field("Score",            result.score_display)
    _field("Rank",             result.rank)
    _field("Popularity",       f"#{result.popularity:,}" if result.popularity else None)
    _field("Episodes",         result.episodes)
    _field("Status",           result.status)
    _field("Season",           result.season)
    _field("Source material",  result.source_material)
    _field("Duration",         result.duration)
    _field("Studios",          ", ".join(result.studios) or None)
    _field("Genres",           ", ".join(result.genres[:6]) or None)
    _field("Streaming",        ", ".join(result.streaming_platforms) or None)
    _field("Trailer",          result.trailer_url)
    _field("Cover URL",        result.cover_url)

    if result.synopsis:
        print(f"    {'Synopsis':<22}", end="")
        words = result.synopsis.replace("\n", " ").split()
        line, col = [], 26
        for w in words:
            if col + len(w) + 1 > _W:
                print(" ".join(line))
                print(" " * 26, end="")
                line, col = [w], 26 + len(w)
            else:
                line.append(w)
                col += len(w) + 1
        if line:
            print(" ".join(line))

    if result.relations:
        rels = " | ".join(
            f"{'⬅ Prequel' if r['type'] == 'PREQUEL' else '➡ Sequel'}: {r['title']}"
            for r in result.relations[:3]
        )
        _field("Relations", rels)


# ── Test runner ────────────────────────────────────────────────────────────────

async def run_tests() -> int:
    """Run all test cases. Returns number of failures."""

    service = AnimeSearchService()   # fresh instance with its own cache for isolation

    test_cases: list[tuple[str, str, str]] = [
        # (query,           label,                  expected_outcome)
        ("Naruto",          "Naruto",               "found"),
        ("One Piece",       "One Piece",            "found"),
        ("Solo Levelling",  "Solo Levelling",       "found"),
        ("Dandadan",        "Dandadan",             "found"),
        ("Narutoo",         "Narutoo (misspelt)",   "found"),
        ("Naruto",          "Naruto (cache test)",  "found_cached"),
        ("xyzzy_fake_9999", "Guaranteed not-found", "not_found"),
    ]

    _banner("Ani Zeo — Anime Search Service Test")
    print(f"  Running {len(test_cases)} test cases with real API calls.")
    print(f"  Cache size before run: {service.cache_size()}")

    passed = failed = 0
    summary: list[str] = []

    for query, label, expected in test_cases:
        t0     = time.monotonic()
        result = await service.search(query)
        ms     = (time.monotonic() - t0) * 1000

        _result_block(label, result, ms)

        # ── Assertion logic ───────────────────────────────────────────────────
        if expected == "found":
            ok = result.found and not result.cached
        elif expected == "found_cached":
            ok = result.found and result.cached
        elif expected == "not_found":
            ok = not result.found and result.source == "not_found"
        else:
            ok = False

        mark = "PASS ✓" if ok else "FAIL ✗"
        print(f"    → {mark}  (expected={expected!r})")
        summary.append(f"  {'✓' if ok else '✗'}  {label:<30} expected={expected!r}")

        if ok:
            passed += 1
        else:
            failed += 1

        # Small delay between live API calls to be polite to rate limits
        if not result.cached and query != test_cases[-1][0]:
            await asyncio.sleep(0.5)

    # ── Summary ───────────────────────────────────────────────────────────────
    _banner("Summary")
    for line in summary:
        print(line)
    print()
    print(f"  Results: {passed}/{passed + failed} passed", end="")
    if failed:
        print(f"  |  {failed} FAILED ✗")
    else:
        print("  — all tests passed ✓")
    print(f"  Cache size after run: {service.cache_size()}")

    # ── Cache behaviour note ──────────────────────────────────────────────────
    _section("Cache behaviour")
    print("  Same query run twice: second call should show [CACHE HIT] above.")
    print("  Not-found results cached for 10 min (shorter TTL — user may fix typo).")
    print("  Positive results cached for 1 hour.")

    return failed


def main() -> None:
    failures = asyncio.run(run_tests())
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
