"""
ContextBuilder — converts structured data into clean AI-ready context.

The AI should NEVER receive raw API JSON or internal fields.
This module is the single gate between every data source and every AI provider.

Pipeline
────────
  AnimeSearchResult  +  Intent  +  UserProfile
            │
            ▼
  ContextBuilder.from_search_result()
            │
            ▼
  AIContext  — three clean dataclasses, no raw API fields, no internal IDs
            │
            ▼
  ContextBuilder.to_text()
            │
            ▼
  Plain-text context block  →  appended to SYSTEM_PROMPT  →  AI providers

Design rules
────────────
  - All methods are @classmethods — no instantiation needed.
  - Output is source-agnostic: AniList and Jikan produce identical text.
  - Empty / None values are omitted, never forwarded as "null" or "N/A".
  - Internal IDs, cover_url, cached flag, raw API keys are stripped.
  - The module never imports from ai/, tools/, or bot.py (acyclic deps).

Extensibility
─────────────
  Anime Info:        ContextBuilder.from_search_result()     ← implemented
  Recommendations:   ContextBuilder.build_user_only()        ← implemented
  Character Info:    ContextBuilder.from_character_result()  ← stub (future)
  Watch Order:       ContextBuilder.from_watch_order()       ← stub (future)
  Anime News:        ContextBuilder.from_news_result()       ← stub (future)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from services.intent import Intent

if TYPE_CHECKING:
    from services.anime_search import AnimeSearchResult
    from services.anime_intelligence import IntelligenceResult

from services.anime_news import NewsItem, NewsResult   # runtime import — no circular dep
from services.web_search import WebSearchResult        # runtime import — no circular dep


# ── Intents that warrant an anime-title search before routing ─────────────────
# Add an intent here when its responses benefit from specific title metadata.
# Intentionally conservative: broad intents (recommendations, trending)
# are left out — news/trending use _NEWS_CONTEXT_INTENTS below.
# WATCH_ORDER and MANGA_CONTINUATION are handled by _INTELLIGENCE_INTENTS.

_ANIME_CONTEXT_INTENTS: frozenset[Intent] = frozenset({
    Intent.SEARCH_ANIME,     # "find / search for X"
    Intent.GET_DETAILS,      # "details about X"
    Intent.CHARACTER_LOOKUP, # "who is / voice actor of X"
    Intent.DUB_INFO,         # "is X dubbed"
    Intent.LORE_QUESTION,    # "what happens in X"
    Intent.EXPLANATION,      # "what is X / explain X"
    Intent.OPEN_QUESTION,    # general question mentioning a title
})

# ── Intents handled by the Anime Intelligence Core ────────────────────────────
# These get franchise manifests + continuation plans instead of simple searches.

_INTELLIGENCE_INTENTS: frozenset[Intent] = frozenset({
    Intent.WATCH_ORDER,         # "watch order for X", "where to start X"
    Intent.MANGA_CONTINUATION,  # "manga after anime", "pick up manga for X"
})

# ── Intents that warrant a live news fetch before routing ─────────────────────
# ANIME_NEWS → fetch_latest()   (recent articles from MAL, Anime Corner)
# TRENDING   → fetch_trending() (currently-airing anime sorted by trending score)

_NEWS_CONTEXT_INTENTS: frozenset[Intent] = frozenset({
    Intent.ANIME_NEWS,   # "latest anime news", "what's new in anime"
    Intent.TRENDING,     # "what's trending in anime"
})


# ── Dataclasses ────────────────────────────────────────────────────────────────

@dataclass
class AnimeContext:
    """
    AI-ready anime metadata.

    Stripped of: internal IDs, cover_url, cached flag, raw API field names,
    and any empty value.  Source-agnostic: AniList and Jikan produce the
    same structure after normalisation.

    Fields marked "future" are already in the schema — populated once the
    relevant data source is wired (AniList character/tag queries, etc.).
    """

    # Titles (all optional — display_title falls back gracefully)
    title_english:  str | None = None   # "Attack on Titan"
    title_romaji:   str | None = None   # "Shingeki no Kyojin"
    title_native:   str | None = None   # "進撃の巨人"

    # Content
    synopsis:       str | None = None   # HTML-stripped, max 900 chars

    # Lists — empty list means "not available", never None
    genres:              list[str] = field(default_factory=list)
    main_characters:     list[str] = field(default_factory=list)  # future
    tags:                list[str] = field(default_factory=list)  # future

    # Production
    episodes:        str | None = None   # "25" | "Ongoing" | None
    status:          str | None = None   # "Finished" | "Currently Airing" | …
    studio:          str | None = None   # primary studio only
    season:          str | None = None   # "Fall 2013"
    year:            str | None = None   # "2013"  (extracted from season)
    source_material: str | None = None   # "Manga" | "Light Novel" | …
    duration:        str | None = None   # "24 min/ep"

    # Quality
    rating:          str | None = None   # "9.0/10"  (AniList 0–100 ÷ 10)

    # Access
    trailer_url:         str | None = None
    streaming_platforms: list[str]  = field(default_factory=list)
    available_languages: list[str]  = field(default_factory=list)  # future

    # Relations (formatted strings, not raw dicts)
    relations:       list[str] = field(default_factory=list)   # "➡ Sequel: X"

    # Provenance — always set; tells AI which database was used
    data_source:     str = "unknown"   # "AniList" | "MAL (Jikan)"

    @property
    def display_title(self) -> str:
        """Best available title for display."""
        return self.title_english or self.title_romaji or "Unknown"


@dataclass
class UserContext:
    """
    User preferences passed to the AI for personalisation.

    All fields are optional.  When a field is None, the AI falls back to
    its own defaults (neutral tone, English, no name used).
    """
    nickname:     str | None = None   # from profiles.json
    language:     str | None = None   # "English" | "Tenglish" | "Hinglish" | "Tamilish"
    intent_label: str        = "Unknown"   # human-readable intent category


@dataclass
class AIContext:
    """
    Complete context envelope delivered to every AI provider call.

    The AI receives this instead of raw API payloads, ensuring:
      - No internal IDs or raw API keys
      - Consistent shape regardless of data source (AniList / Jikan / future)
      - User-specific personalisation baked in
      - Only fields the model can actually use in its response

    Callers check `found` before relying on `anime` metadata.
    """
    user:  UserContext
    anime:      AnimeContext | None = None   # None → no specific title context
    found:      bool                = False  # False → AI must not hallucinate details
    query:      str                 = ""     # original user query (for logging / not-found note)
    # News fields — populated only by from_news_result(); empty list for all other paths.
    news_items: list[NewsItem]      = field(default_factory=list)
    news_mode:  str                 = ""     # "latest" | "trending" | ""
    # Intelligence fields — populated only by from_intelligence_result().
    franchise_context: str          = ""     # pre-rendered watch-order / manga block
    intelligence_mode: str          = ""     # "watch_order" | "manga_continuation" | ""
    # Web search fields — populated by KnowledgeRouter when ENABLE_WEB_SEARCH=True.
    # Always empty list for all non-web paths; never None.
    web_results:       list[WebSearchResult] = field(default_factory=list)
    web_search_mode:   bool                  = False   # True → render web section in to_text()


# ── Builder ────────────────────────────────────────────────────────────────────

class ContextBuilder:
    """
    Stateless builder — all methods are classmethods.

    Import the class and call its methods directly:

        from services.context_builder import ContextBuilder, AIContext

        ctx = ContextBuilder.from_search_result(result, intent, profile)
        system_text = SYSTEM_PROMPT + ContextBuilder.to_text(ctx)
        response = await router.route(prompt=text, system=system_text)
    """

    # ── Public API ─────────────────────────────────────────────────────────────

    @classmethod
    def should_resolve_intelligence(cls, intent: Intent) -> bool:
        """
        Return True when this intent should be handled by the Anime Intelligence Core.

        These intents get franchise manifests and continuation plans rather than
        a simple title search.  Handled before should_search() in the pipeline.
        """
        return intent in _INTELLIGENCE_INTENTS

    @classmethod
    def should_search(cls, intent: Intent) -> bool:
        """
        Return True when this intent benefits from an anime-title context search.

        Conservative: only intents that discuss a *specific* title return True.
        Broad intents (recommendations, rankings) return False — the AI
        handles those from its training data, not from a title lookup.
        """
        return intent in _ANIME_CONTEXT_INTENTS

    @classmethod
    def should_fetch_news(cls, intent: Intent) -> bool:
        """
        Return True when this intent benefits from a live anime news fetch.

        ANIME_NEWS → fetch_latest()   (recent news articles)
        TRENDING   → fetch_trending() (currently popular airing anime)
        """
        return intent in _NEWS_CONTEXT_INTENTS

    @classmethod
    def from_search_result(
        cls,
        result: AnimeSearchResult,
        intent: Intent | None = None,
        user_profile: dict | None = None,
    ) -> AIContext:
        """
        Build an AIContext from an AnimeSearchResult.

        Strips raw API fields, internal IDs, empty values.
        Output is source-agnostic: AniList and Jikan produce identical structure.

        Args:
            result:       AnimeSearchResult from search_service.search()
            intent:       Detected Intent enum value (optional; used for label)
            user_profile: Dict from profiles.json for this user (optional)
        """
        user_ctx = cls._build_user_context(intent, user_profile or {})

        if not result.found:
            return AIContext(
                user=user_ctx,
                anime=None,
                found=False,
                query=result.query,
            )

        anime_ctx = cls._build_anime_context(result)
        return AIContext(
            user=user_ctx,
            anime=anime_ctx,
            found=True,
            query=result.query,
        )

    @classmethod
    def build_user_only(
        cls,
        intent: Intent | None = None,
        user_profile: dict | None = None,
        query: str = "",
    ) -> AIContext:
        """
        Build an AIContext without anime data.

        Used for: greetings, help, recommendations, news, seasonal, trending —
        any intent where a specific title search is not warranted.
        The AI still receives user personalisation (nickname, language, intent).
        """
        user_ctx = cls._build_user_context(intent, user_profile or {})
        return AIContext(user=user_ctx, anime=None, found=False, query=query)

    @classmethod
    def to_text(cls, ctx: AIContext) -> str:
        """
        Render an AIContext as a clean plain-text block.

        This block is appended to SYSTEM_PROMPT before the AI provider call.
        Format is human-readable labeled fields — NOT JSON, NOT markdown-heavy.
        Empty values are omitted entirely.

        Returns an empty string when there is genuinely nothing to inject
        (no user data, no anime data, unknown query).

        Example output:
            === Ani Zeo Context ===
            [User]
              Nickname: Karan
              Language: English
              Intent:   Anime Information

            [Anime: Attack on Titan]
              English:   Attack on Titan
              Romaji:    Shingeki no Kyojin
              Native:    進撃の巨人
              Status:    Finished
              Episodes:  25
              Rating:    9.0/10
              Season:    Spring 2013
              Studio:    Wit Studio
              Source:    Manga
              Duration:  24 min/ep
              Genres:    Action, Drama, Fantasy, Military, Mystery
              Streaming: Crunchyroll, Hulu
              Trailer:   https://...
              Related:   ➡ Sequel: Attack on Titan Season 2
              Synopsis:  Several hundred years ago...
              Data:      AniList
            ======================
        """
        lines: list[str] = []

        # ── Intelligence section (watch order / manga continuation) ───────────
        # Mutually exclusive with news and anime sections.
        if ctx.franchise_context:
            # User block first (if any), then the pre-rendered intelligence block
            user_lines_for_intel: list[str] = []
            if ctx.user.nickname:
                user_lines_for_intel.append(f"  Nickname: {ctx.user.nickname}")
            if ctx.user.language:
                user_lines_for_intel.append(f"  Language: {ctx.user.language}")
            if ctx.user.intent_label and ctx.user.intent_label != "Unknown":
                user_lines_for_intel.append(f"  Intent:   {ctx.user.intent_label}")
            if user_lines_for_intel:
                lines.append("[User]")
                lines.extend(user_lines_for_intel)
            lines.append("")
            lines.append(ctx.franchise_context)
            block = "\n".join(lines)
            return f"\n=== Ani Zeo Context ===\n{block}\n=== End Context ===\n"

        # ── User section ──────────────────────────────────────────────────────
        user_lines: list[str] = []
        if ctx.user.nickname:
            user_lines.append(f"  Nickname: {ctx.user.nickname}")
        if ctx.user.language:
            user_lines.append(f"  Language: {ctx.user.language}")
        if ctx.user.intent_label and ctx.user.intent_label != "Unknown":
            user_lines.append(f"  Intent:   {ctx.user.intent_label}")

        if user_lines:
            lines.append("[User]")
            lines.extend(user_lines)

        # ── News section ──────────────────────────────────────────────────────
        # Rendered when the intent is ANIME_NEWS or TRENDING.
        # Mutually exclusive with the anime section — a single context always
        # comes from one path (news fetch OR anime search, never both).
        if ctx.news_mode:
            if ctx.news_items:
                header = (
                    "Trending Anime"
                    if ctx.news_mode == "trending"
                    else "Latest Anime News"
                )
                lines.append(f"\n[{header}]")
                for i, item in enumerate(ctx.news_items, 1):
                    lines.append(f"  {i}. {item.title}")
                    meta: list[str] = [item.source_name]
                    if item.published:
                        meta.append(item.published)
                    lines.append(f"     Source:    {' | '.join(meta)}")
                    if item.summary:
                        s = item.summary[:200].rstrip()
                        if len(item.summary) > 200:
                            s += "…"
                        lines.append(f"     Summary:   {s}")
                    if item.url:
                        lines.append(f"     URL:       {item.url}")
            else:
                # All news sources failed — tell the AI to acknowledge the gap
                lines.append("\n[Note]")
                lines.append("  No anime news is available right now.")
                lines.append(
                    "  Answer from your training knowledge and note that"
                    " live news cannot be fetched at this moment."
                )

        # ── Anime section ─────────────────────────────────────────────────────
        elif ctx.anime and ctx.found:
            a = ctx.anime
            lines.append(f"\n[Anime: {a.display_title}]")

            # Titles — show all available; skip romaji when same as English
            if a.title_english:
                lines.append(f"  English:   {a.title_english}")
            if a.title_romaji and a.title_romaji != a.title_english:
                lines.append(f"  Romaji:    {a.title_romaji}")
            if a.title_native:
                lines.append(f"  Native:    {a.title_native}")

            # Core production facts
            if a.status:
                lines.append(f"  Status:    {a.status}")
            if a.episodes:
                lines.append(f"  Episodes:  {a.episodes}")
            if a.rating:
                lines.append(f"  Rating:    {a.rating}")
            # Show season if available, otherwise year alone
            if a.season:
                lines.append(f"  Season:    {a.season}")
            elif a.year:
                lines.append(f"  Year:      {a.year}")
            if a.studio:
                lines.append(f"  Studio:    {a.studio}")
            if a.source_material:
                lines.append(f"  Source:    {a.source_material}")
            if a.duration:
                lines.append(f"  Duration:  {a.duration}")

            # Descriptive lists
            if a.genres:
                lines.append(f"  Genres:    {', '.join(a.genres)}")
            if a.main_characters:
                lines.append(f"  Characters:{', '.join(a.main_characters)}")
            if a.tags:
                lines.append(f"  Tags:      {', '.join(a.tags)}")

            # Access
            if a.streaming_platforms:
                lines.append(f"  Streaming: {', '.join(a.streaming_platforms)}")
            if a.available_languages:
                lines.append(f"  Languages: {', '.join(a.available_languages)}")
            if a.trailer_url:
                lines.append(f"  Trailer:   {a.trailer_url}")

            # Relations (prequel/sequel)
            if a.relations:
                lines.append(f"  Related:   {' | '.join(a.relations)}")

            # Synopsis last — longest field
            if a.synopsis:
                lines.append(f"  Synopsis:  {a.synopsis}")

            lines.append(f"  Data:      {a.data_source}")

        elif ctx.query and not ctx.found:
            # Explicit not-found note so the AI does not hallucinate.
            # Only reached for anime-search misses, not for news intents
            # (those are handled by the news_mode branch above).
            lines.append(f"\n[Note]")
            lines.append(f"  No anime data found for: {ctx.query!r}")
            lines.append("  Do not hallucinate anime titles, scores, or episode counts.")
            lines.append("  Acknowledge the gap honestly.")

        # ── Web search section ────────────────────────────────────────────────
        # Rendered when KnowledgeRouter injected live web results.
        # Placed AFTER internal sections so internal data always takes priority.
        # The AI is explicitly told to treat these as supplemental sources.
        if ctx.web_search_mode and ctx.web_results:
            lines.append("\n[Web Search Results]")
            lines.append("  Source: live web search — treat as supplemental, not authoritative canon.")
            lines.append("  If internal anime data above conflicts with a web result, trust the internal data.")
            for i, r in enumerate(ctx.web_results, 1):
                lines.append(f"  {i}. {r.title}")
                if r.source:
                    lines.append(f"     Source: {r.source}")
                if r.published_date:
                    lines.append(f"     Date:   {r.published_date}")
                if r.snippet:
                    # Cap snippet at 220 chars to stay within token budget
                    s = r.snippet[:220].rstrip()
                    if len(r.snippet) > 220:
                        s += "…"
                    lines.append(f"     Snippet: {s}")
        elif ctx.web_search_mode and not ctx.web_results:
            # Web search was attempted but returned nothing
            lines.append("\n[Note]")
            lines.append("  Live web search returned no results for this query.")
            lines.append("  Answer from training knowledge and note that live data is unavailable.")

        # Return empty string when there is nothing useful to inject
        if not lines:
            return ""

        block = "\n".join(lines)
        return f"\n=== Ani Zeo Context ===\n{block}\n=== End Context ===\n"

    # ── Future stubs ───────────────────────────────────────────────────────────
    # Uncomment and implement when the relevant data source is wired.

    @classmethod
    def from_intelligence_result(
        cls,
        result: "IntelligenceResult",
        intent: Intent | None = None,
        user_profile: dict | None = None,
    ) -> AIContext:
        """
        Build an AIContext from an IntelligenceResult (watch order / manga continuation).

        Formats the structured franchise and continuation data into a plain-text
        context block stored in franchise_context.  The AI never sees raw dataclass
        internals — only the rendered text produced here.
        """
        user_ctx = cls._build_user_context(intent, user_profile or {})
        lines: list[str] = []

        # ── Ambiguous: ask the user ───────────────────────────────────────────
        if result.ambiguous:
            lines.append(f"[Clarification Needed: {result.original_query!r}]")
            if result.clarification:
                lines.append(f"  {result.clarification}")
            return AIContext(
                user=user_ctx,
                found=False,
                query=result.original_query,
                franchise_context="\n".join(lines),
                intelligence_mode=result.intent,
            )

        # ── Franchise not found ───────────────────────────────────────────────
        if not result.franchise or not result.franchise.found:
            lines.append(f"[Note]")
            lines.append(
                f"  No franchise data found for: {result.resolved_title or result.original_query!r}"
            )
            lines.append(
                "  Answer from training knowledge. "
                "Do not hallucinate episode counts or release dates."
            )
            return AIContext(
                user=user_ctx,
                found=False,
                query=result.original_query,
                franchise_context="\n".join(lines),
                intelligence_mode=result.intent,
            )

        franchise = result.franchise
        continuation = result.continuation

        # ── Manga continuation ────────────────────────────────────────────────
        if result.intent == "manga_continuation" and continuation:
            lines.append(f"[Manga Continuation: {franchise.canonical_title}]")
            if continuation.starting_chapter:
                lines.append(f"  Start reading from: Chapter {continuation.starting_chapter}")
            if continuation.manga_note:
                lines.append(f"  Note: {continuation.manga_note}")
            if franchise.source_material:
                lines.append(f"  Source material: {franchise.source_material}")

        # ── Watch / read order ────────────────────────────────────────────────
        else:
            order_label = {
                "canon_only":    "Canon-Only Order",
                "filler_skipped": "Filler-Skipped Order",
            }.get(result.intent, "Watch Order")

            lines.append(f"[{order_label}: {franchise.canonical_title}]")
            if result.original_query.lower() != (result.resolved_title or "").lower():
                lines.append(f"  Resolved from: {result.original_query!r}")

            if continuation and continuation.sequence:
                # Main story
                main = [i for i in continuation.sequence if not i.is_optional]
                optional = [i for i in continuation.sequence if i.is_optional]

                if main:
                    lines.append("  Main Story:")
                    for item in main:
                        ep_str = f"{item.episodes} eps" if item.episodes else "? eps"
                        yr_str = f" ({item.year})" if item.year else ""
                        filler_str = ""
                        if item.filler_ranges:
                            filler_str = f" | filler: {item.filler_ranges}"
                        lines.append(
                            f"    {item.order}. {item.title}"
                            f" — {item.fmt} | {ep_str}{yr_str}{filler_str}"
                        )
                        if item.notes and item.notes not in ("Finished", "Airing"):
                            lines.append(f"       {item.notes}")

                if optional:
                    lines.append("  Optional Content:")
                    for item in optional:
                        ep_str = f"{item.episodes} eps" if item.episodes else ""
                        yr_str = f" ({item.year})" if item.year else ""
                        ep_part = f" | {ep_str}" if ep_str else ""
                        lines.append(
                            f"    - {item.title}"
                            f" — {item.fmt}{ep_part}{yr_str}"
                        )
                        if item.notes:
                            lines.append(f"       {item.notes}")

            if continuation and continuation.general_note:
                lines.append(f"  Note: {continuation.general_note}")

            if franchise.source_material and franchise.source_material != "Original":
                lines.append(f"  Source material: {franchise.source_material}")

        franchise_context = "\n".join(lines)
        return AIContext(
            user=user_ctx,
            found=True,
            query=result.original_query,
            franchise_context=franchise_context,
            intelligence_mode=result.intent,
        )

    @classmethod
    def from_character_result(cls, result, intent=None, user_profile=None) -> AIContext:  # noqa: ANN001
        """Future: build context from a character lookup result."""
        raise NotImplementedError("Character context — Sprint 4")

    @classmethod
    def from_news_result(
        cls,
        result: NewsResult,
        intent: Intent | None = None,
        user_profile: dict | None = None,
    ) -> AIContext:
        """
        Build an AIContext from a NewsResult.

        Converts raw NewsItem objects into a clean context envelope.
        The AI NEVER sees RSS field names, raw XML, or internal source
        identifiers — only the human-readable labeled text produced by to_text().

        Items are capped at 5 to keep the context block within a reasonable
        token budget.

        Args:
            result:       NewsResult from news_service.fetch_latest/trending()
            intent:       Detected Intent (ANIME_NEWS or TRENDING)
            user_profile: Dict from profiles.json for this user (optional)
        """
        user_ctx = cls._build_user_context(intent, user_profile or {})
        items    = result.items[:5] if result.found else []
        return AIContext(
            user=user_ctx,
            anime=None,
            found=result.found,
            query="",
            news_items=items,
            news_mode=result.mode,
        )

    @classmethod
    def from_web_result(
        cls,
        query:        str,
        results:      "list[WebSearchResult]",
        user_profile: dict | None = None,
        intent:       "Intent | None" = None,
    ) -> "AIContext":
        """
        Build an AIContext whose primary content is live web search results.

        Used by KnowledgeRouter when the intent is WEB_SEARCH or GENERAL_KNOWLEDGE
        (i.e. no internal anime source can satisfy the query).

        The AI is instructed to treat these results as supplemental, not as
        authoritative canon — see the web section in to_text().

        Args:
            query:        Raw user query (for the not-found note fallback).
            results:      List from WebSearchService.search() — may be empty.
            user_profile: Dict from profiles.json (optional).
            intent:       Detected Intent (optional; used for label).
        """
        user_ctx = cls._build_user_context(intent, user_profile or {})
        return AIContext(
            user             = user_ctx,
            anime            = None,
            found            = bool(results),
            query            = query,
            web_results      = list(results),
            web_search_mode  = True,
        )

    @classmethod
    def from_watch_order(cls, franchise, intent=None, user_profile=None) -> AIContext:  # noqa: ANN001
        """Future: build context from a watch-order lookup."""
        raise NotImplementedError("Watch-order context — Sprint 4")

    # ── Private helpers ────────────────────────────────────────────────────────

    @classmethod
    def _build_user_context(
        cls,
        intent: Intent | None,
        profile: dict,
    ) -> UserContext:
        intent_label = "Unknown"
        if intent is not None:
            from services.intent import IntentClassifier
            intent_label = IntentClassifier().display_name(intent)

        return UserContext(
            nickname=profile.get("nickname") or None,
            language=profile.get("language") or None,
            intent_label=intent_label,
        )

    @classmethod
    def _build_anime_context(cls, result: AnimeSearchResult) -> AnimeContext:
        """
        Convert an AnimeSearchResult into a clean AnimeContext.

        Strips: found/query/source/cached flags, cover_url, popularity, rank,
                raw score (replaced with formatted rating), raw relation dicts
                (replaced with formatted strings).
        """
        # Source label — human-readable, not the raw API identifier
        source_label = {
            "anilist": "AniList",
            "jikan":   "MAL (Jikan)",
        }.get(result.source, result.source.capitalize())

        # Rating: AniList 0–100 → "X.X/10" display string
        rating: str | None = None
        if result.score:
            rating = f"{result.score / 10:.1f}/10"

        # Episodes: format with status context for ongoing series
        episodes: str | None = None
        if result.episodes:
            episodes = str(result.episodes)
        elif result.status in ("Currently Airing", "On Hiatus"):
            episodes = "Ongoing"

        # Year: extract the 4-digit year from the season string ("Fall 2013" → "2013")
        year: str | None = None
        if result.season:
            parts = result.season.split()
            if parts and parts[-1].isdigit() and len(parts[-1]) == 4:
                year = parts[-1]

        # Studio: first entry is the primary studio
        studio: str | None = result.studios[0] if result.studios else None

        # Relations: convert raw dicts to formatted display strings
        relations: list[str] = []
        for rel in result.relations:
            rel_type  = rel.get("type", "")
            rel_title = rel.get("title", "")
            if rel_type and rel_title:
                arrow = "➡ Sequel" if rel_type == "SEQUEL" else "⬅ Prequel"
                relations.append(f"{arrow}: {rel_title}")

        return AnimeContext(
            title_english=result.title_english or None,
            title_romaji=result.title_romaji or None,
            title_native=result.title_native or None,

            synopsis=result.synopsis or None,
            genres=result.genres or [],

            episodes=episodes,
            status=result.status or None,
            studio=studio,
            season=result.season or None,
            year=year,
            source_material=result.source_material or None,
            duration=result.duration or None,
            rating=rating,

            trailer_url=result.trailer_url or None,
            streaming_platforms=result.streaming_platforms or [],

            relations=relations,

            # Not yet populated by AnimeSearchService — reserved for future queries
            main_characters=[],
            tags=[],
            available_languages=[],

            data_source=source_label,
        )
