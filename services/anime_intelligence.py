"""
Anime Intelligence Core — title resolver, franchise manifest, continuation planner.

Three components
────────────────
  AnimeResolver       — alias / abbreviation / typo → canonical search title
  FranchiseService    — AniList relations → structured FranchiseManifest
  ContinuationPlanner — manifest + intent → ordered watch / read / manga plan
  AnimeIntelligence   — facade that wires all three together

All output is structured data (dataclasses only).
AI formatting and Telegram rendering happen upstream in ContextBuilder / message_handler.

Reuses:
  services.anime_search.search_service — title verification (no duplicate API layer)
  requests (already a project dependency — no new installs)
"""
from __future__ import annotations

import asyncio
import logging
import re
from dataclasses import dataclass, field

import requests

logger = logging.getLogger(__name__)

_REQUEST_TIMEOUT: int = 15
_ANILIST_URL: str = "https://graphql.anilist.co"


# ── Alias table ────────────────────────────────────────────────────────────────
# Keys: lowercased, hyphen→space, punctuation-stripped, whitespace-collapsed.
# Values: canonical title string to pass to AniList / Jikan search.

_ALIAS_TABLE: dict[str, str] = {
    # Dragon Ball family ──────────────────────────────────────────────────────
    "db":                               "Dragon Ball",
    "dragonball":                       "Dragon Ball",
    "dragon ball":                      "Dragon Ball",
    "dragon balls":                     "Dragon Ball",
    "dragon-ball":                      "Dragon Ball",
    "dbz":                              "Dragon Ball Z",
    "dragon ball z":                    "Dragon Ball Z",
    "dragonball z":                     "Dragon Ball Z",
    "dbs":                              "Dragon Ball Super",
    "dragon ball super":                "Dragon Ball Super",
    "dbgt":                             "Dragon Ball GT",
    "dragon ball gt":                   "Dragon Ball GT",

    # Jujutsu Kaisen ──────────────────────────────────────────────────────────
    "jjk":                              "Jujutsu Kaisen",
    "jjk 0":                            "Jujutsu Kaisen 0",
    "jjk0":                             "Jujutsu Kaisen 0",
    "jujutsu kaisen 0":                 "Jujutsu Kaisen 0",
    "jujutsu kaisen zero":              "Jujutsu Kaisen 0",

    # Attack on Titan ─────────────────────────────────────────────────────────
    "aot":                              "Attack on Titan",
    "snk":                              "Attack on Titan",
    "shingeki no kyojin":               "Attack on Titan",

    # One Piece ───────────────────────────────────────────────────────────────
    "op":                               "One Piece",

    # Naruto ──────────────────────────────────────────────────────────────────
    "ns":                               "Naruto: Shippuden",
    "naruto shippuuden":                "Naruto: Shippuden",
    "naruto shippuden":                 "Naruto: Shippuden",

    # Fullmetal Alchemist ─────────────────────────────────────────────────────
    "fma":                              "Fullmetal Alchemist",
    "fmab":                             "Fullmetal Alchemist: Brotherhood",
    "fullmetal alchemist brotherhood":  "Fullmetal Alchemist: Brotherhood",

    # My Hero Academia ────────────────────────────────────────────────────────
    "mha":                              "My Hero Academia",
    "bnha":                             "My Hero Academia",
    "boku no hero":                     "My Hero Academia",
    "boku no hero academia":            "My Hero Academia",

    # Demon Slayer ────────────────────────────────────────────────────────────
    "kny":                              "Demon Slayer",
    "kimetsu no yaiba":                 "Demon Slayer",

    # Hunter x Hunter ─────────────────────────────────────────────────────────
    "hxh":                              "Hunter x Hunter",
    "hunterxhunter":                    "Hunter x Hunter",

    # Bleach ──────────────────────────────────────────────────────────────────
    "tybw":                             "Bleach: Thousand-Year Blood War",
    "bleach tybw":                      "Bleach: Thousand-Year Blood War",
    "bleach tbtp":                      "Bleach: Thousand-Year Blood War",

    # Sword Art Online ────────────────────────────────────────────────────────
    "sao":                              "Sword Art Online",

    # Re:Zero ─────────────────────────────────────────────────────────────────
    "rezero":                           "Re:Zero",
    "re zero":                          "Re:Zero",

    # JoJo's Bizarre Adventure ────────────────────────────────────────────────
    "jojo":                             "JoJo's Bizarre Adventure",
    "jojos":                            "JoJo's Bizarre Adventure",
    "jjba":                             "JoJo's Bizarre Adventure",

    # That Time I Got Reincarnated as a Slime ─────────────────────────────────
    "tensura":                          "That Time I Got Reincarnated as a Slime",
    "slime isekai":                     "That Time I Got Reincarnated as a Slime",

    # Frieren ─────────────────────────────────────────────────────────────────
    "frieren":                          "Frieren: Beyond Journey's End",
    "frieren beyond journey":           "Frieren: Beyond Journey's End",
    "sousou no frieren":                "Frieren: Beyond Journey's End",

    # Shield Hero ─────────────────────────────────────────────────────────────
    "tate no yuusha":                   "The Rising of the Shield Hero",
    "shield hero":                      "The Rising of the Shield Hero",

    # Black Clover ────────────────────────────────────────────────────────────
    "bc":                               "Black Clover",

    # Solo Leveling (British spelling) ────────────────────────────────────────
    "solo levelling":                   "Solo Leveling",

    # Dr. Stone — unambiguous forms ───────────────────────────────────────────
    "dr stone":                         "Dr. Stone",
    "doctor stone":                     "Dr. Stone",
}

