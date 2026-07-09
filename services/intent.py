"""
IntentClassifier — maps a free-text user message to a structured Intent.

Currently uses fast keyword/regex matching.  The calling code depends only
on Intent (enum) and IntentClassifier.classify() — the matching strategy
can be replaced with an ML model in a later sprint without changing callers.

Disabled until config.ai_config.ENABLE_INTENT_ROUTING = True.
"""
from __future__ import annotations

import re
from enum import Enum, auto


class Intent(Enum):
    """
    All intents Ani Zeo can understand.

    Intents map 1-to-1 to existing commands where possible, and add
    AI-only intents (OPEN_QUESTION, EXPLANATION, LORE_QUESTION) that
    have no command equivalent yet.
    """
    # ── Anime ──────────────────────────────────────────────────────────────
    SEARCH_ANIME      = auto()
    GET_DETAILS       = auto()
    RECOMMENDATIONS   = auto()
    TOP_ANIME         = auto()
    TRENDING          = auto()
    RANDOM_ANIME      = auto()
    SEASON_INFO       = auto()
    GENRE_BROWSE      = auto()
    CHARACTER_LOOKUP  = auto()
    STUDIO_LOOKUP     = auto()
    WATCH_ORDER       = auto()
    COMPARE_ANIME     = auto()
    UPCOMING          = auto()
    DUB_INFO          = auto()
    # ── Manga ──────────────────────────────────────────────────────────────
    SEARCH_MANGA      = auto()
    TOP_MANGA         = auto()
    RANDOM_MANGA      = auto()
    MANGA_GENRE       = auto()
    # ── User data ──────────────────────────────────────────────────────────
    WATCHLIST_ACTION  = auto()
    PROFILE_VIEW      = auto()
    FAVORITES_ACTION  = auto()
    # ── AI-only (no command equivalent yet) ────────────────────────────────
    OPEN_QUESTION     = auto()   # general anime/manga question
    EXPLANATION       = auto()   # "what is …", "explain …"
    LORE_QUESTION     = auto()   # "who killed …", "what happens in …"
    # ── Fallback ───────────────────────────────────────────────────────────
    UNKNOWN           = auto()


# ── Pattern table ─────────────────────────────────────────────────────────────
# Each row: (Intent, [regex patterns]).
# Matched top-to-bottom — first match wins.

_PATTERNS: list[tuple[Intent, list[str]]] = [
    (Intent.WATCH_ORDER,      [r"\bwatch order\b", r"\bwhere (to start|do i start)\b",
                                r"\bwatch (first|next)\b", r"\bin what order\b"]),
    (Intent.RECOMMENDATIONS,  [r"\brecommend", r"\bsimilar to\b", r"\banime like\b",
                                r"\bwhat (should|to) watch\b", r"\bsuggest"]),
    (Intent.COMPARE_ANIME,    [r"\bcompare\b", r"\b(vs|versus)\b"]),
    (Intent.CHARACTER_LOOKUP, [r"\bcharacter\b", r"\bwho is\b", r"\bvoice actor\b",
                                r"\bprotagonist\b", r"\bantagonist\b"]),
    (Intent.STUDIO_LOOKUP,    [r"\bstudio\b", r"\banimation (company|studio)\b",
                                r"\bwho (made|animated|produced)\b"]),
    (Intent.DUB_INFO,         [r"\bdub\b", r"\bdubbed\b", r"\benglish version\b"]),
    (Intent.GENRE_BROWSE,     [r"\bgenre\b", r"\baction anime\b", r"\bromance anime\b",
                                r"\bcomedy anime\b", r"\bhorror anime\b"]),
    (Intent.SEASON_INFO,      [r"\bthis season\b", r"\bairing now\b", r"\bcurrently airing\b"]),
    (Intent.UPCOMING,         [r"\bupcoming\b", r"\bnext season\b", r"\bnew anime\b"]),
    (Intent.TOP_ANIME,        [r"\btop\b", r"\bbest anime\b", r"\bhighest rated\b",
                                r"\bmost popular\b"]),
    (Intent.TRENDING,         [r"\btrending\b", r"\bpopular right now\b"]),
    (Intent.RANDOM_ANIME,     [r"\brandom\b", r"\bsurprise me\b", r"\bpick (one|something)\b"]),
    (Intent.TOP_MANGA,        [r"\btop manga\b", r"\bbest manga\b"]),
    (Intent.SEARCH_MANGA,     [r"\bmanga\b.*\bsearch\b", r"\blook up.*\bmanga\b",
                                r"\bfind.*\bmanga\b"]),
    (Intent.MANGA_GENRE,      [r"\bmanga.*genre\b", r"\bgenre.*manga\b"]),
    (Intent.RANDOM_MANGA,     [r"\brandom manga\b"]),
    (Intent.WATCHLIST_ACTION, [r"\bwatchlist\b", r"\badd to\b", r"\bmark (as|it)\b",
                                r"\bfinished watching\b"]),
    (Intent.FAVORITES_ACTION, [r"\bfavourite\b", r"\bfavorite\b", r"\bsaved anime\b"]),
    (Intent.PROFILE_VIEW,     [r"\bmy profile\b", r"\bmy stats\b", r"\bmy activity\b"]),
    (Intent.EXPLANATION,      [r"\bwhat is\b", r"\bexplain\b", r"\btell me about\b",
                                r"\bdefine\b"]),
    (Intent.LORE_QUESTION,    [r"\bwhat happens\b", r"\bwho (killed|is|was)\b",
                                r"\bending (of|explained)\b", r"\bplot of\b"]),
    (Intent.SEARCH_ANIME,     [r"\bsearch\b", r"\bfind anime\b", r"\blook up\b"]),
]


class IntentClassifier:
    """
    Classifies a user message string into an Intent enum value.

    Example:
        classifier = IntentClassifier()
        intent = classifier.classify("recommend some romance anime")
        # → Intent.RECOMMENDATIONS
    """

    def classify(self, text: str) -> Intent:
        """Return the best-matching Intent for the given text."""
        normalised = text.lower().strip()
        for intent, patterns in _PATTERNS:
            for pattern in patterns:
                if re.search(pattern, normalised):
                    return intent
        return Intent.UNKNOWN

    def classify_with_confidence(self, text: str) -> tuple[Intent, float]:
        """
        Returns (Intent, confidence_score 0.0–1.0).
        Confidence is 1.0 for a keyword match, 0.0 for UNKNOWN.
        Reserved for future ML-backed scoring.
        """
        intent = self.classify(text)
        confidence = 1.0 if intent is not Intent.UNKNOWN else 0.0
        return intent, confidence

    def describe(self, intent: Intent) -> str:
        """Human-readable label for an intent (useful for logging/debug)."""
        return intent.name.replace("_", " ").title()
