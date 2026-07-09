"""
WatchlistNLP — natural language parser for watchlist commands.

parse(text) → WatchlistAction | None

Returns None when the text is not a watchlist command so callers can fall
through to the AI router for everything else.

Supported natural language (case-insensitive):
  ADD / PLANNED
    "Add Naruto to my watchlist"
    "Put One Piece on my watchlist"
    "I want to watch Demon Slayer"
    "Planning to watch Vinland Saga"
    "I'll watch Mushishi"

  ADD / WATCHING
    "I'm watching Bleach"
    "Currently watching Hunter x Hunter"
    "Started watching Fullmetal Alchemist"

  ADD / COMPLETED
    "I finished Attack on Titan"
    "I've completed Death Note"
    "Finished watching Steins;Gate"
    "Just finished Cowboy Bebop"

  MARK (move between statuses)
    "Mark Bleach as completed"
    "Mark Naruto as watching"

  REMOVE
    "Remove Bleach from my watchlist"
    "Delete One Piece from my list"
    "Drop Sword Art Online"
    "Drop Sword Art Online from my watchlist"

  SHOW
    "Show my watchlist"
    "My watchlist"
    "What's on my watchlist?"
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class WatchlistAction:
    """Structured result from the NLP parser."""
    action: str          # "add" | "remove" | "show" | "mark"
    anime: str | None    # extracted title (None for "show")
    status: str | None   # target status, or None for "remove" / "show"


# ── Pattern table ──────────────────────────────────────────────────────────────
# Each entry: (action, default_status, compiled pattern)
# Capture group 1 is always the anime title (when present).
# Matched top-to-bottom — first match wins.

_RX = re.compile  # shorthand

_PATTERNS: list[tuple[str, str | None, re.Pattern]] = [

    # ── show ──────────────────────────────────────────────────────────────────
    ("show", None, _RX(
        r"^(?:show\s+)?(?:my\s+)?watchlist$"
        r"|^(?:what[''']?s|what\s+is)\s+(?:on|in)\s+(?:my\s+)?watchlist\?*$"
        r"|^(?:show|display|list)\s+(?:my\s+)?(?:watchlist|watch[\s\-]list)$",
        re.I,
    )),

    # ── mark <anime> as <status> ──────────────────────────────────────────────
    ("mark", None, _RX(
        r"^mark\s+(.+?)\s+as\s+(watching|completed|planned|dropped|done|finished|watched)$",
        re.I,
    )),

    # ── finished / completed ──────────────────────────────────────────────────
    ("add", "completed", _RX(
        r"^(?:i(?:'ve|'ve|\s+have|\s+just)?|just)\s+finished\s+(?:watching\s+)?(.+)$"
        r"|^(?:i(?:'ve|'ve|\s+have|\s+just)?|just)\s+completed\s+(?:watching\s+)?(.+)$"
        r"|^finished\s+(?:watching\s+)?(.+)$"
        r"|^completed\s+(?:watching\s+)?(.+)$",
        re.I,
    )),

    # ── currently watching ────────────────────────────────────────────────────
    ("add", "watching", _RX(
        r"^(?:i(?:'m|'m|\s+am)|currently)\s+watching\s+(.+)$"
        r"|^started\s+watching\s+(.+)$",
        re.I,
    )),

    # ── plan to watch ─────────────────────────────────────────────────────────
    ("add", "planned", _RX(
        r"^i\s+(?:want|wanna)\s+to\s+watch\s+(.+)$"
        r"|^(?:planning|plan)\s+to\s+watch\s+(.+)$"
        r"|^i(?:'ll|'ll|\s+will)\s+watch\s+(.+)$",
        re.I,
    )),

    # ── add to <status> list (explicit status in phrase) ─────────────────────
    ("add", None, _RX(
        r"^(?:add|put)\s+(.+?)\s+(?:to|in(?:to)?)\s+(?:my\s+)?"
        r"(watching|completed|planned|dropped)\s+(?:list|watchlist)$"
        r"|^(.+?)\s+(?:to|in(?:to)?)\s+(?:my\s+)?"
        r"(watching|completed|planned|dropped)\s+(?:list|watchlist)$",
        re.I,
    )),

    # ── add to watchlist (no explicit status → planned) ───────────────────────
    ("add", "planned", _RX(
        r"^(?:add|put)\s+(.+?)\s+(?:to|on|in(?:to)?)\s+(?:my\s+)?(?:watchlist|watch[\s\-]list)$",
        re.I,
    )),

    # ── remove / drop ─────────────────────────────────────────────────────────
    # Accepts with or without "from my watchlist/list" suffix.
    ("remove", None, _RX(
        r"^(?:remove|delete|take\s+off)\s+(.+?)"
        r"(?:\s+from\s+(?:my\s+)?(?:watchlist|watch[\s\-]list|list))?$"
        r"|^drop\s+(.+?)"
        r"(?:\s+from\s+(?:my\s+)?(?:watchlist|watch[\s\-]list|list))?$",
        re.I,
    )),
]

# Trailing words to strip from extracted titles
_TRAILING_NOISE = re.compile(
    r"\s+(?:anime|series|show|from\s+(?:my\s+)?(?:watchlist|list))$",
    re.I,
)

# Status synonym mapping for mark/add inline status groups
_STATUS_MAP: dict[str, str] = {
    "finished": "completed",
    "done":     "completed",
    "watched":  "completed",
}


def parse(text: str) -> WatchlistAction | None:
    """
    Parse a natural-language message into a WatchlistAction.
    Returns None if the text is not a watchlist command.
    """
    stripped = text.strip()

    for action, default_status, pattern in _PATTERNS:
        m = pattern.match(stripped)
        if not m:
            continue

        # "show" — no groups
        if action == "show":
            return WatchlistAction(action="show", anime=None, status=None)

        groups = [g for g in m.groups() if g is not None]
        if not groups:
            continue

        # "mark" — group 1 = title, group 2 = status keyword
        if action == "mark":
            anime  = _clean(groups[0])
            status = _map_status(groups[1])
            if anime:
                return WatchlistAction(action="mark", anime=anime, status=status)
            continue

        # "add to <status> list" patterns have alternating title/status groups.
        # Detect an inline status: if the last group is a known status word,
        # use it and treat the first group as the title.
        status = default_status
        title_raw = groups[0]

        if len(groups) >= 2:
            last = groups[-1].lower()
            if last in ("watching", "completed", "planned", "dropped",
                        "finished", "done", "watched"):
                status = _map_status(last)
                title_raw = groups[0]

        anime = _clean(title_raw)
        if anime:
            return WatchlistAction(
                action=action,
                anime=anime,
                status=status or "planned",
            )

    return None


def is_watchlist_phrase(text: str) -> bool:
    """Quick pre-check — returns True if text might be a watchlist command."""
    lower = text.lower()
    return bool(re.search(
        r"\bwatchlist\b"
        r"|\badd to\b"
        r"|\bmark .+ as\b"
        r"|\b(i(?:\'ve|\'m| have| am| finished| completed| want| will)|just|finished|completed|started|currently|planning|drop(?:ped)?)\b",
        lower,
    ))


# ── Helpers ────────────────────────────────────────────────────────────────────

def _clean(raw: str) -> str:
    return _TRAILING_NOISE.sub("", raw.strip()).strip()


def _map_status(word: str) -> str:
    return _STATUS_MAP.get(word.lower(), word.lower())