# ── Context-dependent disambiguation ──────────────────────────────────────────
# For aliases that could mean multiple titles.
# keywords: if any keyword appears in the original query → resolve to that target.
# question: ask the user if no keywords match.

_AMBIGUOUS_TABLE: dict[str, dict] = {
    "ds": {
        "options": ["Dr. Stone", "Demon Slayer"],
        "keywords": {
            "Dr. Stone":    ["stone", "senku", "science", "dr", "doctor"],
            "Demon Slayer": ["demon", "kimetsu", "slayer", "tanjiro", "nezuko"],
        },
        "question": (
            "Did you mean *Dr. Stone* or *Demon Slayer*? "
            "Reply with the title to continue."
        ),
    },
}

# ── Stop-word patterns for title extraction ────────────────────────────────────
# These intent phrases are stripped from the query before alias resolution.
# "Naruto watch order" → "Naruto",  "jjk manga continuation" → "jjk"

_STOP_PATTERNS: list[str] = [
    # Combined multi-word patterns FIRST — they must win over their sub-parts
    r"\bmanga\s+after\s+(the\s+)?anime\b",    # "manga after anime" as a unit
    r"\bafter\s+(the\s+)?anime\b",
    r"\bwatch\s+order\b",
    r"\bread\s+order\b",
    r"\bin\s+what\s+order\b",
    r"\bwhere\s+to\s+start\b",
    r"\bwatch\s+first\b",
    r"\bwhat\s+to\s+watch\s+(next|first)\b",
    r"\bmanga\s+continuation\b",
    r"\bcontinuation\b",
    r"\bread\s+manga\b",
    r"\bmanga\s+after\b",
    r"\bpick\s+up\s+manga\b",
    r"\bcanon[\s-]only\b",
    r"\bfiller[\s-]?skip(ped|ping)?\b",       # "filler skip", "filler skipped"
    r"\bskip[\s-]?filler\b",
    r"\bfiller[\s-]?(free|less)\b",
    r"\bfull\s+order\b",
    r"\bwatch\s+guide\b",
    r"\bguide\b",
    r"\border\s+to\s+watch\b",
    r"\border\s+to\s+read\b",
    r"\border\b",             # trailing "order" left over after partial phrase removal
]

# ── Filler episode ranges ──────────────────────────────────────────────────────
# key: lowercased title exactly as AniList returns it.
# value: list of (first, last) inclusive episode ranges that are non-canon filler.

