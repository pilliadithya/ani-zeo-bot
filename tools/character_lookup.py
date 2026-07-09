"""
CharacterLookupTool — fetch character data for AI context enrichment.

Data source: AniList GraphQL API (same endpoint used by /character command).
Status:      STUB — not implemented until Sprint 3.

Sprint 3 implementation notes:
  1. Query AniList characters edges filtered by anime title.
  2. Include Japanese and English voice actors per character.
  3. Return top N main characters with roles and VA names.
"""
from __future__ import annotations

from tools.base_tool import BaseTool


class CharacterLookupTool(BaseTool):
    tool_name        = "character_lookup"
    tool_description = "Get main characters and voice actors for an anime."

    def schema(self) -> dict:
        return {
            "name":        self.tool_name,
            "description": self.tool_description,
            "parameters": {
                "query": {"type": "string", "description": "Anime title."},
                "limit": {"type": "integer", "description": "Max characters (default 5)."},
            },
        }

    async def run(
        self,
        query: str = "",
        user_id: int = 0,
        limit: int = 5,
        **kwargs,
    ) -> dict:
        """
        Args:
            query:   Anime title.
            limit:   Maximum number of characters to return.

        Returns:
            {"characters": [{"name": str, "role": str,
                              "ja_va": str, "en_va": str}, ...]}

        TODO (Sprint 3): query AniList characters edges with voiceActors.
        """
        return {"error": "CharacterLookupTool not implemented yet — Sprint 3"}
