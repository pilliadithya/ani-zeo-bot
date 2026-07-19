"""
AnimeSearchService — dual-API anime lookup with TTL caching and structured results.

Search strategy
───────────────
  user query
      │
      ├─ normalise → cache lookup
      │       └─ HIT  → return (cached=True)
      │
      ├─ AniList  Media(search:)   [primary]
      │       └─ FOUND → cache & return
      │
      ├─ Jikan v4 /anime?q=        [fallback — different fuzzy engine]
      │       └─ FOUND → cache & return
      │
      └─ neither found → AnimeSearchResult(found=False, source="not_found")

Why two APIs?
─────────────
  AniList  — rich metadata, canonical titles, trailer, streaming links, relations.
             Its fuzzy matcher handles partial names, romanised names, some typos.
  Jikan v4 — MAL data.  Different tokeniser catches alternative romanisations
             (e.g. "Solo Levelling" / "Ore dake Level Up na Ken") that AniList
             might miss.

What callers receive
────────────────────
  Always an AnimeSearchResult dataclass.  Callers MUST check result.found
  before using metadata fields.  Every field is Optional except found/query/source.
"""
from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import logging
import re
import time
from dataclasses import dataclass, field

import requests

logger = logging.getLogger(__name__)

# ── Constants ──────────────────────────────────────────────────────────────────

_ANILIST_URL:    str = "https://graphql.anilist.co"
_JIKAN_BASE:     str = "https://api.jikan.moe/v4"

_CACHE_TTL:      int = 3_600   # 1 hour for positive results
_NOTFOUND_TTL:   int = 600     # 10 minutes for negative results (user may fix typo)
_REQUEST_TIMEOUT: int = 15     # seconds per HTTP call

_STREAMING_SITES: frozenset[str] = frozenset({
    "Crunchyroll", "Netflix", "Amazon Prime Video", "Prime Video",
    "Disney Plus", "Disney+", "Hulu", "HIDIVE", "Muse Asia",
    "Ani-One", "Ani-One Asia", "Funimation", "VRV", "Bilibili",
})

_STATUS_MAP: dict[str, str] = {
    "FINISHED":         "Finished",
    "RELEASING":        "Currently Airing",
    "NOT_YET_RELEASED": "Upcoming",
    "CANCELLED":        "Cancelled",
    "HIATUS":           "On Hiatus",
}

_SOURCE_MAP: dict[str, str] = {
    "MANGA":        "Manga",
    "LIGHT_NOVEL":  "Light Novel",
    "VISUAL_NOVEL": "Visual Novel",
    "VIDEO_GAME":   "Video Game",
    "ORIGINAL":     "Original",
    "NOVEL":        "Novel",
    "ANIME":        "Anime",
    "WEB_MANGA":    "Web Manga",
    "BOOK":         "Book",
    "COMIC":        "Comic",
    "ONE_SHOT":     "One-Shot",
    "OTHER":        "Other",
}

_EXCLUDED_GENRES: frozenset[str] = frozenset({"hentai", "erotica"})

# Same GraphQL fields as the /search command in bot.py — keeping them in sync
# ensures both paths return identical metadata shapes.
_ANILIST_QUERY = """
query ($search: String) {
  Media(search: $search, type: ANIME, isAdult: false) {
    id
    title { romaji english native }
    coverImage { large }
    averageScore popularity
    rankings { rank type allTime }
    episodes status season seasonYear
    genres
    studios(isMain: true) { nodes { name } }
    source duration
    description(asHtml: false)
    trailer { id site }
    externalLinks { url site type }
    relations {
      edges {
        relationType(version: 2)
        node { title { romaji english } type }
      }
    }
  }
}
"""


# ── Result dataclass ───────────────────────────────────────────────────────────

