"""
RecommendationsTool — fetch anime recommendations by title or genre.

Data source: Jikan API (MyAnimeList recommendations endpoint).
Status:      STUB — not implemented until Sprint 3.

Sprint 3 implementation notes:
  1. For mode="title": call Jikan /recommendations/anime for the queried title.
  2. For mode="genre": query AniList top-scored anime filtered by genre.
  3. Return list of recommendations with title, score, and reason.
"""
from __future__ import annotations

from tools.base_tool import BaseTool


class RecommendationsTool(BaseTool):
    tool_name        = "recommendations"
    tool_description = "Get anime recommendations by title similarity or genre."

    def schema(self) -> dict:
        return {
            "name":        self.tool_name,
            "description": self.tool_description,
            "parameters": {
                "query": {"type": "string",
                          "description": "Anime title or genre keyword."},
                "mode":  {"type": "string",
                          "description": "'title' for similar anime, "
                                         "'genre' for top anime in genre."},
                "limit": {"type": "integer", "description": "Max results (default 10)."},
            },
        }

    async def run(
        self,
        query: str = "",
        user_id: int = 0,
        mode: str = "title",
        limit: int = 10,
        **kwargs,
    ) -> dict:
        """
        Args:
            query:   Anime title or genre keyword.
            mode:    "title" | "genre"
            limit:   Maximum number of results.

        Returns:
            {"results": [{"title": str, "score": float, "reason": str}, ...]}

        TODO (Sprint 3): route to Jikan recommendations or AniList genre endpoint.
        """
        return {"error": "RecommendationsTool not implemented yet — Sprint 3"}