_FILLER_RANGES: dict[str, list[tuple[int, int]]] = {
    "naruto": [
        (26, 26), (97, 106), (137, 140), (143, 219),
    ],
    "naruto: shippuden": [
        (57, 71), (91, 112), (144, 151), (170, 171),
        (176, 196), (223, 242), (257, 260), (271, 273),
        (279, 281), (284, 295), (303, 320), (333, 336),
        (347, 349), (351, 361), (376, 377), (388, 390),
        (394, 416), (422, 423), (427, 450), (480, 483),
    ],
    "bleach": [
        (33, 50), (64, 109), (128, 137), (147, 149),
        (168, 189), (204, 205), (213, 214), (228, 266),
        (287, 310), (316, 341),
    ],
    "one piece": [
        (54, 61), (131, 143), (196, 206), (220, 227),
        (279, 283), (291, 292), (303, 336), (382, 384),
        (427, 456), (492, 516), (575, 578), (590, 591),
    ],
    "dragon ball z": [
        (108, 117), (125, 126), (139, 141),
        (166, 169), (172, 194), (200, 202),
    ],
}

# ── Manga chapter map ──────────────────────────────────────────────────────────
# Approximate chapter where the anime ends, keyed by lowercased canonical title.
# end_chapter=None → ongoing; use the note field for guidance.

_MANGA_CHAPTER_MAP: dict[str, dict] = {
    "naruto": {
        "end_chapter": 244,
        "note": (
            "The Naruto (Part 1) anime covers manga chapters 1–244 (volumes 1–27). "
            "Naruto: Shippuden picks up at chapter 245 and covers through chapter 700."
        ),
    },
    "naruto: shippuden": {
        "end_chapter": 700,
        "note": (
            "Naruto: Shippuden covers manga chapters 245–700. "
            "The manga concludes at chapter 700 + epilogue (700.5). "
            "Boruto continues in the Boruto manga series."
        ),
    },
    "one piece": {
        "end_chapter": None,
        "note": (
            "One Piece is ongoing. The anime typically runs 60–80 chapters behind "
            "the current manga. Check the latest episode-to-chapter guide for the "
            "current sync point."
        ),
    },
    "bleach": {
        "end_chapter": 479,
        "note": (
            "The original Bleach anime (2004–2012) covered chapters 1–479. "
            "Bleach: Thousand-Year Blood War adapts chapters 480–686. "
            "The manga ends at chapter 686."
        ),
    },
    "bleach: thousand-year blood war": {
        "end_chapter": 686,
        "note": (
            "Bleach TYBW fully adapts the Thousand-Year Blood War arc (ch 480–686). "
            "The manga ends at chapter 686."
        ),
    },
    "jujutsu kaisen": {
        "end_chapter": None,
        "note": (
            "Jujutsu Kaisen is ongoing. Each 12-episode cour covers roughly "
            "22–25 manga chapters. Check the current season's ending episode "
            "against a chapter guide to find your pickup point."
        ),
    },
    "attack on titan": {
        "end_chapter": 139,
        "note": (
            "The anime fully adapted the manga (chapters 1–139, volumes 1–34). "
            "No additional manga content exists after the finale."
        ),
    },
    "demon slayer": {
        "end_chapter": 205,
        "note": (
            "Demon Slayer: Kimetsu no Yaiba fully adapted the manga (205 chapters). "
            "No additional manga content remains after the anime's conclusion."
        ),
    },
    "demon slayer: kimetsu no yaiba": {
        "end_chapter": 205,
        "note": (
            "The anime fully adapted the manga (205 chapters). "
            "No additional manga content remains."
        ),
    },
    "fullmetal alchemist: brotherhood": {
        "end_chapter": 108,
        "note": (
            "Brotherhood faithfully adapts all 108 manga chapters plus bonus extras. "
            "No additional manga content exists after the finale."
        ),
    },
    "my hero academia": {
        "end_chapter": None,
        "note": (
            "My Hero Academia is finished in the manga (430 chapters). "
            "The anime typically runs 20–30 chapters behind. "
            "Check the current season's ending episode against a chapter guide."
        ),
    },
    "dragon ball": {
        "end_chapter": 194,
        "note": (
            "The Dragon Ball anime covers manga chapters 1–194 (volumes 1–16). "
            "Dragon Ball Z picks up at chapter 195."
        ),
    },
    "dragon ball z": {
        "end_chapter": 519,
        "note": (
            "Dragon Ball Z covers manga chapters 195–519. "
            "Dragon Ball Super continues in its own manga series (separate from the anime)."
        ),
    },
    "vinland saga": {
        "end_chapter": None,
        "note": (
            "Vinland Saga is ongoing. Season 1 covered chapters 1–54, "
            "Season 2 covered chapters 55–100. "
            "Continue from the next chapter after your last-watched episode."
        ),
    },
    "hunter x hunter": {
        "end_chapter": 339,
        "note": (
            "The 2011 anime covers chapters 1–339. "
            "The manga (on extended hiatus) has ~400 chapters. "
            "Start from chapter 340 for manga-only content."
        ),
    },
    "dr. stone": {
        "end_chapter": None,
        "note": (
            "Dr. Stone manga concluded at chapter 232. "
            "Check which arc the anime last covered to find your pickup chapter."
        ),
    },
    "frieren: beyond journey's end": {
        "end_chapter": None,
        "note": (
            "Frieren: Beyond Journey's End is ongoing in the manga. "
            "The anime covered the early arcs; check the last animated chapter "
            "using an episode-to-chapter guide."
        ),
    },
}