@dataclass
class AnimeSearchResult:
    """
    Structured result for a single anime lookup.

    Always returned by AnimeSearchService.search() — callers check
    `found` before accessing metadata fields.

    Scores use AniList scale (0–100).  Jikan scores (0–10) are multiplied
    by 10 on ingestion so callers never need to branch on source.
    """

    # ── Required ──────────────────────────────────────────────────────────────
    found:   bool            # False → all metadata fields are None/empty
    query:   str             # original user query (unmodified)
    source:  str             # "anilist" | "jikan" | "not_found"
    cached:  bool = False    # True when returned from in-process cache

    # ── Identity ──────────────────────────────────────────────────────────────
    title_romaji:  str | None = None   # e.g. "Shingeki no Kyojin"
    title_english: str | None = None   # e.g. "Attack on Titan"
    title_native:  str | None = None   # e.g. "進撃の巨人"
    cover_url:     str | None = None

    # ── Statistics ────────────────────────────────────────────────────────────
    score:      float | None = None    # 0–100 (AniList scale)
    rank:       str   | None = None    # e.g. "#42"
    popularity: int   | None = None    # lower = more popular

    # ── Metadata ──────────────────────────────────────────────────────────────
    episodes:        int  | None = None
    status:          str  | None = None
    season:          str  | None = None   # e.g. "Fall 2024"
    source_material: str  | None = None   # e.g. "Manga"
    duration:        str  | None = None   # e.g. "24 min/ep"
    synopsis:        str  | None = None   # HTML stripped, max 900 chars
    trailer_url:     str  | None = None

    # ── Lists ─────────────────────────────────────────────────────────────────
    genres:              list[str]  = field(default_factory=list)
    studios:             list[str]  = field(default_factory=list)
    streaming_platforms: list[str]  = field(default_factory=list)
    # Each relation: {"type": "PREQUEL"|"SEQUEL", "title": str}
    relations:           list[dict] = field(default_factory=list)

    # ── Derived ───────────────────────────────────────────────────────────────

    @property
    def display_title(self) -> str:
        """Best available human-readable title for display."""
        return self.title_english or self.title_romaji or self.query

    @property
    def score_display(self) -> str:
        """Formatted score string e.g. '8.5/10', or 'N/A'."""
        if not self.score:
            return "N/A"
        return f"{self.score / 10:.1f}/10"

    def to_dict(self) -> dict:
        """Serialise to a plain dict (used by tools layer)."""
        return dataclasses.asdict(self)


# ── Cache ──────────────────────────────────────────────────────────────────────

class _SearchCache:
    """
    In-memory TTL cache keyed on a normalised query hash.

    Normalisation: lowercase → strip punctuation → collapse whitespace.
    This ensures "Naruto!", "naruto", and "  NARUTO  " all share the same
    cache slot.

    Positive results: 1-hour TTL.
    Negative results: 10-minute TTL (lets users retry after fixing typos
    without waiting a full hour).
    """

    def __init__(self) -> None:
        # value: (result, expires_at_monotonic)
        self._store: dict[str, tuple[AnimeSearchResult, float]] = {}

    @staticmethod
    def _normalise(query: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"[^\w\s]", "", query.lower())).strip()

    @staticmethod
    def _key(query: str) -> str:
        norm = _SearchCache._normalise(query)
        return hashlib.sha256(norm.encode()).hexdigest()[:24]

    def get(self, query: str) -> AnimeSearchResult | None:
        key   = self._key(query)
        entry = self._store.get(key)
        if entry is None:
            return None
        result, expires_at = entry
        if time.monotonic() > expires_at:
            del self._store[key]
            return None
        return result

    def set(self, query: str, result: AnimeSearchResult, ttl: int = _CACHE_TTL) -> None:
        key = self._key(query)
        self._store[key] = (result, time.monotonic() + ttl)

    def size(self) -> int:
        """Number of live (non-expired) cache entries."""
        now = time.monotonic()
        return sum(1 for _, exp in self._store.values() if exp > now)


# ── AniList client ─────────────────────────────────────────────────────────────

