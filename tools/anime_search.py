"""
AnimeSearchTool — thin adapter between ToolManager and AnimeSearchService.

All search logic (AniList, Jikan, caching, fallback) lives in
services/anime_search.py.  This tool is intentionally a one-liner:
it calls the service and maps the AnimeSearchResult dataclass to the
flat dict contract that ToolManager and AI function-calling expect.

Data flow:
    ToolManager.dispatch(Intent.SEARCH_ANIME, query=...) 
        → AnimeSearchTool.run(query=...)
            → AnimeSearchService.search(query)
                → AniList / Jikan / cache
            → AnimeSearchResult.to_dict()
"""
from __future__ import annotations

from tools.base_tool import BaseTool
from services.anime_search import search_service


class AnimeSearchTool(BaseTool):
    tool_name        = "anime_search"
    tool_description = (
        "Search for an anime by title and return its details. "
        "Handles typos, partial names, romanised names, and alternative titles. "
        "Falls back to MAL (Jikan) if AniList returns no result."
    )

    def schema(self) -> dict:
        return {
            "name":        self.tool_name,
            "description": self.tool_description,
            "parameters": {
                "query": {
                    "type":        "string",
                    "description": "Anime title to search (full, partial, or romanised).",
                    "required":    True,
                },
            },
        }

    async def run(
        self,
        query: str = "",
        user_id: int = 0,
        **kwargs,
    ) -> dict:
        """
        Search for an anime and return a structured result dict.

        Returns a dict with all AnimeSearchResult fields on success.
        Returns {"error": reason, "found": False} when not found —
        ToolManager will treat this as a miss and fall through to AIRouter.

        Never raises — all exceptions are caught inside AnimeSearchService.
        """
        if not query:
            return {"error": "No query provided", "found": False}

        result = await search_service.search(query)

        if not result.found:
            return {
                "error": f"Anime not found for query: {query!r}",
                "found": False,
                "query": query,
                "source": result.source,
            }

        return result.to_dict()