# ── AniList franchise GraphQL query ──────────────────────────────────────────

_FRANCHISE_QUERY = """
query ($search: String) {
  Media(search: $search, type: ANIME, isAdult: false) {
    id
    title { romaji english native }
    format
    episodes
    status
    season
    seasonYear
    source
    relations {
      edges {
        relationType(version: 2)
        node {
          id
          title { romaji english }
          type
          format
          episodes
          status
          season
          seasonYear
        }
      }
    }
  }
}
"""

_FORMAT_LABELS: dict[str, str] = {
    "TV":       "TV Series",
    "TV_SHORT": "TV Short",
    "MOVIE":    "Movie",
    "SPECIAL":  "Special",
    "OVA":      "OVA",
    "ONA":      "ONA",
    "MUSIC":    "Music",
    "MANGA":    "Manga",
    "NOVEL":    "Light Novel",
    "ONE_SHOT": "One-Shot",
}

_STATUS_LABELS: dict[str, str] = {
    "FINISHED":         "Finished",
    "RELEASING":        "Airing",
    "NOT_YET_RELEASED": "Upcoming",
    "CANCELLED":        "Cancelled",
    "HIATUS":           "On Hiatus",
}

_SOURCE_LABELS: dict[str, str] = {
    "MANGA":        "Manga",
    "LIGHT_NOVEL":  "Light Novel",
    "VISUAL_NOVEL": "Visual Novel",
    "ORIGINAL":     "Original",
    "NOVEL":        "Novel",
    "WEB_MANGA":    "Web Manga",
}

# Relation types that represent distinct watchable / readable works
_VIEWABLE_RELATIONS: frozenset[str] = frozenset({
    "SEQUEL", "PREQUEL", "SIDE_STORY", "SPIN_OFF",
    "ALTERNATIVE", "SUMMARY", "COMPILATION",
})

# Source / adaptation relations (not directly watchable in the same format)
_SOURCE_RELATIONS: frozenset[str] = frozenset({
    "SOURCE", "ADAPTATION",
})

# Main narrative spine
_MAIN_STORY_RELATIONS: frozenset[str] = frozenset({
    "PREQUEL", "SEQUEL",
})

# Optional / supplementary
_OPTIONAL_RELATIONS: frozenset[str] = frozenset({
    "SIDE_STORY", "SPIN_OFF", "ALTERNATIVE", "SUMMARY", "COMPILATION",
})


# ── Dataclasses ────────────────────────────────────────────────────────────────

@dataclass
class ResolveResult:
    """Outcome of alias resolution for a single title query."""
    resolved_title: str | None   # canonical title for search; None if ambiguous
    original_query: str
    was_alias: bool              # True when an alias mapping was applied
    ambiguous: bool = False
    clarification: str | None = None  # question to ask the user if ambiguous


