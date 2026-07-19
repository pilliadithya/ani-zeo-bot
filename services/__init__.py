"""
services package — cross-cutting application services for Ani Zeo.

Services contain domain logic that is reusable across the bot layer,
the tools layer, and the AI layer.  They never import from bot.py,
tools/, or ai/ to keep the dependency graph acyclic.

Public surface
──────────────
  from services.intent       import Intent, IntentClassifier
  from services.anime_search import AnimeSearchResult, AnimeSearchService, search_service
"""
from services.intent        import Intent, IntentClassifier
from services.anime_search  import AnimeSearchResult, AnimeSearchService, search_service

__all__ = [
    "Intent",
    "IntentClassifier",
    "AnimeSearchResult",
    "AnimeSearchService",
    "search_service",
]
