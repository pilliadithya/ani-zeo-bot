"""
AiringTool — fetch currently airing or upcoming anime.

Data source: AniList GraphQL API (same endpoint used by /airing and /upcoming).
Status:      STUB — not implemented until Sprint 3.

Sprint 3 implementation notes:
  1. Query AniList: status=RELEASING (airing) or status=NOT_YET_RELEASED (upcoming).
  2. Sort by POPULARITY_DESC.
  3. Return title, next episode air date, episodes, and score.
"""
from __future__ import annotations

from tools.base_tool import BaseTool


class AiringTool(BaseTool):
    tool_name        = "airing"
    tool_description = "Get currently airing anime or upcoming titles."

    def schema(self) -> dict:
        return {
            "name":        self.tool_name,
            "description": self.tool_description,
            "parameters": {
                "mode":  {"type": "string",
                          "description": "'airing' for currently airing, "
                                         "'upcoming' for not yet released."},
                "limit": {"type": "integer", "description": "Max results (default 10)."},
            },
        }

    async def run(
        self,
        query: str = "",
        user_id: int = 0,
        mode: str = "airing",
        limit: int = 10,
        **kwargs,
    ) -> dict:
        """
        Args:
            query:   Optional filter keyword (currently unused).
            mode:    "airing" | "upcoming"
            limit:   Maximum number of results.

        Returns:
            {"mode": str,
             "results": [{"title": str, "episode": int, "air_date": str}, ...]}

        TODO (Sprint 3): call AniList status filter, return structured dict.
        """
        return {"error": "AiringTool not implemented yet — Sprint 3"}
