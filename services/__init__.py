"""
services package — cross-cutting application services for Ani Zeo.

Services contain domain logic that is reusable across the bot layer,
the tools layer, and the AI layer.  They never import from bot.py,
tools/, or ai/ to keep the dependency graph acyclic.

Public surface
──────────────
  from services.intent          import Intent, IntentClassifier
  from services.anime_search    import AnimeSearchResult, AnimeSearchService, search_service
  from services.context_builder import AnimeContext, UserContext, AIContext, ContextBuilder
"""
from services.intent          import Intent, IntentClassifier
from services.anime_search    import AnimeSearchResult, AnimeSearchService, search_service
from services.context_builder import AnimeContext, UserContext, AIContext, ContextBuilder

__all__ = [
    # intent
    "Intent",
    "IntentClassifier",
    # anime search
    "AnimeSearchResult",
    "AnimeSearchService",
    "search_service",
    # context builder
    "AnimeContext",
    "UserContext",
    "AIContext",
    "ContextBuilder",
]
