"""
KnowledgeRouter — intent-driven, priority-based knowledge source dispatcher.

Replaces the inline if/elif chain in message_handler._build_context_for_route()
with a clean pluggable registry.  New knowledge sources are registered via
KnowledgeRouter.register() without modifying any routing logic.

Architecture
────────────
  KnowledgeSourceSpec  descriptor for one knowledge source
  KnowledgeRouter      dispatcher — owns the registry + executes sources

Priority rules (lower number = higher priority)
  0   Anime Intelligence   watch-order / manga continuation (internal, canonical)
  10  Anime Search         AniList / Jikan title lookup (internal, canonical)
  20  News Service         MAL RSS + AniList trending (live)
  50  Web Search           SerpAPI (live, supplemental)

Routing rules
  1. Internal sources (is_live=False) always run first for their handled intents.
  2. Live sources (is_live=True) run for live intents (news, trending, web-only queries).
  3. Web search is SUPPLEMENTAL for news/trending: it merges web_results into the
     context produced by the primary source rather than replacing it.
  4. Web search is PRIMARY for WEB_SEARCH / GENERAL_KNOWLEDGE intents (no internal source).
  5. If the primary source finds nothing (ai_ctx.found=False) and web search is
     enabled, web results are added as a supplement.

Backward compatibility
  This module is wired in message_handler.py behind ENABLE_KNOWLEDGE_ROUTER.
  Setting that flag to False restores the original inline routing instantly.

Usage
─────
    from services.knowledge_router import knowledge_router
    ai_ctx = await knowledge_router.route(text, intent, profile)
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Callable, Awaitable

from services.intent import Intent
from services.context_builder import ContextBuilder, AIContext
from services.web_search import web_search_service, WebSearchResult

logger = logging.getLogger(__name__)

# ── Intents that require live / web data as the primary source ────────────────
# These are never satisfied by internal (AniList/Jikan/intelligence) data alone.
_LIVE_PRIMARY_INTENTS: frozenset[Intent] = frozenset({
    Intent.WEB_SEARCH,
    Intent.GENERAL_KNOWLEDGE,
})

# ── Intents where web search supplements (not replaces) internal data ─────────
_LIVE_SUPPLEMENT_INTENTS: frozenset[Intent] = frozenset({
    Intent.ANIME_NEWS,
    Intent.TRENDING,
    Intent.UPCOMING,
})


# ── Source descriptor ─────────────────────────────────────────────────────────

@dataclass
class KnowledgeSourceSpec:
    """
    Descriptor for one pluggable knowledge source.

    To add a new source, create a KnowledgeSourceSpec and call
    KnowledgeRouter.register(spec).  The routing core never needs to change.

    Fields
    ──────
    key          Unique identifier for logging and deduplication.
    priority     Execution order within a role — lower runs first (0 = highest).
    is_live      True → external / live data (news, web).  False → internal DB.
    intents      Frozenset of Intent values this source handles.
                 Empty frozenset = handles ALL intents (catch-all).
    handler      Async callable: (text, profile, intent) → AIContext | None.
                 Must never raise; return None to signal "no data for this query".
    """
    key:      str
    priority: int
    is_live:  bool
    intents:  frozenset[Intent]
    handler:  Callable[[str, dict, Intent], Awaitable[AIContext | None]]


# ── Router ────────────────────────────────────────────────────────────────────

class KnowledgeRouter:
    """
    Intent-driven dispatcher over a registry of KnowledgeSourceSpec objects.

    Default sources are registered in __init__.  External code may call
    register() to plug in additional sources at any time before the first
    route() call (or live, for runtime-registered sources).

    The routing algorithm is fixed; only the registry changes.
    """

    def __init__(
        self,
        intelligence_service=None,
        search_service=None,
        news_service=None,
    ) -> None:
        self._registry: list[KnowledgeSourceSpec] = []
        self._register_defaults(intelligence_service, search_service, news_service)

    # ── Public API ─────────────────────────────────────────────────────────────

    def register(self, spec: KnowledgeSourceSpec) -> None:
        """
        Add a new knowledge source to the registry.

        Sources with the same key replace any previously registered spec
        with that key (idempotent re-registration).
        """
        self._registry = [s for s in self._registry if s.key != spec.key]
        self._registry.append(spec)
        self._registry.sort(key=lambda s: s.priority)
        logger.debug("KnowledgeRouter | registered source %r (priority=%d)", spec.key, spec.priority)

    async def route(
        self,
        text:    str,
        intent:  Intent,
        profile: dict,
    ) -> AIContext:
        """
        Route *text* through the appropriate knowledge sources for *intent*.

        Returns a fully-populated AIContext ready for ContextBuilder.to_text().
        Never raises — falls back to user-only context on any error.

        Priority rules applied here:
          1. Internal sources first (is_live=False).
          2. Live sources for live intents.
          3. Web search merged as supplement when enabled.
        """
        try:
            return await self._route(text, intent, profile)
        except Exception as exc:
            logger.error("KnowledgeRouter | unexpected error | intent=%s | %s", intent.name, exc)
            return ContextBuilder.build_user_only(intent, profile, text)

    # ── Routing core ───────────────────────────────────────────────────────────

    async def _route(self, text: str, intent: Intent, profile: dict) -> AIContext:
        is_live_primary     = intent in _LIVE_PRIMARY_INTENTS
        is_live_supplement  = intent in _LIVE_SUPPLEMENT_INTENTS

        logger.info(
            "KnowledgeRouter | route | intent=%s | live_primary=%s | live_supplement=%s | text=%r",
            intent.name, is_live_primary, is_live_supplement, text[:80],
        )

        # ── Step 1: run internal sources (never for live-primary intents) ──────
        ai_ctx: AIContext | None = None

        if not is_live_primary:
            ai_ctx = await self._run_internal(text, intent, profile)

        # ── Step 2: run live sources for live-primary intents ──────────────────
        if is_live_primary and ai_ctx is None:
            ai_ctx = await self._run_live_primary(text, intent, profile)

        # ── Step 3: fallback — user-only context (no source produced data) ─────
        if ai_ctx is None:
            ai_ctx = ContextBuilder.build_user_only(intent, profile, text)

        # ── Step 4: web search supplement ─────────────────────────────────────
        # Triggered when:
        #   a) intent is a live-supplement type (news / trending), OR
        #   b) internal source found nothing (ai_ctx.found=False), OR
        #   c) intent is live-primary (already routed through web, but merge anyway)
        should_supplement = (
            is_live_supplement
            or is_live_primary
            or (not ai_ctx.found and not _is_conversational(intent))
        )

        if should_supplement:
            web_results = await self._fetch_web(text, intent)
            if web_results:
                ai_ctx.web_results      = web_results
                ai_ctx.web_search_mode  = True
                logger.info(
                    "KnowledgeRouter | web supplement | intent=%s | %d results",
                    intent.name, len(web_results),
                )

        return ai_ctx

    # ── Internal execution helpers ─────────────────────────────────────────────

    async def _run_internal(self, text: str, intent: Intent, profile: dict) -> AIContext | None:
        """Run the highest-priority internal source that handles this intent."""
        for spec in self._registry:
            if spec.is_live:
                continue
            if spec.intents and intent not in spec.intents:
                continue
            logger.info(
                "KnowledgeRouter | trying internal source=%r | intent=%s",
                spec.key, intent.name,
            )
            result = await self._call_spec(spec, text, profile, intent)
            if result is not None:
                logger.info(
                    "KnowledgeRouter | source=%r produced context | found=%s",
                    spec.key, getattr(result, "found", "n/a"),
                )
                return result
        return None

    async def _run_live_primary(self, text: str, intent: Intent, profile: dict) -> AIContext | None:
        """Run live sources for intents that require live data as primary."""
        for spec in self._registry:
            if not spec.is_live:
                continue
            if spec.intents and intent not in spec.intents:
                continue
            logger.info(
                "KnowledgeRouter | trying live source=%r | intent=%s",
                spec.key, intent.name,
            )
            result = await self._call_spec(spec, text, profile, intent)
            if result is not None:
                logger.info(
                    "KnowledgeRouter | source=%r produced context | found=%s",
                    spec.key, getattr(result, "found", "n/a"),
                )
                return result
        return None

    async def _call_spec(
        self,
        spec:    KnowledgeSourceSpec,
        text:    str,
        profile: dict,
        intent:  Intent,
    ) -> AIContext | None:
        try:
            result = await spec.handler(text, profile, intent)
            logger.debug(
                "KnowledgeRouter | source=%r | intent=%s | found=%s",
                spec.key, intent.name,
                getattr(result, "found", "n/a"),
            )
            return result
        except Exception as exc:
            logger.warning(
                "KnowledgeRouter | source=%r failed | intent=%s | %s",
                spec.key, intent.name, exc,
            )
            return None

    async def _fetch_web(self, text: str, intent: Intent) -> list[WebSearchResult]:
        """
        Fetch web search results for supplemental injection.

        Returns empty list when web search is disabled, unconfigured, or fails.
        news_mode=True is set for news/trending intents to prefer recent results.
        """
        from config.ai_config import ENABLE_WEB_SEARCH
        if not ENABLE_WEB_SEARCH:
            logger.info("KnowledgeRouter | _fetch_web | ENABLE_WEB_SEARCH=False — skipped")
            return []

        news_mode = intent in (_LIVE_SUPPLEMENT_INTENTS | _LIVE_PRIMARY_INTENTS)
        refined   = _refine_query(text, intent)

        logger.info(
            "KnowledgeRouter | _fetch_web | intent=%s | provider=%s | configured=%s | news_mode=%s | query=%r",
            intent.name,
            web_search_service.active_provider_name(),
            web_search_service.is_configured(),
            news_mode,
            refined,
        )

        results = await web_search_service.search(
            refined,
            intent_name=intent.name,
            news_mode=news_mode,
        )
        logger.info(
            "KnowledgeRouter | _fetch_web | %d results returned | intent=%s",
            len(results), intent.name,
        )
        return results

    # ── Default source registration ────────────────────────────────────────────

    def _register_defaults(
        self,
        intelligence_service,
        search_service,
        news_service,
    ) -> None:
        """
        Register the four built-in knowledge sources.

        Handlers are closures that capture the injected service instances.
        All service parameters accept None — the handler returns None gracefully,
        letting the router fall through to the next source.
        """
        from services.context_builder import _INTELLIGENCE_INTENTS, _ANIME_CONTEXT_INTENTS, _NEWS_CONTEXT_INTENTS

        # ── Anime Intelligence (priority 0) ────────────────────────────────────
        if intelligence_service is not None:
            _intel = intelligence_service

            async def _handle_intelligence(text: str, profile: dict, intent: Intent) -> AIContext | None:
                order_type = "manga_continuation" if intent == Intent.MANGA_CONTINUATION else "watch_order"
                try:
                    intel_result = await _intel.resolve_and_plan(text, order_type)
                    ctx = ContextBuilder.from_intelligence_result(intel_result, intent, profile)
                    logger.info(
                        "KnowledgeRouter | intelligence | intent=%s | resolved=%r | ambiguous=%s",
                        intent.name, intel_result.resolved_title, intel_result.ambiguous,
                    )
                    return ctx
                except Exception as exc:
                    logger.warning("KnowledgeRouter | intelligence failed | %s — trying search", exc)
                    # Intelligence failure → fall through to search (return None)
                    return None

            self.register(KnowledgeSourceSpec(
                key      = "anime_intelligence",
                priority = 0,
                is_live  = False,
                intents  = _INTELLIGENCE_INTENTS,
                handler  = _handle_intelligence,
            ))

        # ── Anime Search (priority 10) ─────────────────────────────────────────
        if search_service is not None:
            _search = search_service

            async def _handle_search(text: str, profile: dict, intent: Intent) -> AIContext | None:
                result = await _search.search(text)
                ctx = ContextBuilder.from_search_result(result, intent, profile)
                logger.info(
                    "KnowledgeRouter | search | intent=%s | found=%s | title=%r",
                    intent.name, ctx.found,
                    ctx.anime.display_title if ctx.anime else None,
                )
                return ctx

            self.register(KnowledgeSourceSpec(
                key      = "anime_search",
                priority = 10,
                is_live  = False,
                intents  = _ANIME_CONTEXT_INTENTS,
                handler  = _handle_search,
            ))

        # ── News Service (priority 20) ─────────────────────────────────────────
        if news_service is not None:
            _news = news_service

            async def _handle_news(text: str, profile: dict, intent: Intent) -> AIContext | None:
                if intent == Intent.TRENDING:
                    news_result = await _news.fetch_trending()
                else:
                    news_result = await _news.fetch_latest()
                ctx = ContextBuilder.from_news_result(news_result, intent, profile)
                logger.info(
                    "KnowledgeRouter | news | intent=%s | found=%s | items=%d | source=%r",
                    intent.name, news_result.found, news_result.count, news_result.source,
                )
                return ctx

            self.register(KnowledgeSourceSpec(
                key      = "news",
                priority = 20,
                is_live  = True,
                intents  = _NEWS_CONTEXT_INTENTS,
                handler  = _handle_news,
            ))

        # ── Web Search live-primary handler (priority 50) ──────────────────────
        # This handles WEB_SEARCH / GENERAL_KNOWLEDGE as the primary source.
        # Supplemental web injection (for other intents) is handled directly
        # in _route() via _fetch_web(), not through a registered spec.

        async def _handle_web_primary(text: str, profile: dict, intent: Intent) -> AIContext | None:
            from config.ai_config import ENABLE_WEB_SEARCH
            if not ENABLE_WEB_SEARCH:
                logger.info(
                    "KnowledgeRouter | web_primary | ENABLE_WEB_SEARCH=False — skipped"
                )
                return None
            refined = _refine_query(text, intent)
            logger.info(
                "KnowledgeRouter | web_primary | routing to provider=%s | configured=%s | query=%r",
                web_search_service.active_provider_name(),
                web_search_service.is_configured(),
                refined,
            )
            results = await web_search_service.search(
                refined,
                intent_name=intent.name,
                news_mode=True,
            )
            logger.info(
                "KnowledgeRouter | web_primary | %d results | intent=%s",
                len(results), intent.name,
            )
            if not results:
                return None
            return ContextBuilder.from_web_result(text, results, profile, intent)

        self.register(KnowledgeSourceSpec(
            key      = "web_search_primary",
            priority = 50,
            is_live  = True,
            intents  = _LIVE_PRIMARY_INTENTS,
            handler  = _handle_web_primary,
        ))


# ── Query refinement ──────────────────────────────────────────────────────────

def _refine_query(text: str, intent: Intent) -> str:
    """
    Produce a tight web-search query from raw user text.

    Strips conversational filler and appends intent-appropriate qualifiers
    so SerpAPI returns relevant anime results.

    Examples:
        "what's the latest news about demon slayer" + ANIME_NEWS
          → "Demon Slayer latest news anime 2026"
        "attack on titan 2026 release date"         + WEB_SEARCH
          → "Attack on Titan 2026 release date anime"
    """
    import re
    from datetime import datetime

    filler = re.compile(
        r"\b(tell me|what('?s| is)|can you|please|i want to know|"
        r"search for|find|look up|about|the latest|any news|"
        r"do you know|have you heard|hey|yo|bro|"
        r"latest|recent|current|new|today)\b",
        re.IGNORECASE,
    )
    refined = filler.sub("", text).strip()
    refined = re.sub(r"\s{2,}", " ", refined).strip(" ,?!.")

    # Intent-specific qualifier
    qualifiers: dict[Intent, str] = {
        Intent.ANIME_NEWS:        f"anime news {datetime.now().year}",
        Intent.TRENDING:          f"trending anime {datetime.now().year}",
        Intent.UPCOMING:          f"upcoming anime {datetime.now().year}",
        Intent.WEB_SEARCH:        "anime",
        Intent.GENERAL_KNOWLEDGE: "anime",
    }
    suffix = qualifiers.get(intent, "anime")
    if suffix.lower() not in refined.lower():
        refined = f"{refined} {suffix}".strip()

    return refined or text  # never return empty string


# ── Conversational intent check ───────────────────────────────────────────────

_CONVERSATIONAL_INTENTS: frozenset[Intent] = frozenset({
    Intent.GREETING,
    Intent.HELP,
    Intent.WATCHLIST_ACTION,
    Intent.PROFILE_VIEW,
    Intent.FAVORITES_ACTION,
    Intent.UNKNOWN,
})

def _is_conversational(intent: Intent) -> bool:
    """True for intents that produce no useful web results."""
    return intent in _CONVERSATIONAL_INTENTS


# ── Module-level singleton ─────────────────────────────────────────────────────
# Wired with live service instances in message_handler.py.
# Callers import this and call knowledge_router.route().

def _make_default_router() -> KnowledgeRouter:
    """Instantiate KnowledgeRouter with the module-level service singletons."""
    from services.anime_search import search_service
    from services.anime_news import news_service
    from services.anime_intelligence import intelligence_service
    return KnowledgeRouter(
        intelligence_service=intelligence_service,
        search_service=search_service,
        news_service=news_service,
    )


knowledge_router: KnowledgeRouter = _make_default_router()