@dataclass
class FranchiseEntry:
    """One work in a franchise (the queried root or a related work)."""
    title: str
    relation: str        # "ROOT" | "SEQUEL" | "PREQUEL" | "SIDE_STORY" | …
    media_type: str      # "ANIME" | "MANGA" | "NOVEL" | …
    fmt: str             # human-readable: "TV Series" | "Movie" | "OVA" | …
    episodes: int | None
    status: str | None
    year: int | None
    is_main_story: bool  # True for ROOT / PREQUEL / SEQUEL
    is_optional: bool    # True for side stories, movies, OVAs, specials
    anilist_id: int | None = None


@dataclass
class FranchiseManifest:
    """Complete franchise view for one title."""
    canonical_title: str
    root: FranchiseEntry | None          # the queried entry itself
    entries: list[FranchiseEntry]        # related works
    found: bool = True
    source_material: str | None = None  # "Manga" | "Light Novel" | "Original" | …


@dataclass
class ContinuationItem:
    """One step in a watch or read order sequence."""
    order: int
    title: str
    fmt: str
    episodes: int | None
    year: int | None
    is_optional: bool
    filler_ranges: list[tuple[int, int]] = field(default_factory=list)
    notes: str | None = None


@dataclass
class ContinuationPlan:
    """Structured output for any continuation / order intent."""
    canonical_title: str
    order_type: str                       # "watch_order" | "manga_continuation" | "canon_only" | "filler_skipped"
    sequence: list[ContinuationItem]
    starting_chapter: int | None = None  # for manga_continuation
    manga_note: str | None = None
    general_note: str | None = None


@dataclass
class IntelligenceResult:
    """Top-level structured output from the Anime Intelligence Core."""
    original_query: str
    intent: str                    # "watch_order" | "manga_continuation" | "resolve"
    resolved_title: str | None
    ambiguous: bool
    clarification: str | None      # set when ambiguous=True
    franchise: FranchiseManifest | None
    continuation: ContinuationPlan | None


# ── Anime Resolver ─────────────────────────────────────────────────────────────

class AnimeResolver:
    """
    Normalises anime queries: aliases, abbreviations, punctuation, casing.

    Resolution order:
      1. Exact alias match after normalisation
      2. Ambiguous-table check with context-keyword disambiguation
      3. Pass-through — AniList's fuzzy search handles typos / partial names
    """

    _STOP_RE = re.compile("|".join(_STOP_PATTERNS), flags=re.IGNORECASE)

    def extract_title(self, query: str) -> str:
        """
        Strip intent-related phrases so only the anime title remains.

        "Naruto watch order"      → "Naruto"
        "dbz filler skipped"      → "dbz"
        "jjk manga continuation"  → "jjk"
        """
        stripped = self._STOP_RE.sub("", query).strip()
        return stripped if stripped else query.strip()

    def resolve(self, title_query: str) -> ResolveResult:
        """
        Normalise and resolve a title string via the alias table.

        Returns ResolveResult.ambiguous=True with a clarification question
        when the alias is genuinely ambiguous without additional context.

        Resolution order:
          1. Exact full-string alias match
          2. Exact full-string ambiguous-table match
          3. First-word ambiguous-table match (e.g. "ds stone" → "ds" ambiguous
             table → "stone" keyword → Dr. Stone)
          4. Pass-through to AniList fuzzy search
        """
        original = title_query.strip()
        norm = _normalise(original)

        # 1. Exact alias match
        if norm in _ALIAS_TABLE:
            target = _ALIAS_TABLE[norm]
            return ResolveResult(
                resolved_title=target,
                original_query=original,
                was_alias=(target.lower() != norm),
            )

        # 2. Exact ambiguous-table match
        if norm in _AMBIGUOUS_TABLE:
            return _resolve_ambiguous(norm, original)

        # 3. First-word ambiguous-table match with context keywords.
        #    Handles queries like "ds stone" (first word "ds" is ambiguous;
        #    remaining word "stone" disambiguates to Dr. Stone).
        words = norm.split()
        if words and words[0] in _AMBIGUOUS_TABLE:
            return _resolve_ambiguous(words[0], original)

        # 4. Pass-through — AniList fuzzy search handles typos / partial names
        return ResolveResult(
            resolved_title=original,
            original_query=original,
            was_alias=False,
        )


