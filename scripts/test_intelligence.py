"""
Test suite for the Anime Intelligence Core.

Runs offline (alias/resolve) tests synchronously and live API tests
(franchise manifest, continuation plan) asynchronously.

Usage:
    python scripts/test_intelligence.py
"""
from __future__ import annotations

import asyncio
import sys
import os

# Allow running from project root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.anime_intelligence import (
    AnimeResolver,
    intelligence_service,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

def _ok(label: str, got, expected=None) -> bool:
    if expected is not None:
        passed = got == expected
        status = "✅" if passed else "❌"
        print(f"  {status} {label}: got={got!r} expected={expected!r}")
        return passed
    else:
        print(f"  ℹ  {label}: {got!r}")
        return True


def _section(title: str) -> None:
    print(f"\n{'─'*60}")
    print(f"  {title}")
    print(f"{'─'*60}")


# ── Offline: alias resolution ──────────────────────────────────────────────────

def test_resolver() -> int:
    _section("1. AnimeResolver — alias & abbreviation")
    resolver = AnimeResolver()
    failures = 0

    cases: list[tuple[str, str | None]] = [
        # Dragon Ball family
        ("dragonball",         "Dragon Ball"),
        ("dragon balls",       "Dragon Ball"),
        ("dbz",                "Dragon Ball Z"),
        ("dragon-ball",        "Dragon Ball"),
        ("Dragon Ball Z",      "Dragon Ball Z"),   # casing

        # Jujutsu Kaisen
        ("JJK",                "Jujutsu Kaisen"),
        ("jjk",                "Jujutsu Kaisen"),
        ("Jujutsu Kaisen 0",   "Jujutsu Kaisen 0"),
        ("jjk0",               "Jujutsu Kaisen 0"),

        # Dr. Stone (alias)
        ("Dr. Stone",          "Dr. Stone"),
        ("dr stone",           "Dr. Stone"),
        ("doctor stone",       "Dr. Stone"),

        # Other aliases
        ("aot",                "Attack on Titan"),
        ("snk",                "Attack on Titan"),
        ("op",                 "One Piece"),
        ("fmab",               "Fullmetal Alchemist: Brotherhood"),
        ("mha",                "My Hero Academia"),
        ("hxh",                "Hunter x Hunter"),
        ("kny",                "Demon Slayer"),
        ("frieren",            "Frieren: Beyond Journey's End"),
        ("frieren beyond journey", "Frieren: Beyond Journey's End"),

        # Ambiguous — ds alone → ambiguous (None)
        ("ds",                 None),

        # Pass-through titles (no alias → returned as-is)
        ("Naruto",             "Naruto"),
        ("One Piece",          "One Piece"),
    ]

    for query, expected_title in cases:
        result = resolver.resolve(query)
        if expected_title is None:
            # Expect ambiguous
            ok = result.ambiguous
            status = "✅" if ok else "❌"
            print(f"  {status} resolve({query!r}) → ambiguous={result.ambiguous} "
                  f"clarification={result.clarification!r}")
            if not ok:
                failures += 1
        else:
            ok = result.resolved_title == expected_title
            status = "✅" if ok else "❌"
            print(f"  {status} resolve({query!r}) → {result.resolved_title!r} "
                  f"(was_alias={result.was_alias})")
            if not ok:
                failures += 1

    return failures


def test_title_extraction() -> int:
    _section("2. AnimeResolver — title extraction (strip intent words)")
    resolver = AnimeResolver()
    failures = 0

    cases = [
        ("Naruto watch order",          "Naruto"),
        ("dbz filler skipped order",    "dbz"),
        ("jjk manga continuation",      "jjk"),
        ("Attack on Titan canon only",  "Attack on Titan"),
        ("One Piece read order",        "One Piece"),
        ("Bleach where to start",       "Bleach"),
        ("Naruto manga after anime",    "Naruto"),
    ]

    for query, expected in cases:
        resolver_obj = AnimeResolver()
        got = resolver_obj.extract_title(query)
        ok = got.strip().lower() == expected.strip().lower()
        status = "✅" if ok else "❌"
        print(f"  {status} extract_title({query!r}) → {got!r}")
        if not ok:
            failures += 1

    return failures


def test_misspelled() -> int:
    _section("3. AnimeResolver — misspelled inputs (pass-through to AniList fuzzy)")
    resolver = AnimeResolver()

    # These do NOT hit the alias table — they pass through unchanged.
    # AniList's fuzzy engine handles them at search time.
    misspelled = [
        "Narruto",            # Naruto
        "Jujutso Kaisen",     # Jujutsu Kaisen
        "Atack on Titan",     # Attack on Titan
        "Dragonball Zee",     # Dragon Ball Z
        "Bleech",             # Bleach
    ]

    print("  (These pass through unchanged — AniList fuzzy handles typos)")
    for query in misspelled:
        result = resolver.resolve(query)
        print(f"  ℹ  {query!r} → pass-through: {result.resolved_title!r} "
              f"(was_alias={result.was_alias})")

    return 0  # always pass — these are informational


