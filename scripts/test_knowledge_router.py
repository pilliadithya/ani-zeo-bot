"""
test_knowledge_router.py — Sprint A: KnowledgeRouter unit tests.

Run:
    python scripts/test_knowledge_router.py

Tests:
  1. _decide: every Intent maps to the correct primary source
  2. Registry: register/dedup/priority-sort
  3. Live / supplement / conversational intent sets are mutually appropriate
  4. _refine_query: strips filler, appends qualifiers
  5. from_web_result + to_text: web section renders correctly
  6. Feature flag: ENABLE_WEB_SEARCH=False → web search returns []
  7. New intents: WEB_SEARCH and GENERAL_KNOWLEDGE are classified correctly
"""
from __future__ import annotations

import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# ── helpers ───────────────────────────────────────────────────────────────────

PASS = "\033[32m✓\033[0m"
FAIL = "\033[31m✗\033[0m"
_failures: list[str] = []

def ok(label: str) -> None:
    print(f"  {PASS} {label}")

def fail(label: str, detail: str = "") -> None:
    msg = f"{label}: {detail}" if detail else label
    print(f"  {FAIL} {msg}")
    _failures.append(msg)

def section(title: str) -> None:
    print(f"\n── {title} {'─' * (60 - len(title))}")

# ── imports ───────────────────────────────────────────────────────────────────

from services.intent import Intent, IntentClassifier
from services.knowledge_router import (
    KnowledgeRouter, KnowledgeSourceSpec,
    _LIVE_PRIMARY_INTENTS, _LIVE_SUPPLEMENT_INTENTS,
    _is_conversational, _refine_query, knowledge_router,
)
from services.context_builder import AIContext, ContextBuilder
from services.web_search import WebSearchResult, web_search_service
from config.ai_config import ENABLE_KNOWLEDGE_ROUTER, ENABLE_WEB_SEARCH

# ─────────────────────────────────────────────────────────────────────────────
# Test 1 — Config flags
# ─────────────────────────────────────────────────────────────────────────────
section("1. Config flags")

if ENABLE_KNOWLEDGE_ROUTER:
    ok("ENABLE_KNOWLEDGE_ROUTER = True")
else:
    fail("ENABLE_KNOWLEDGE_ROUTER should default True", str(ENABLE_KNOWLEDGE_ROUTER))

ok(f"ENABLE_WEB_SEARCH = {ENABLE_WEB_SEARCH}  (False by default — needs SERPAPI_KEY)")

# ─────────────────────────────────────────────────────────────────────────────
# Test 2 — Default registry
# ─────────────────────────────────────────────────────────────────────────────
section("2. Default source registry")

keys = [s.key for s in knowledge_router._registry]
for expected in ("anime_intelligence", "anime_search", "news", "web_search_primary"):
    if expected in keys:
        ok(f"Source '{expected}' registered")
    else:
        fail(f"Source '{expected}' missing from registry", f"found: {keys}")

# Priority ordering
priorities = [s.priority for s in knowledge_router._registry]
if priorities == sorted(priorities):
    ok("Registry sorted by priority")
else:
    fail("Registry not sorted", str(list(zip(keys, priorities))))

# ─────────────────────────────────────────────────────────────────────────────
# Test 3 — Register / dedup / re-sort
# ─────────────────────────────────────────────────────────────────────────────
section("3. Register() idempotency and dedup")

before = len(knowledge_router._registry)
dummy_spec = KnowledgeSourceSpec(
    key="__test__", priority=99, is_live=False,
    intents=frozenset({Intent.UNKNOWN}),
    handler=lambda t, p, i: None,
)
knowledge_router.register(dummy_spec)
knowledge_router.register(dummy_spec)  # re-register same key
after = len(knowledge_router._registry)

if after == before + 1:
    ok(f"Dedup: double-register kept registry at {after} (not {before + 2})")
else:
    fail("Dedup failed", f"before={before}, after={after}, expected={before + 1}")

# Cleanup
knowledge_router._registry = [s for s in knowledge_router._registry if s.key != "__test__"]
ok("Cleanup: test source removed")

# ─────────────────────────────────────────────────────────────────────────────
# Test 4 — Intent → source mapping
# ─────────────────────────────────────────────────────────────────────────────
section("4. Intent → source category mapping")

# Internal intents (should NOT be live-primary)
internal_intents = [
    Intent.WATCH_ORDER, Intent.MANGA_CONTINUATION,
    Intent.SEARCH_ANIME, Intent.GET_DETAILS,
    Intent.CHARACTER_LOOKUP, Intent.DUB_INFO,
    Intent.LORE_QUESTION, Intent.EXPLANATION, Intent.OPEN_QUESTION,
]
for intent in internal_intents:
    if intent not in _LIVE_PRIMARY_INTENTS:
        ok(f"{intent.name} is internal (not live-primary)")
    else:
        fail(f"{intent.name} should be internal", "found in _LIVE_PRIMARY_INTENTS")

# Live-supplement intents
supplement_intents = [Intent.ANIME_NEWS, Intent.TRENDING]
for intent in supplement_intents:
    if intent in _LIVE_SUPPLEMENT_INTENTS:
        ok(f"{intent.name} is live-supplement")
    else:
        fail(f"{intent.name} should be live-supplement")

# Live-primary intents (Sprint A)
live_primary_intents = [Intent.WEB_SEARCH, Intent.GENERAL_KNOWLEDGE]
for intent in live_primary_intents:
    if intent in _LIVE_PRIMARY_INTENTS:
        ok(f"{intent.name} is live-primary")
    else:
        fail(f"{intent.name} should be live-primary")

