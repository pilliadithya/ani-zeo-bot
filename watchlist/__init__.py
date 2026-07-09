"""
watchlist — modular watchlist system for Ani Zeo.

Public API
──────────
  WatchlistManager  business logic: add / remove / update_status / show
  WatchlistStore    JSON persistence (swap for a DB implementation later)
  WatchlistAction   structured result from the NLP parser
  parse             natural language → WatchlistAction | None
  is_watchlist_phrase  fast pre-check before running the full parser
"""
from watchlist.manager import WatchlistManager
from watchlist.store import WatchlistStore
from watchlist.nlp import WatchlistAction, parse, is_watchlist_phrase

__all__ = [
    "WatchlistManager",
    "WatchlistStore",
    "WatchlistAction",
    "parse",
    "is_watchlist_phrase",
]
