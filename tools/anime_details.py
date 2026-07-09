"""
AnimeDetailsTool — fetch full details for an anime by AniList ID.

Data source: AniList GraphQL API.
Status:      STUB — not implemented until Sprint 3.

Sprint 3 implementation notes:
  1. Query AniList Media(id: $anilist_id).
  2. Include relations, rankings, streaming links, and source.
"""
from __future__ import annotations

from tools.base_tool import BaseTool


class AnimeDetailsTool(BaseTool):
    tool_name        = "anime_details"
    tool_description = "Get full details for an anime by its AniList media ID."

    def schema(self) -> dict:
        return {
            "name":        self.tool_name,
            "description": self.tool_description,
            "parameters": {
                "anilist_id": {"type": "integer",
                               "description": "AniList media ID of the anime."},
            },
        }

    async def run(
        self,
        query: str = "",
        user_id: int = 0,
        anilist_id: int = 0,
        **kwargs,
    ) -> dict:
        """
        Args:
            anilist_id:  AniList media ID.
            query:       Ignored (kept for interface consistency).

        Returns:
            Extended dict including relations, rankings, streaming links, source.

        TODO (Sprint 3): call AniList Media(id:) query, return dict.
        """
        return {"error": "AnimeDetailsTool not implemented yet — Sprint 3"}