# Conversational intents (never web)
conv_intents = [Intent.GREETING, Intent.HELP, Intent.WATCHLIST_ACTION, Intent.UNKNOWN]
for intent in conv_intents:
    if _is_conversational(intent):
        ok(f"{intent.name} is conversational (no web)")
    else:
        fail(f"{intent.name} should be conversational")

# ─────────────────────────────────────────────────────────────────────────────
# Test 5 — _refine_query
# ─────────────────────────────────────────────────────────────────────────────
section("5. _refine_query: filler stripping + qualifier injection")

cases = [
    ("tell me what's happening with demon slayer", Intent.ANIME_NEWS,    "demon slayer"),
    ("search the web for bleach",                  Intent.WEB_SEARCH,    "bleach"),
    ("what is trending right now",                 Intent.TRENDING,      "trending anime"),
    ("when does SnK season 5 release",             Intent.GENERAL_KNOWLEDGE, "snk"),
]
for text, intent, must_contain in cases:
    result = _refine_query(text, intent)
    if must_contain.lower() in result.lower():
        ok(f"_refine_query({text!r:.35}) → {result!r}")
    else:
        fail(f"_refine_query missing '{must_contain}'", f"got: {result!r}")

if _refine_query("", Intent.ANIME_NEWS):
    ok("Empty query → non-empty fallback (uses original text or qualifier)")

# ─────────────────────────────────────────────────────────────────────────────
# Test 6 — AIContext web fields + from_web_result + to_text
# ─────────────────────────────────────────────────────────────────────────────
section("6. AIContext.web_results / web_search_mode + from_web_result + to_text")

sample_results = [
    WebSearchResult(
        title="Bleach TYBW Part 3 drops 2026",
        url="https://animenewsnetwork.com/bleach",
        snippet="Bleach Thousand-Year Blood War Part 3 is confirmed for late 2026 on Disney+.",
        source="animenewsnetwork.com",
        published_date="2026-07-15",
    ),
    WebSearchResult(
        title="Bleach manga vs anime comparison",
        url="https://cbr.com/bleach-manga",
        snippet="Here's how the manga compares to the new anime arc.",
        source="cbr.com",
        published_date=None,
    ),
]

ctx = ContextBuilder.from_web_result("bleach 2026", sample_results, {}, Intent.GENERAL_KNOWLEDGE)

if ctx.web_search_mode:
    ok("from_web_result: web_search_mode=True")
else:
    fail("from_web_result: web_search_mode should be True")

if ctx.web_results == sample_results:
    ok("from_web_result: web_results populated correctly")
else:
    fail("from_web_result: web_results mismatch")

if ctx.found:
    ok("from_web_result: found=True when results non-empty")
else:
    fail("from_web_result: found should be True with results")

txt = ContextBuilder.to_text(ctx)

for expected in ("Web Search Results", "supplemental", "animenewsnetwork.com", "Bleach TYBW"):
    if expected in txt:
        ok(f"to_text: contains {expected!r}")
    else:
        fail(f"to_text: missing {expected!r}", f"block:\n{txt[:500]}")

# No-results path
ctx_empty = ContextBuilder.from_web_result("something", [], {}, Intent.WEB_SEARCH)
txt_empty = ContextBuilder.to_text(ctx_empty)
if "live web search returned no results" in txt_empty.lower():
    ok("to_text: no-results path renders fallback note")
else:
    fail("to_text: missing no-results fallback note", txt_empty[:300])

# ─────────────────────────────────────────────────────────────────────────────
# Test 7 — ENABLE_WEB_SEARCH=False → search() returns []
# ─────────────────────────────────────────────────────────────────────────────
section("7. WebSearchService feature flag")

results_off = asyncio.run(web_search_service.search("naruto", intent_name="SEARCH_ANIME"))
if results_off == [] and not ENABLE_WEB_SEARCH:
    ok("ENABLE_WEB_SEARCH=False → search() returns [] immediately (zero overhead)")
elif ENABLE_WEB_SEARCH:
    ok(f"ENABLE_WEB_SEARCH=True — live call would fire (returned {len(results_off)} results)")
else:
    fail("WebSearchService did not respect ENABLE_WEB_SEARCH=False flag")

# ─────────────────────────────────────────────────────────────────────────────
# Test 8 — New intents are classified by IntentClassifier
# ─────────────────────────────────────────────────────────────────────────────
section("8. New intents — IntentClassifier")

clf = IntentClassifier()
new_intent_cases = [
    ("search the web for Jujutsu Kaisen season 3",    Intent.WEB_SEARCH),
    ("when does attack on titan final season release", Intent.GENERAL_KNOWLEDGE),
    ("latest news on bleach",                          Intent.ANIME_NEWS),
    ("JJK season 3 release date confirmed",            Intent.GENERAL_KNOWLEDGE),
    ("find online info about vinland saga",            Intent.WEB_SEARCH),
]
for text, expected in new_intent_cases:
    result, _ = clf.classify_with_confidence(text)
    if result == expected:
        ok(f"classify({text!r:.45}) → {expected.name}")
    else:
        fail(f"classify({text!r:.45})", f"expected={expected.name}, got={result.name}")

# ─────────────────────────────────────────────────────────────────────────────
# Summary
# ─────────────────────────────────────────────────────────────────────────────
print()
if not _failures:
    print(f"\033[32m✓ All tests passed.\033[0m")
else:
    print(f"\033[31m✗ {len(_failures)} test(s) failed:\033[0m")
    for f in _failures:
        print(f"    • {f}")
    sys.exit(1)
