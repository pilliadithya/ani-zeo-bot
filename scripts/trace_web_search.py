"""
trace_web_search.py — complete runtime flow trace for a web-search query.

Shows every step of the pipeline for:
  "What are the latest anime news today?"

including intent classification, KnowledgeRouter decisions, provider calls,
the exact context block sent to Gemini, and Gemini's final response.

Run:
    python scripts/trace_web_search.py
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# ── Logging: INFO so all routing steps are visible ────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="  [LOG] %(name)s | %(message)s",
    stream=sys.stdout,
)
# Suppress noisy third-party logs
for _noisy in ("httpx", "httpcore", "telegram", "google"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

# ── Imports (after path is set) ───────────────────────────────────────────────
from config.ai_config import ENABLE_WEB_SEARCH, WEB_SEARCH_PROVIDER
from services.intent import IntentClassifier
from services.knowledge_router import knowledge_router
from services.context_builder import ContextBuilder
from services.web_search import web_search_service, list_providers
from ai.router import AIRouter
from ai.prompts import build_system_prompt

QUERY   = "What are the latest anime news today?"
DIV     = "─" * 72
SECTION = "━" * 72


def _header(n: int, title: str) -> None:
    print(f"\n{SECTION}")
    print(f"  {n}  {title}")
    print(SECTION)


async def trace() -> None:
    print(f"\n{SECTION}")
    print("  ARI ZEO — WEB SEARCH PIPELINE TRACE")
    print(f"  Query: {QUERY!r}")
    print(SECTION)

    # ── ① Config state ────────────────────────────────────────────────────────
    _header("①", "CONFIG")
    brave_key = os.environ.get("BRAVE_API_KEY")
    print(f"  ENABLE_WEB_SEARCH        = {ENABLE_WEB_SEARCH}")
    print(f"  WEB_SEARCH_PROVIDER      = {WEB_SEARCH_PROVIDER!r}")
    print(f"  Registered providers     = {list_providers()}")
    print(f"  Active provider name     = {web_search_service.active_provider_name()!r}")
    print(f"  Provider is_configured() = {web_search_service.is_configured()}")
    print(f"  BRAVE_API_KEY            = {'✓ set' if brave_key else '✗ NOT SET — results will be empty'}")

    # ── ② Intent classification ───────────────────────────────────────────────
    _header("②", "INTENT CLASSIFICATION")
    clf = IntentClassifier()
    intent, confidence = clf.classify_with_confidence(QUERY)
    print(f"  intent     = {intent.name}")
    print(f"  label      = {clf.display_name(intent)!r}")
    print(f"  confidence = {confidence:.1f}")

    # ── ③ KnowledgeRouter (with live INFO logs) ───────────────────────────────
    _header("③", "KNOWLEDGE ROUTER  (routing logs follow)")
    print()
    ai_ctx = await knowledge_router.route(QUERY, intent, {})
    print()
    print(f"  ── router result ──")
    print(f"  found        = {ai_ctx.found}")
    print(f"  news_items   = {len(ai_ctx.news_items)}")
    print(f"  web_results  = {len(ai_ctx.web_results)}")
    print(f"  web_mode     = {ai_ctx.web_search_mode}")
    if ai_ctx.web_results:
        print(f"\n  Web results injected:")
        for i, r in enumerate(ai_ctx.web_results, 1):
            print(f"    {i}. [{r.source}]  {r.title}")
            print(f"       {r.snippet[:120]}…" if len(r.snippet) > 120 else f"       {r.snippet}")

    # ── ④ Context block sent to Gemini ────────────────────────────────────────
    _header("④", "CONTEXT BLOCK SENT TO GEMINI")
    context_block = ContextBuilder.to_text(ai_ctx)
    system_prompt = build_system_prompt() + context_block

    print(f"  system_prompt total length : {len(system_prompt)} chars")
    print(f"  context_block length       : {len(context_block)} chars")
    print()
    if context_block:
        print(context_block)
    else:
        print("  [no context block — bare system prompt only]")

    # ── ⑤ Gemini response ─────────────────────────────────────────────────────
    _header("⑤", "GEMINI RESPONSE")
    print()
    try:
        ai_router = AIRouter()
        response  = await ai_router.route(
            prompt  = QUERY,
            system  = system_prompt,
            history = None,
        )
        if response.success:
            print(f"  provider = {response.provider}")
            print(f"  latency  = {response.latency_ms:.0f} ms")
            print()
            print(DIV)
            print(response.text)
            print(DIV)
        else:
            print(f"  ✗ All providers failed: {response.error}")
    except Exception as exc:
        print(f"  ✗ AIRouter raised: {exc}")

    print(f"\n{SECTION}")
    print("  TRACE COMPLETE")
    print(SECTION)


if __name__ == "__main__":
    asyncio.run(trace())