class _AniListClient:
    """
    Async AniList GraphQL client.

    Uses requests in a thread pool (asyncio.to_thread) to stay consistent
    with the existing bot.py HTTP pattern and avoid adding httpx as a dep.

    AniList's Media(search:) performs server-side fuzzy matching across
    romaji, English, and native title fields.  It handles:
      - Partial names      ("Attack" → "Attack on Titan")
      - Romanised names    ("Shingeki no Kyojin")
      - Alternative titles  (synonyms stored in AniList)
      - Mild typos         (server-side Levenshtein)
    """

    def _fetch_sync(self, query: str) -> dict:
        r = requests.post(
            _ANILIST_URL,
            json={"query": _ANILIST_QUERY, "variables": {"search": query}},
            timeout=_REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        return r.json()

    async def search(self, query: str) -> AnimeSearchResult | None:
        """
        Search AniList.  Returns a populated result on success,
        None on API error or no match.  Never raises.
        """
        try:
            data = await asyncio.to_thread(self._fetch_sync, query)
        except requests.Timeout:
            logger.warning("AniList timeout | query=%r", query)
            return None
        except requests.HTTPError as exc:
            logger.warning("AniList HTTP error | query=%r | %s", query, exc)
            return None
        except requests.RequestException as exc:
            logger.warning("AniList request error | query=%r | %s", query, exc)
            return None
        except Exception as exc:
            logger.error("AniList unexpected error | query=%r | %s: %s",
                         query, type(exc).__name__, exc)
            return None

        media = (data.get("data") or {}).get("Media")
        if not media:
            errors = data.get("errors")
            if errors:
                logger.debug("AniList errors | query=%r | %s", query, errors)
            else:
                logger.debug("AniList: no Media in response | query=%r", query)
            return None

        return self._build(query, media)

    @staticmethod
    def _build(query: str, media: dict) -> AnimeSearchResult:
        title    = media.get("title") or {}
        rankings = media.get("rankings") or []

        # All-time rated rank
        rated_entry = next(
            (r for r in rankings if r.get("allTime") and r.get("type") == "RATED"),
            None,
        )

        # Streaming platforms from external links
        ext_links = media.get("externalLinks") or []
        platforms = list(dict.fromkeys(
            lnk["site"]
            for lnk in ext_links
            if lnk.get("site") in _STREAMING_SITES
        ))

        # PREQUEL / SEQUEL relations
        rel_edges = (media.get("relations") or {}).get("edges") or []
        relations: list[dict] = []
        for edge in rel_edges:
            rt   = edge.get("relationType", "")
            node = edge.get("node") or {}
            if rt in ("PREQUEL", "SEQUEL") and node.get("type") == "ANIME":
                t = node.get("title", {}).get("english") or node.get("title", {}).get("romaji")
                if t:
                    relations.append({"type": rt, "title": t})

        # YouTube trailer
        trailer     = media.get("trailer") or {}
        trailer_url: str | None = None
        if trailer.get("site") == "youtube" and trailer.get("id"):
            trailer_url = f"https://www.youtube.com/watch?v={trailer['id']}"

        # Season label
        season_label: str | None = None
        if media.get("season") and media.get("seasonYear"):
            season_label = f"{media['season'].capitalize()} {media['seasonYear']}"

        # Synopsis (strip HTML, cap at 900 chars)
        synopsis = _strip_html(media.get("description") or "")
        if len(synopsis) > 900:
            synopsis = synopsis[:900] + "…"

        # Studios
        studios = [
            n["name"]
            for n in (media.get("studios") or {}).get("nodes", [])
        ]

        return AnimeSearchResult(
            found=True,
            query=query,
            source="anilist",

            title_romaji=title.get("romaji"),
            title_english=title.get("english"),
            title_native=title.get("native"),
            cover_url=(media.get("coverImage") or {}).get("large"),

            score=media.get("averageScore"),
            rank=f"#{rated_entry['rank']}" if rated_entry else None,
            popularity=media.get("popularity"),

            episodes=media.get("episodes"),
            status=_STATUS_MAP.get(media.get("status", ""), media.get("status")),
            season=season_label,
            source_material=_SOURCE_MAP.get(media.get("source", ""), media.get("source")),
            duration=f"{media['duration']} min/ep" if media.get("duration") else None,
            synopsis=synopsis or None,
            trailer_url=trailer_url,

            genres=media.get("genres") or [],
            studios=studios,
            streaming_platforms=platforms,
            relations=relations,
        )


# ── Jikan client ───────────────────────────────────────────────────────────────

class _JikanClient:
    """
    Async Jikan v4 (MAL) REST client.  Used as fallback when AniList returns
    no result.

    MAL's search tokeniser handles some alternative romanisations that AniList
    misses — e.g. "Solo Levelling" (British) vs "Ore dake Level Up na Ken"
    (Japanese romaji).  The two APIs complement each other.

    Score conversion: MAL uses 0–10; we multiply by 10 to match AniList's
    0–100 scale so callers never branch on source.
    """

    def _fetch_sync(self, query: str) -> dict:
        r = requests.get(
            f"{_JIKAN_BASE}/anime",
            params={"q": query, "limit": 1, "sfw": "true"},
            timeout=_REQUEST_TIMEOUT,
        )
        r.raise_for_status()
        return r.json()

    async def search(self, query: str) -> AnimeSearchResult | None:
        """
        Search Jikan (MAL).  Returns a populated result on success,
        None on API error or no match.  Never raises.
        """
        try:
            data = await asyncio.to_thread(self._fetch_sync, query)
        except requests.Timeout:
            logger.warning("Jikan timeout | query=%r", query)
            return None
        except requests.HTTPError as exc:
            logger.warning("Jikan HTTP error | query=%r | %s", query, exc)
            return None
        except requests.RequestException as exc:
            logger.warning("Jikan request error | query=%r | %s", query, exc)
            return None
        except Exception as exc:
            logger.error("Jikan unexpected error | query=%r | %s: %s",
                         query, type(exc).__name__, exc)
            return None

        items = data.get("data") or []
        if not items:
            logger.debug("Jikan: empty data list | query=%r", query)
            return None

        return self._build(query, items[0])

    @staticmethod
    def _build(query: str, item: dict) -> AnimeSearchResult:
        # Filter excluded genres
        genres = [
            g["name"]
            for g in (item.get("genres") or [])
            if g.get("name", "").lower() not in _EXCLUDED_GENRES
        ]
        studios = [s["name"] for s in (item.get("studios") or [])]

        # Cover image (prefer large)
        imgs = (item.get("images") or {}).get("jpg") or {}
        cover_url = imgs.get("large_image_url") or imgs.get("image_url")

        # Trailer URL
        trailer     = item.get("trailer") or {}
        trailer_url = trailer.get("url") or None
        # Jikan sometimes returns embed URLs — convert to watch URLs
        if trailer_url and "embed" in trailer_url:
            video_id = re.search(r"embed/([^?&]+)", trailer_url)
            if video_id:
                trailer_url = f"https://www.youtube.com/watch?v={video_id.group(1)}"

        # Season label
        season_label: str | None = None
        if item.get("season") and item.get("year"):
            season_label = f"{str(item['season']).capitalize()} {item['year']}"

        # Rank / popularity
        rank       = f"#{item['rank']}"  if item.get("rank")       else None
        popularity =  item.get("popularity")

        # Score: MAL 0–10 → AniList 0–100
        raw_score = item.get("score")
        score     = round(raw_score * 10) if raw_score else None

        # Duration: Jikan returns "23 min per ep" — normalise to "23 min/ep"
        duration_raw = item.get("duration") or ""
        duration     = re.sub(r"\bper ep\b", "min/ep", duration_raw).strip() or None
        if duration and "min/ep" not in duration and "min" in duration:
            duration = re.sub(r"\s*min\b", " min/ep", duration)

        # Synopsis
        synopsis = item.get("synopsis") or ""
        if len(synopsis) > 900:
            synopsis = synopsis[:900] + "…"

        return AnimeSearchResult(
            found=True,
            query=query,
            source="jikan",

            title_romaji=item.get("title"),
            title_english=item.get("title_english"),
            title_native=item.get("title_japanese"),
            cover_url=cover_url,

            score=score,
            rank=rank,
            popularity=popularity,

            episodes=item.get("episodes"),
            status=item.get("status"),
            season=season_label,
            source_material=item.get("source"),
            duration=duration,
            synopsis=synopsis or None,
            trailer_url=trailer_url,

            genres=genres,
            studios=studios,
            streaming_platforms=[],   # Jikan streaming varies; omitted for consistency
            relations=[],             # Jikan relations need a separate call; omitted
        )


# ── Service ────────────────────────────────────────────────────────────────────

class AnimeSearchService:
    """
    Public entry point for all anime lookups in Ani Zeo.

    Single instance recommended — holds the shared cache.
    Import the module-level `search_service` singleton rather than
    constructing your own, unless you need an isolated cache for tests.

    Usage:
        from services.anime_search import search_service
        result = await search_service.search("Demon Slayer")
        if result.found:
            print(result.display_title, result.score_display)
        else:
            print("Not found")
    """

    def __init__(self) -> None:
        self._cache   = _SearchCache()
        self._anilist = _AniListClient()
        self._jikan   = _JikanClient()

    async def search(self, query: str) -> AnimeSearchResult:
        """
        Search for an anime by title.

        Four-pass strategy:
          1. In-process TTL cache
          2. AniList  Media(search:)  — primary, rich fuzzy matching
          3. Jikan v4 /anime?q=       — secondary, different tokeniser
          4. Normalized query retry   — collapses British spelling / trailing
             typos (e.g. "Levelling"→"Leveling", "Narutoo"→"Naruto") then
             re-runs passes 2–3 with the cleaned query

        Always returns an AnimeSearchResult — never raises.
        Check result.found before using metadata fields.
        """
        query = query.strip()
        if not query:
            return _NOT_FOUND_EMPTY

        # ── 1. Cache hit ──────────────────────────────────────────────────────
        cached = self._cache.get(query)
        if cached is not None:
            logger.info(
                "Search cache HIT | query=%r | source=%s | title=%r",
                query, cached.source, cached.display_title,
            )
            return dataclasses.replace(cached, cached=True)

        # ── 2. AniList (primary) ──────────────────────────────────────────────
        logger.info("Searching AniList | query=%r", query)
        result = await self._anilist.search(query)

        # ── 3. Jikan fallback ─────────────────────────────────────────────────
        if result is None:
            logger.info("AniList miss → Jikan | query=%r", query)
            result = await self._jikan.search(query)

        # ── 4. Normalized query retry ─────────────────────────────────────────
        # When both APIs fail with the original query, attempt a cleaned variant:
        #   "Solo Levelling" → "Solo Leveling"  (British doubled consonant)
        #   "Narutoo"        → "Naruto"          (trailing duplicate character)
        # Only runs if normalization actually changes the query.
        if result is None:
            normalized = self._normalize_query(query)
            if normalized:
                logger.info(
                    "Both APIs miss → normalized retry | %r → %r",
                    query, normalized,
                )
                result = await self._anilist.search(normalized)
                if result is None:
                    result = await self._jikan.search(normalized)
                if result is not None:
                    # Preserve the original query so callers see what was asked
                    result = dataclasses.replace(result, query=query)

        # ── 5. Not found ──────────────────────────────────────────────────────
        if result is None:
            logger.info("All passes exhausted — not found | query=%r", query)
            nf = AnimeSearchResult(found=False, query=query, source="not_found")
            self._cache.set(query, nf, ttl=_NOTFOUND_TTL)
            return nf

        # ── 6. Cache positive result and return ───────────────────────────────
        logger.info(
            "Search SUCCESS | query=%r | source=%s | title=%r | score=%s",
            query, result.source, result.display_title, result.score_display,
        )
        self._cache.set(query, result)
        return result

    @staticmethod
    def _normalize_query(query: str) -> str | None:
        """
        Produce a 'cleaned' query variant to retry when both primary APIs fail.

        Transformations (applied in order, each is optional):
          1. Collapse doubled consonants — handles British English spelling
             differences stored as American in anime databases:
             "Levelling" → "Leveling",  "Travelling" → "Traveling"
          2. Strip trailing repeated characters — handles trailing-key typos:
             "Narutoo" → "Naruto",  "Bleachh" → "Bleach"

        Returns the cleaned string if it differs from the original, else None.
        The caller skips the retry when None is returned.

        Note: only runs as a last resort — titles that AniList or Jikan find
        directly (e.g. "Fullmetal Alchemist") never reach this function.
        """
        # Step 1: collapse doubled consonants (British → American spelling)
        step1 = re.sub(r'([bcdfghjklmnpqrstvwxyz])\1', r'\1', query,
                       flags=re.IGNORECASE)

        # Step 2: strip trailing doubled characters ("Narutoo" → "Naruto")
        step2 = re.sub(r'(.)\1+$', r'\1', step1)
        return step2 if step2.lower() != query.lower() else None

    def cache_size(self) -> int:
        """Number of live cache entries (for diagnostics)."""
        return self._cache.size()


# ── Utilities ──────────────────────────────────────────────────────────────────

def _strip_html(text: str) -> str:
    """Remove HTML tags and normalise <br> to newlines."""
    if not text:
        return ""
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    return text.strip()


# ── Module-level singleton ─────────────────────────────────────────────────────

_NOT_FOUND_EMPTY = AnimeSearchResult(found=False, query="", source="not_found")

search_service = AnimeSearchService()
"""
Shared AnimeSearchService instance.  Import this; don't construct your own.
One instance = one shared cache = fewer redundant API calls.
"""
