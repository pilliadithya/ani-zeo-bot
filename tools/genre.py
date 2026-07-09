"""
GenreTool — browse anime by genre.

Data source: AniList GraphQL API (same endpoint used by /genre command).
Status:      STUB — not implemented until Sprint 3.

Sprint 3 implementation notes:
  1. Parse genre name from query.
  2. Query AniList: MediaListCollection filtered by genre, sorted by SCORE_DESC.
  3. Return top 10 results with title, score, episodes, and synopsis.
"""
from __future__ import annotations

from tools.base_tool import BaseTool


class GenreTool(BaseTool):
    tool_name        = "genre_browse"
    tool_description = "Browse top anime for a specific genre (action, romance, etc.)."

    def schema(self) -> dict:
        return {
            "name":        self.tool_name,
            "description": self.tool_description,
            "parameters": {
                "query":  {"type": "string", "description": "Genre name (e.g. 'action')."},
                "limit":  {"type": "integer", "description": "Max results (default 10)."},
            },
        }

    async def run(
        self,
        query: str = "",
        user_id: int = 0,
        limit: int = 10,
        **kwargs,
    ) -> dict:
        """
        Args:
            query:   Genre name to browse.
            limit:   Maximum number of results.

        Returns:
            {"results": [{"title": str, "score": float, "episodes": int}, ...]}

        TODO (Sprint 3): query AniList genre filter, return structured list.
        """
        return {"error": "GenreTool not implemented yet — Sprint 3"}