def test_ambiguous() -> int:
    _section("4. Ambiguous input — 'ds'")
    resolver = AnimeResolver()
    failures = 0

    # Plain "ds" → ambiguous
    r = resolver.resolve("ds")
    ok1 = r.ambiguous and r.resolved_title is None
    status = "✅" if ok1 else "❌"
    print(f"  {status} 'ds' alone → ambiguous={r.ambiguous}, "
          f"clarification={r.clarification!r}")
    if not ok1:
        failures += 1

    # "ds stone" → Dr. Stone
    r2 = resolver.resolve("ds stone")
    ok2 = r2.resolved_title == "Dr. Stone"
    status = "✅" if ok2 else "❌"
    print(f"  {status} 'ds stone' → {r2.resolved_title!r} (disambiguated)")
    if not ok2:
        failures += 1

    # "ds demon" → Demon Slayer
    r3 = resolver.resolve("ds demon")
    ok3 = r3.resolved_title == "Demon Slayer"
    status = "✅" if ok3 else "❌"
    print(f"  {status} 'ds demon' → {r3.resolved_title!r} (disambiguated)")
    if not ok3:
        failures += 1

    return failures


# ── Live API: franchise manifest + continuation plan ──────────────────────────

async def test_franchise(query: str, order_type: str = "watch_order") -> None:
    _section(f"LIVE: '{query}' — {order_type}")
    result = await intelligence_service.resolve_and_plan(query, order_type)

    print(f"  resolved_title : {result.resolved_title!r}")
    print(f"  ambiguous      : {result.ambiguous}")
    if result.clarification:
        print(f"  clarification  : {result.clarification}")

    if result.franchise:
        f = result.franchise
        print(f"  franchise      : {f.canonical_title!r} (found={f.found})")
        if f.root:
            print(f"    root         : {f.root.title!r} | {f.root.fmt} | "
                  f"{f.root.episodes} eps | {f.root.status}")
        print(f"    relations    : {len(f.entries)} entries")
        for e in f.entries[:8]:
            print(f"      [{e.relation:16}] {e.title!r} — {e.fmt} | "
                  f"{e.episodes or '?'} eps | {e.year or '?'}")
        if f.source_material:
            print(f"    source       : {f.source_material}")
    else:
        print("  franchise      : None")

    if result.continuation:
        c = result.continuation
        print(f"  order_type     : {c.order_type}")
        if c.starting_chapter:
            print(f"  start_chapter  : {c.starting_chapter}")
        if c.manga_note:
            print(f"  manga_note     : {c.manga_note}")
        if c.general_note:
            print(f"  general_note   : {c.general_note}")
        print(f"  sequence ({len(c.sequence)} items):")
        for item in c.sequence[:10]:
            opt = " [optional]" if item.is_optional else ""
            filler = f" | filler: {item.filler_ranges}" if item.filler_ranges else ""
            print(f"    {item.order:2}. {item.title!r} — {item.fmt}{opt}{filler}")
            if item.notes:
                print(f"        notes: {item.notes}")
        if len(c.sequence) > 10:
            print(f"    ... (+{len(c.sequence)-10} more)")


async def run_live_tests() -> None:
    live_cases = [
        # Dragon Ball variants
        ("dragonball",                    "watch_order"),
        ("dragon balls",                  "watch_order"),
        ("dbz",                           "watch_order"),
        ("dragon-ball",                   "watch_order"),

        # Jujutsu Kaisen
        ("JJK",                           "watch_order"),
        ("Jujutsu Kaisen 0",              "watch_order"),

        # Dr. Stone
        ("Dr. Stone",                     "watch_order"),

        # Naruto — watch order
        ("Naruto watch order",            "watch_order"),

        # Naruto — manga continuation
        ("Naruto manga continuation",     "manga_continuation"),

        # Ambiguous: ds (should return clarification immediately, no API call)
        ("ds",                            "watch_order"),

        # Misspelled (one per alias group) — AniList fuzzy should rescue these
        ("Narruto watch order",           "watch_order"),
        ("Jujutso Kaisen",                "watch_order"),
        ("dragonbal",                     "watch_order"),
        ("Atack on Titan watch order",    "watch_order"),
    ]

    for query, order_type in live_cases:
        try:
            await test_franchise(query, order_type)
        except Exception as exc:
            print(f"  ❌ Exception: {exc}")


# ── Runner ─────────────────────────────────────────────────────────────────────

async def main() -> None:
    print("\n" + "=" * 60)
    print("  Anime Intelligence Core — Test Suite")
    print("=" * 60)

    # Offline tests (no API)
    offline_failures = 0
    offline_failures += test_resolver()
    offline_failures += test_title_extraction()
    offline_failures += test_misspelled()
    offline_failures += test_ambiguous()

    print(f"\n{'='*60}")
    print(f"  Offline tests: {'✅ All passed' if offline_failures == 0 else f'❌ {offline_failures} failed'}")
    print(f"{'='*60}")

    # Live API tests
    print("\n" + "=" * 60)
    print("  Live API Tests (requires network)")
    print("=" * 60)
    await run_live_tests()

    print("\n" + "=" * 60)
    print("  Done.")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    asyncio.run(main())
