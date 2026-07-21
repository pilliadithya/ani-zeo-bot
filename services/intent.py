"""
IntentClassifier — maps a free-text user message to a structured Intent.

Currently uses fast keyword/regex matching.  The calling code depends only
on Intent (enum) and IntentClassifier.classify() — the matching strategy
can be replaced with an ML model in a later sprint without changing callers.

Enabled via config.ai_config.ENABLE_INTENT_ROUTING = True.

Supported user-facing intent categories (12):
    Anime Recommendation | Anime Information | Character Information |
    Manga Information    | Watch Order       | Watchlist             |
    Anime News           | Seasonal Anime    | Compare Anime         |
    Greeting             | Help              | Unknown
"""
from __future__ import annotations

import re
from enum import Enum, auto


class Intent(Enum):
    """
    All intents Ani Zeo can understand.

    Fine-grained values map 1-to-1 to existing commands where possible.
    Use DISPLAY_NAMES to get the user-facing category label for each value.
    """
    # ── Anime ──────────────────────────────────────────────────────────────
    SEARCH_ANIME      = auto()   # "find anime", "look up"
    GET_DETAILS       = auto()   # detailed info about a specific title
    RECOMMENDATIONS   = auto()   # "recommend", "anime like X"
    TOP_ANIME         = auto()   # "best anime", "highest rated"
    TRENDING          = auto()   # "what's trending"
    RANDOM_ANIME      = auto()   # "surprise me"
    SEASON_INFO       = auto()   # "currently airing", "this season"
    GENRE_BROWSE      = auto()   # "action anime", "genre"
    CHARACTER_LOOKUP  = auto()   # "who is", "voice actor"
    STUDIO_LOOKUP     = auto()   # "who made", "which studio"
    WATCH_ORDER       = auto()   # "watch order", "where to start"
    MANGA_CONTINUATION = auto() # "manga after anime", "read manga from", "pick up manga"
    COMPARE_ANIME     = auto()   # "X vs Y", "compare"
    UPCOMING          = auto()   # "next season", "upcoming"
    DUB_INFO          = auto()   # "dubbed", "English version"
    ANIME_NEWS        = auto()   # "latest anime news", "what's new"
    # ── Manga ──────────────────────────────────────────────────────────────
    SEARCH_MANGA      = auto()   # "find manga", "manga about X"
    TOP_MANGA         = auto()   # "best manga", "top manga"
    RANDOM_MANGA      = auto()   # "random manga"
    MANGA_GENRE       = auto()   # "manga genre"
    # ── User data ──────────────────────────────────────────────────────────
    WATCHLIST_ACTION  = auto()   # "add to watchlist", "mark as finished"
    PROFILE_VIEW      = auto()   # "my profile", "my stats"
    FAVORITES_ACTION  = auto()   # "my favorites", "saved anime"
    # ── Conversational ─────────────────────────────────────────────────────
    GREETING          = auto()   # "hi", "hello", "hey"
    HELP              = auto()   # "help", "what can you do"
    # ── AI-only (no command equivalent yet) ────────────────────────────────
    OPEN_QUESTION     = auto()   # general anime/manga question
    EXPLANATION       = auto()   # "what is …", "explain …"
    LORE_QUESTION     = auto()   # "who killed …", "what happens in …"
    # ── Fallback ───────────────────────────────────────────────────────────
    UNKNOWN           = auto()


# ── User-facing category labels ───────────────────────────────────────────────
# Maps each fine-grained Intent to one of the 12 display categories.
# Use IntentClassifier.display_name(intent) instead of accessing this directly.

DISPLAY_NAMES: dict[Intent, str] = {
    Intent.SEARCH_ANIME:      "Anime Information",
    Intent.GET_DETAILS:       "Anime Information",
    Intent.RECOMMENDATIONS:   "Anime Recommendation",
    Intent.TOP_ANIME:         "Anime Information",
    Intent.TRENDING:          "Anime Information",
    Intent.RANDOM_ANIME:      "Anime Information",
    Intent.SEASON_INFO:       "Seasonal Anime",
    Intent.GENRE_BROWSE:      "Anime Information",
    Intent.CHARACTER_LOOKUP:  "Character Information",
    Intent.STUDIO_LOOKUP:     "Anime Information",
    Intent.WATCH_ORDER:        "Watch Order",
    Intent.MANGA_CONTINUATION: "Watch Order",
    Intent.COMPARE_ANIME:     "Compare Anime",
    Intent.UPCOMING:          "Seasonal Anime",
    Intent.DUB_INFO:          "Anime Information",
    Intent.ANIME_NEWS:        "Anime News",
    Intent.SEARCH_MANGA:      "Manga Information",
    Intent.TOP_MANGA:         "Manga Information",
    Intent.RANDOM_MANGA:      "Manga Information",
    Intent.MANGA_GENRE:       "Manga Information",
    Intent.WATCHLIST_ACTION:  "Watchlist",
    Intent.PROFILE_VIEW:      "Anime Information",
    Intent.FAVORITES_ACTION:  "Anime Information",
    Intent.GREETING:          "Greeting",
    Intent.HELP:              "Help",
    Intent.OPEN_QUESTION:     "Anime Information",
    Intent.EXPLANATION:       "Anime Information",
    Intent.LORE_QUESTION:     "Anime Information",
    Intent.UNKNOWN:           "Unknown",
}


