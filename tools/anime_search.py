"""
AnimeSearchTool — search for anime or manga by title.

Data source: AniList GraphQL API (same endpoint used by /search command).
Status:      STUB — not implemented until Sprint 3.

Sprint 3 implementation notes:
  1. Call AniList Media query with search=$query.
  2. Return title, score, episodes, status, genres, synopsis, studios, trailer.
"""
from __future__ import annotations

from tools.base_tool import BaseTool


class AnimeSearchTool(BaseTool):
    tool_name        = "anime_search"
    tool_description = "Search for an anime or manga by title and return its details."

    def schema(self) -> dict:
        return {
            "name":        self.tool_name,
            "description": self.tool_description,
            "parameters": {
                "query": {"type": "string", "description": "Anime or manga title to search."},
                "type":  {"type": "string", "description": "'ANIME' or 'MANGA' (default ANIME)."},
            },
        }

    async def run(
        self,
        query: str = "",
        user_id: int = 0,
        type: str = "ANIME",
        **kwargs,
    ) -> dict:
        """
        Args:
            query:   Title to search.
            type:    Media type — "ANIME" or "MANGA".

        Returns:
            {"title": str, "score": float, "episodes": int, "status": str,
             "genres": list, "synopsis": str, "studios": list, "trailer_url": str}

        TODO (Sprint 3): call AniList Media(search:) query, return dict.
        """
        return {"error": "AnimeSearchTool not implemented yet — Sprint 3"}
