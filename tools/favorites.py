"""
FavoritesTool — read a user's saved favourites for AI context enrichment.

Data source: favorites.json (local file, same as bot.py).
Status:      STUB — not implemented until Sprint 3.

Sprint 3 implementation notes:
  1. Read favorites.json.
  2. Return the list for the given user_id.
  3. Used by AI to personalise recommendations without re-asking the user.
"""
from __future__ import annotations

from tools.base_tool import BaseTool


class FavoritesTool(BaseTool):
    tool_name        = "favorites"
    tool_description = "Get the user's saved favourite anime list for personalisation."

    def schema(self) -> dict:
        return {
            "name":        self.tool_name,
            "description": self.tool_description,
            "parameters": {
                "user_id": {"type": "integer", "description": "Telegram user ID."},
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
            user_id:  Telegram user ID.
            query:    Ignored (kept for interface consistency).

        Returns:
            {"favorites": ["Anime Title 1", "Anime Title 2", ...]}

        TODO (Sprint 3): read favorites.json, return user's list.
        """
        return {"error": "FavoritesTool not implemented yet — Sprint 3"}