# ── Pattern table ─────────────────────────────────────────────────────────────
# Each row: (Intent, [regex patterns]).
# Matched top-to-bottom — first match wins.
#
# Ordering rules:
#   1. Specific multi-word constructs before single-word anchors.
#   2. Structural intents (watch order, compare) before simple lookups.
#   3. GREETING and HELP last — they match very short messages only.

_PATTERNS: list[tuple[Intent, list[str]]] = [
    # ── Must-be-first: structural / multi-word ────────────────────────────
    # WATCH_ORDER: only unambiguous watch-order phrases.
    # "watch next" removed — too easily confused with "what to watch next"
    # (a recommendation intent).
    (Intent.MANGA_CONTINUATION, [r"\bmanga (after|continuation|from chapter)\b",
                                  r"\bafter (the )?anime\b.{0,30}\bmanga\b",
                                  r"\bmanga\b.{0,30}\bafter (the )?anime\b",
                                  r"\bpick up (the )?manga\b",
                                  r"\bwhere (to start|does).{0,20}manga\b",
                                  r"\bread manga (after|from|continuation)\b",
                                  r"\bread order\b"]),
    (Intent.WATCH_ORDER,      [r"\bwatch order\b",
                                r"\bwhere (to start|do i start)\b",
                                r"\bwatch first\b",
                                r"\bin what order\b"]),
    (Intent.COMPARE_ANIME,    [r"\bcompare\b",
                                r"\b(vs|versus)\b"]),

    # ── Manga cluster — must precede all broad anime/recommendation rules ──
    # Rule: any phrase containing "manga" AND a recommendation/discovery word
    # is manga-territory. Placing this cluster before RECOMMENDATIONS ensures
    # "best manga recommendations" / "random manga suggestion" don't fall
    # through to the general anime intents.
    (Intent.RANDOM_MANGA,     [r"\brandom manga\b"]),
    (Intent.TOP_MANGA,        [r"\btop manga\b",
                                r"\bbest manga\b"]),
    (Intent.MANGA_GENRE,      [r"\bmanga\b.*\bgenre\b",
                                r"\bgenre\b.*\bmanga\b"]),
    (Intent.SEARCH_MANGA,     [r"\bmanga\b.*(recommend|suggest)",
                                r"(recommend|suggest).*\bmanga\b",
                                r"\bmanga\b.*\bsearch\b",
                                r"\blook up.*\bmanga\b",
                                r"\bfind.*\bmanga\b",
                                r"\bmanga about\b",
                                r"\bmanga\b"]),   # broad catch-all after specifics

    # ── Recommendation (anime-scoped — manga already handled above) ────────
    (Intent.RECOMMENDATIONS,  [r"\brecommend",
                                r"\bsimilar to\b",
                                r"\banime like\b",
                                r"\bwhat (should|to)\b.*\bwatch\b",
                                r"\bsuggest"]),

    # ── People & studios ──────────────────────────────────────────────────
    (Intent.CHARACTER_LOOKUP, [r"\bcharacter\b",
                                r"\bwho is\b",
                                r"\bvoice actor\b",
                                r"\bprotagonist\b",
                                r"\bantagonist\b"]),
    (Intent.STUDIO_LOOKUP,    [r"\bstudio\b",
                                r"\banimation (company|studio)\b",
                                r"\bwho (made|animated|produced)\b"]),

    # ── Format / version ──────────────────────────────────────────────────
    (Intent.DUB_INFO,         [r"\bdub\b",
                                r"\bdubbed\b",
                                r"\benglish version\b"]),

    # ── Browse / discover ─────────────────────────────────────────────────
    # GENRE_BROWSE is after MANGA_GENRE so "manga genre" hits MANGA_GENRE first.
    (Intent.GENRE_BROWSE,     [r"\bgenre\b",
                                r"\baction anime\b",
                                r"\bromance anime\b",
                                r"\bcomedy anime\b",
                                r"\bhorror anime\b",
                                r"\bisekai anime\b",
                                r"\bshounen anime\b"]),
    (Intent.SEASON_INFO,      [r"\bthis season\b",
                                r"\bairing now\b",
                                r"\bcurrently airing\b"]),
    (Intent.UPCOMING,         [r"\bupcoming\b",
                                r"\bnext season\b",
                                r"\bnew anime\b"]),

    # ── News ──────────────────────────────────────────────────────────────
    (Intent.ANIME_NEWS,       [r"\banime news\b",
                                r"\blatest (anime|manga)\b",
                                r"\banime updates?\b",
                                r"\bwhat'?s new (in anime|in manga)\b",
                                r"\bnews\b"]),

    # ── Rankings ──────────────────────────────────────────────────────────
    (Intent.TOP_ANIME,        [r"\btop anime\b",
                                r"\bbest anime\b",
                                r"\bhighest rated\b",
                                r"\bmost popular\b"]),
    (Intent.TRENDING,         [r"\btrending\b",
                                r"\bpopular right now\b"]),
    (Intent.RANDOM_ANIME,     [r"\brandom anime\b",
                                r"\bsurprise me\b",
                                r"\bpick (one|something)\b"]),

    # ── User data ─────────────────────────────────────────────────────────
    # WATCHLIST mark: use \bmark\b.*\b(as|it)\b so a title between
    # "mark" and "as" (e.g. "mark One Piece as finished") still matches.
    (Intent.WATCHLIST_ACTION, [r"\bwatchlist\b",
                                r"\badd to\b",
                                r"\bmark\b.*\b(as|it)\b",
                                r"\bfinished watching\b"]),
    (Intent.FAVORITES_ACTION, [r"\bfavourite\b",
                                r"\bfavorite\b",
                                r"\bsaved anime\b"]),
    (Intent.PROFILE_VIEW,     [r"\bmy profile\b",
                                r"\bmy stats\b",
                                r"\bmy activity\b"]),

    # ── AI-only / open questions ───────────────────────────────────────────
    (Intent.EXPLANATION,      [r"\bwhat is\b",
                                r"\bexplain\b",
                                r"\btell me about\b",
                                r"\bdefine\b"]),
    (Intent.LORE_QUESTION,    [r"\bwhat happens\b",
                                r"\bwho (killed|was)\b",
                                r"\bending (of|explained)\b",
                                r"\bplot of\b"]),

    # ── General anime search (broad — keep near end) ──────────────────────
    (Intent.SEARCH_ANIME,     [r"\bsearch\b",
                                r"\bfind anime\b",
                                r"\blook up\b",
                                r"\binfo (on|about)\b",
                                r"\bdetails (on|about)\b"]),

    # ── Conversational (very last — short/vague messages only) ────────────
    (Intent.HELP,             [r"\bhelp\b",
                                r"\bwhat can you do\b",
                                r"\bcommands?\b",
                                r"\bhow (do i|to) use\b",
                                r"\bwhat do you do\b"]),
    (Intent.GREETING,         [r"^(hi|hey|hello|yo|sup|hiya|heya|howdy)[!?\s.,]*$",
                                r"^(good (morning|afternoon|evening|night))[!?\s.,]*$",
                                r"^(konnichiwa|ohayo|kon(ban)?wa|namaste|vanakkam)[!?\s.,]*$",
                                r"^(what'?s up|wassup|wsg)[!?\s.,]*$"]),
]


