"""
SeasonTool — fetch anime for a specific season and year.

Data source: AniList GraphQL API (same endpoint used by /season command).
Status:      STUB — not implemented until Sprint 3.

Sprint 3 implementation notes:
  1. Parse season ("winter", "spring", "summer", "fall") and year from query.
  2. Default to current season/year if not provided.
  3. Query AniList: season + seasonYear filter, sorted by POPULARITY_DESC.
  4. Return results with title, score, episodes, and status.
"""
from __future__ import annotations

from tools.base_tool import BaseTool


class SeasonTool(BaseTool):
    tool_name        = "season_info"
    tool_description = "Get anime for a specific season (winter/spring/summer/fall) and year."

    def schema(self) -> dict:
        return {
            "name":        self.tool_name,
            "description": self.tool_description,
            "parameters": {
                "query":  {"type": "string", "description": "e.g. 'spring 2024' or 'current'."},
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
            query:   Season descriptor (e.g. "spring 2024", "current", "fall").
            limit:   Maximum number of results.

        Returns:
            {"season": str, "year": int,
             "results": [{"title": str, "score": float, "status": str}, ...]}

        TODO (Sprint 3): parse query, call AniList season query, return dict.
        """
        return {"error": "SeasonTool not implemented yet — Sprint 3"}