def _normalise(text: str) -> str:
    """Lowercase, hyphen/underscore → space, strip punctuation, collapse whitespace."""
    text = text.lower()
    text = re.sub(r"[-_]", " ", text)
    text = re.sub(r"[^\w\s]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _resolve_ambiguous(norm: str, original: str) -> ResolveResult:
    entry = _AMBIGUOUS_TABLE[norm]
    for target, keywords in entry["keywords"].items():
        if any(kw in original.lower() for kw in keywords):
            return ResolveResult(
                resolved_title=target,
                original_query=original,
                was_alias=True,
            )
    return ResolveResult(
        resolved_title=None,
        original_query=original,
        was_alias=False,
        ambiguous=True,
        clarification=entry["question"],
    )


# ── Franchise Service ──────────────────────────────────────────────────────────

class FranchiseService:
    """
    Fetches full AniList relation graph for a title and returns a FranchiseManifest.

    Uses asyncio.to_thread so the blocking requests call does not stall the
    event loop.  Never raises — returns FranchiseManifest(found=False) on error.
    """

    def _fetch_sync(self, search: str) -> dict:
        resp = requests.post(
            _ANILIST_URL,
            json={"query": _FRANCHISE_QUERY, "variables": {"search": search}},
            timeout=_REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()

    async def build(self, canonical_title: str) -> FranchiseManifest:
        try:
            data = await asyncio.to_thread(self._fetch_sync, canonical_title)
        except Exception as exc:
            logger.warning(
                "FranchiseService: AniList error for %r: %s", canonical_title, exc
            )
            return FranchiseManifest(
                canonical_title=canonical_title,
                root=None,
                entries=[],
                found=False,
            )

        media = (data.get("data") or {}).get("Media")
        if not media:
            logger.info(
                "FranchiseService: no Media found for %r", canonical_title
            )
            return FranchiseManifest(
                canonical_title=canonical_title,
                root=None,
                entries=[],
                found=False,
            )

        return _parse_franchise(canonical_title, media)


def _parse_franchise(canonical_title: str, media: dict) -> FranchiseManifest:
    title_obj = media.get("title") or {}
    display = (
        title_obj.get("english")
        or title_obj.get("romaji")
        or canonical_title
    )

    root = FranchiseEntry(
        title=display,
        relation="ROOT",
        media_type="ANIME",
        fmt=_FORMAT_LABELS.get(media.get("format", ""), "TV Series"),
        episodes=media.get("episodes"),
        status=_STATUS_LABELS.get(media.get("status", ""), media.get("status")),
        year=media.get("seasonYear"),
        is_main_story=True,
        is_optional=False,
        anilist_id=media.get("id"),
    )

    source_material = _SOURCE_LABELS.get(media.get("source", ""))

    entries: list[FranchiseEntry] = []
    for edge in (media.get("relations") or {}).get("edges", []):
        rel_type = edge.get("relationType", "")
        node = edge.get("node") or {}
        node_type = node.get("type", "ANIME")
        node_fmt_raw = node.get("format", "")
        node_fmt = _FORMAT_LABELS.get(node_fmt_raw, node_fmt_raw or "Unknown")

        # Skip pure character-link edges — not a watchable/readable work
        if rel_type == "CHARACTER":
            continue

        node_title_obj = node.get("title") or {}
        node_title = (
            node_title_obj.get("english")
            or node_title_obj.get("romaji")
            or "Unknown"
        )

        is_main   = rel_type in _MAIN_STORY_RELATIONS and node_type == "ANIME"
        is_source = rel_type in _SOURCE_RELATIONS
        is_opt    = (
            rel_type in _OPTIONAL_RELATIONS
            or node_fmt_raw in ("SPECIAL", "OVA", "ONA", "MOVIE")
        ) and not is_main

        # Only include works we can say something meaningful about
        if not (is_main or is_opt or is_source or rel_type in _VIEWABLE_RELATIONS):
            continue

        entries.append(FranchiseEntry(
            title=node_title,
            relation=rel_type,
            media_type=node_type,
            fmt=node_fmt,
            episodes=node.get("episodes"),
            status=_STATUS_LABELS.get(node.get("status", ""), node.get("status")),
            year=node.get("seasonYear"),
            is_main_story=is_main,
            is_optional=is_opt or is_source,
            anilist_id=node.get("id"),
        ))

    return FranchiseManifest(
        canonical_title=display,
        root=root,
        entries=entries,
        found=True,
        source_material=source_material,
    )


# ── Continuation Planner ───────────────────────────────────────────────────────

class ContinuationPlanner:
    """
    Builds a ContinuationPlan from a FranchiseManifest.

    Supports:
      watch_order        — main story first, optional content after
      manga_continuation — chapter to start after the anime
      canon_only         — main story only, compilations/summaries excluded
      filler_skipped     — watch_order with filler episode ranges attached
    """

    def plan(self, manifest: FranchiseManifest, order_type: str) -> ContinuationPlan:
        if order_type == "manga_continuation":
            return self._manga_continuation(manifest)
        if order_type == "canon_only":
            return self._canon_only(manifest)
        if order_type == "filler_skipped":
            return self._filler_skipped(manifest)
        return self._watch_order(manifest)

    # ── Order builders ────────────────────────────────────────────────────────

    def _watch_order(self, manifest: FranchiseManifest) -> ContinuationPlan:
        main, optional = _split_entries(manifest)
        sequence: list[ContinuationItem] = []
        idx = 1

        for e in main:
            sequence.append(ContinuationItem(
                order=idx, title=e.title, fmt=e.fmt,
                episodes=e.episodes, year=e.year,
                is_optional=False, notes=e.status,
            ))
            idx += 1

        for e in optional:
            rel_label = e.relation.replace("_", " ").title()
            notes = f"{rel_label} · {e.status}" if e.status else rel_label
            sequence.append(ContinuationItem(
                order=idx, title=e.title, fmt=e.fmt,
                episodes=e.episodes, year=e.year,
                is_optional=True, notes=notes,
            ))
            idx += 1

        return ContinuationPlan(
            canonical_title=manifest.canonical_title,
            order_type="watch_order",
            sequence=sequence,
            general_note=_source_note(manifest),
        )

    def _canon_only(self, manifest: FranchiseManifest) -> ContinuationPlan:
        main, _ = _split_entries(manifest)
        filtered = [e for e in main if e.relation not in ("SUMMARY", "COMPILATION")]
        sequence = [
            ContinuationItem(
                order=i + 1, title=e.title, fmt=e.fmt,
                episodes=e.episodes, year=e.year,
                is_optional=False, notes=e.status,
            )
            for i, e in enumerate(filtered)
        ]
        return ContinuationPlan(
            canonical_title=manifest.canonical_title,
            order_type="canon_only",
            sequence=sequence,
            general_note="Canon-only order — compilations and summaries excluded.",
        )

    def _filler_skipped(self, manifest: FranchiseManifest) -> ContinuationPlan:
        plan = self._watch_order(manifest)
        plan.order_type = "filler_skipped"
        for item in plan.sequence:
            ranges = _FILLER_RANGES.get(item.title.lower())
            if ranges:
                item.filler_ranges = ranges
                count = len(ranges)
                item.notes = (item.notes or "") + f" · {count} filler block(s) to skip"
        plan.general_note = (
            "Filler ranges shown per entry (inclusive episode numbers). "
            "These episodes are non-canon and can be skipped without losing story continuity."
        )
        return plan

    def _manga_continuation(self, manifest: FranchiseManifest) -> ContinuationPlan:
        key = manifest.canonical_title.lower()
        chapter_data = _MANGA_CHAPTER_MAP.get(key)

        # Fuzzy key match (handles slight title differences)
        if chapter_data is None:
            for k, v in _MANGA_CHAPTER_MAP.items():
                if k in key or key in k:
                    chapter_data = v
                    break

        starting_chapter = chapter_data["end_chapter"] if chapter_data else None
        manga_note = chapter_data["note"] if chapter_data else (
            f"No chapter map is available for {manifest.canonical_title!r}. "
            "Use an episode-to-chapter guide for your series to find your pickup point."
        )

        return ContinuationPlan(
            canonical_title=manifest.canonical_title,
            order_type="manga_continuation",
            sequence=[],
            starting_chapter=starting_chapter,
            manga_note=manga_note,
        )


# ── Shared helpers ─────────────────────────────────────────────────────────────

def _split_entries(
    manifest: FranchiseManifest,
) -> tuple[list[FranchiseEntry], list[FranchiseEntry]]:
    """
    Partition manifest into (main_story, optional), each sorted by year.

    Main story: ROOT + PREQUEL/SEQUEL ANIME entries.
    Optional: side stories, movies, OVAs, specials, and non-ANIME source entries.
    """
    all_entries: list[FranchiseEntry] = []
    if manifest.root:
        all_entries.append(manifest.root)
    all_entries.extend(manifest.entries)

    main = sorted(
        [e for e in all_entries if e.is_main_story and e.media_type == "ANIME"],
        key=lambda e: (e.year or 9999),
    )
    optional = sorted(
        [e for e in all_entries if not e.is_main_story and e.media_type == "ANIME"],
        key=lambda e: (e.year or 9999),
    )
    return main, optional


def _source_note(manifest: FranchiseManifest) -> str | None:
    if manifest.source_material and manifest.source_material != "Original":
        return f"Source material: {manifest.source_material}"
    return None


# ── Anime Intelligence Facade ──────────────────────────────────────────────────

class AnimeIntelligence:
    """
    Public entry point for the Anime Intelligence Core.

    Usage:
        result = await intelligence_service.resolve_and_plan(
            query="Naruto watch order",
            order_type="watch_order",
        )
    """

    def __init__(self) -> None:
        self._resolver = AnimeResolver()
        self._franchise = FranchiseService()
        self._planner   = ContinuationPlanner()

    async def resolve_and_plan(
        self,
        query: str,
        order_type: str = "watch_order",
    ) -> IntelligenceResult:
        """
        Full pipeline: extract title → resolve alias → franchise manifest → continuation plan.

        Args:
            query:      Full user message (e.g. "Naruto watch order")
            order_type: "watch_order" | "manga_continuation" | "canon_only" | "filler_skipped"

        Returns:
            IntelligenceResult — always; never raises.
        """
        # 1. Strip intent words → isolate the title
        title_query = self._resolver.extract_title(query)
        logger.info(
            "AnimeIntelligence | query=%r → title=%r | order_type=%s",
            query, title_query, order_type,
        )

        # 2. Alias / abbreviation resolution
        resolve = self._resolver.resolve(title_query)
        logger.info(
            "AnimeIntelligence | resolved=%r | was_alias=%s | ambiguous=%s",
            resolve.resolved_title, resolve.was_alias, resolve.ambiguous,
        )

        if resolve.ambiguous:
            return IntelligenceResult(
                original_query=query,
                intent=order_type,
                resolved_title=None,
                ambiguous=True,
                clarification=resolve.clarification,
                franchise=None,
                continuation=None,
            )

        canonical = resolve.resolved_title or title_query

        # 3. Franchise manifest
        try:
            franchise = await self._franchise.build(canonical)
        except Exception as exc:
            logger.warning(
                "AnimeIntelligence | franchise build failed for %r: %s", canonical, exc
            )
            franchise = FranchiseManifest(
                canonical_title=canonical, root=None, entries=[], found=False
            )

        # 4. Continuation plan
        try:
            continuation = self._planner.plan(franchise, order_type)
        except Exception as exc:
            logger.warning(
                "AnimeIntelligence | planner failed for %r: %s", canonical, exc
            )
            continuation = None

        return IntelligenceResult(
            original_query=query,
            intent=order_type,
            resolved_title=franchise.canonical_title if franchise.found else canonical,
            ambiguous=False,
            clarification=None,
            franchise=franchise,
            continuation=continuation,
        )

    async def resolve_only(self, query: str) -> ResolveResult:
        """Alias resolution only — no franchise or continuation data."""
        title_query = self._resolver.extract_title(query)
        return self._resolver.resolve(title_query)


# ── Module singleton ───────────────────────────────────────────────────────────

intelligence_service = AnimeIntelligence()
"""
Shared AnimeIntelligence instance.
Import and use this; do not construct your own.
"""