class IntentClassifier:
    """
    Classifies a user message string into an Intent enum value.

    Callers should depend only on Intent and this class interface —
    the underlying matching strategy (regex → ML) can change without
    touching any calling code.

    Example:
        classifier = IntentClassifier()
        intent = classifier.classify("recommend some romance anime")
        # → Intent.RECOMMENDATIONS

        label = classifier.display_name(intent)
        # → "Anime Recommendation"
    """

    def classify(self, text: str) -> Intent:
        """
        Return the best-matching Intent for the given text.
        Returns Intent.UNKNOWN when no pattern matches confidently.
        """
        normalised = text.lower().strip()
        for intent, patterns in _PATTERNS:
            for pattern in patterns:
                if re.search(pattern, normalised):
                    return intent
        return Intent.UNKNOWN

    def classify_with_confidence(self, text: str) -> tuple[Intent, float]:
        """
        Returns (Intent, confidence_score 0.0–1.0).
        Confidence is 1.0 for any keyword match, 0.0 for UNKNOWN.
        Reserved for future ML-backed probability scoring.
        """
        intent = self.classify(text)
        confidence = 1.0 if intent is not Intent.UNKNOWN else 0.0
        return intent, confidence

    def display_name(self, intent: Intent) -> str:
        """
        Return the user-facing category name for an intent.
        One of the 12 supported categories, e.g. 'Anime Recommendation'.
        """
        return DISPLAY_NAMES.get(intent, "Unknown")

    def describe(self, intent: Intent) -> str:
        """
        Internal name for logging / debugging.
        E.g. Intent.RECOMMENDATIONS → 'Recommendations'.
        """
        return intent.name.replace("_", " ").title()
