"""
StudioLookupTool — fetch animation studio information.

Data source: AniList GraphQL API (same endpoint used by /studio command).
Status:      STUB — not implemented until Sprint 3.

Sprint 3 implementation notes:
  1. Query AniList studios edges filtered by anime title.
  2. Return main studio name, total favourites, and site URL.
"""
from __future__ import annotations

from tools.base_tool import BaseTool


class StudioLookupTool(BaseTool):
    tool_name        = "studio_lookup"
    tool_description = "Get animation studio details for an anime."

    def schema(self) -> dict:
        return {
            "name":        self.tool_name,
            "description": self.tool_description,
            "parameters": {
                "query": {"type": "string", "description": "Anime title."},
            },
        }

    async def run(
        self,
        query: str = "",
        user_id: int = 0,
        **kwargs,
    ) -> dict:
        """
        Args:
            query:   Anime title.

        Returns:
            {"studios": [{"name": str, "is_main": bool,
                          "favourites": int, "site_url": str}, ...]}

        TODO (Sprint 3): query AniList studios edges.
        """
        return {"error": "StudioLookupTool not implemented yet — Sprint 3"}
