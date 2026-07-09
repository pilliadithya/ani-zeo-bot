"""
WatchlistStore — JSON-backed persistence layer for user watchlists.

This is the *only* file that reads or writes watchlist.json.
To replace JSON with a database, subclass or re-implement this class and
inject the new implementation into WatchlistManager — no other file changes.

Data shape (watchlist.json):
  {
    "<user_id_str>": {
      "watching":  ["Naruto", "Bleach"],
      "completed": ["Attack on Titan"],
      "planned":   [],
      "dropped":   []
    }
  }
"""
from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# Shared with bot.py — same file, same schema
WATCHLIST_FILE = Path("watchlist.json")

VALID_STATUSES: tuple[str, ...] = ("watching", "completed", "planned", "dropped")


class WatchlistStore:
    """
    Thin persistence wrapper around watchlist.json.

    Reads on every call so that multiple restarts or future multi-process
    deployments see consistent state. Acceptable for a single-process bot;
    replace with a DB-backed implementation to scale.
    """

    def load(self, user_id: int) -> dict[str, list[str]]:
        """
        Return the watchlist for user_id.

        Always returns a complete dict with all four status keys so callers
        never need to guard against missing keys.
        """
        raw = self._read_file()
        entry = raw.get(str(user_id), {})
        return {s: list(entry.get(s, [])) for s in VALID_STATUSES}

    def save(self, user_id: int, user_data: dict[str, list[str]]) -> None:
        """Persist user_data for user_id, merging into the shared file."""
        raw = self._read_file()
        raw[str(user_id)] = {s: list(user_data.get(s, [])) for s in VALID_STATUSES}
        try:
            WATCHLIST_FILE.write_text(
                json.dumps(raw, indent=2, ensure_ascii=False)
            )
        except OSError as exc:
            logger.error("WatchlistStore.save failed: %s", exc)
            raise

    # ── Private ────────────────────────────────────────────────────────────────

    def _read_file(self) -> dict:
        if not WATCHLIST_FILE.exists():
            return {}
        try:
            return json.loads(WATCHLIST_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("WatchlistStore._read_file error: %s", exc)
            return {}
