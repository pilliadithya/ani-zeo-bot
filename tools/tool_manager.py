"""
ToolManager — central registry and dispatcher for all Ani Zeo tools.

Why this exists:
  - AI providers never import Jikan / AniList directly.
  - AI and slash commands reuse the exact same tool implementations.
  - One place to add, remove, or stub any tool.
  - Providers receive a ToolManager reference in Sprint 3 for function-calling.

Usage:

  # From message_handler (intent-based free-text dispatch):
  tm = ToolManager()
  result = await tm.dispatch(Intent.SEARCH_ANIME, query="Death Note", user_id=123)

  # From AI provider function-calling (Sprint 3, structured params):
  result = await tm.run("anime_search", {"query": "Death Note"})

  # Register tools with a provider's function-calling API:
  schemas = tm.list_schemas()
"""
from __future__ import annotations

import logging

from services.intent import Intent
from tools.base_tool import BaseTool
from tools.anime_search import AnimeSearchTool
from tools.anime_details import AnimeDetailsTool
from tools.recommendations import RecommendationsTool
from tools.favorites import FavoritesTool
from tools.character_lookup import CharacterLookupTool
from tools.studio_lookup import StudioLookupTool
from tools.genre import GenreTool
from tools.season import SeasonTool
from tools.airing import AiringTool

logger = logging.getLogger(__name__)

# ── Tool registry ─────────────────────────────────────────────────────────────
# To add a new tool: import it above and add one entry here.
# Nothing else in the codebase needs to change.

_REGISTRY: dict[str, type[BaseTool]] = {
    "anime_search":     AnimeSearchTool,
    "anime_details":    AnimeDetailsTool,
    "recommendations":  RecommendationsTool,
    "favorites":        FavoritesTool,
    "character_lookup": CharacterLookupTool,
    "studio_lookup":    StudioLookupTool,
    "genre_browse":     GenreTool,
    "season_info":      SeasonTool,
    "airing":           AiringTool,
}

# ── Intent → tool name mapping ────────────────────────────────────────────────
# Only intents that have a direct tool equivalent appear here.
# Everything else falls through to the AI Router.

_INTENT_MAP: dict[Intent, str] = {
    Intent.SEARCH_ANIME:     "anime_search",
    Intent.GET_DETAILS:      "anime_details",
    Intent.SEARCH_MANGA:     "anime_search",
    Intent.RECOMMENDATIONS:  "recommendations",
    Intent.CHARACTER_LOOKUP: "character_lookup",
    Intent.STUDIO_LOOKUP:    "studio_lookup",
    Intent.GENRE_BROWSE:     "genre_browse",
    Intent.SEASON_INFO:      "season_info",
    Intent.UPCOMING:         "airing",
    Intent.FAVORITES_ACTION: "favorites",
}


class ToolManager:
    """
    Single entry point for all tool execution in Ani Zeo.

    A ToolManager instance is created once and shared between the message
    handler (intent dispatch) and the AI Router (provider function-calling).
    """

    def __init__(self) -> None:
        self._instances: dict[str, BaseTool] = {}

    # ── Intent-based dispatch (used by message_handler) ───────────────────────

    async def dispatch(
        self,
        intent: Intent,
        query: str = "",
        user_id: int = 0,
        **kwargs,
    ) -> dict | None:
        """
        Map an intent to its registered tool and run it.

        Returns the tool result dict on success, or None when:
          - No tool is registered for this intent.
          - The tool returns {"error": …} (stub or API failure).

        None tells the caller to fall through to AIRouter.
        """
        tool_name = _INTENT_MAP.get(intent)
        if tool_name is None:
            logger.debug("ToolManager.dispatch: no tool for intent %s", intent.name)
            return None

        result = await self.run(tool_name, {"query": query, "user_id": user_id, **kwargs})
        return result

    # ── Name-based dispatch (used by AI providers in Sprint 3) ────────────────

    async def run(self, tool_name: str, params: dict | None = None) -> dict | None:
        """
        Execute a tool by name with structured parameters.

        Called by AI providers when they use function-calling to request data.
        Returns the tool result dict on success, or None on failure.
        """
        tool = self._get_instance(tool_name)
        if tool is None:
            logger.warning("ToolManager.run: unknown tool %r", tool_name)
            return None

        try:
            result = await tool.run(**(params or {}))
            if isinstance(result, dict) and "error" in result:
                logger.debug(
                    "ToolManager.run: tool %r → error: %s", tool_name, result["error"]
                )
                return None
            return result
        except Exception as exc:
            logger.error(
                "ToolManager.run: tool %r raised %s: %s",
                tool_name, type(exc).__name__, exc,
            )
            return None

    # ── Schema / introspection ────────────────────────────────────────────────

    def list_schemas(self) -> list[dict]:
        """
        Return tool descriptors for AI function-calling registration.
        Providers call this to build their function-calling payloads.
        """
        return [tool_class().schema() for tool_class in _REGISTRY.values()]

    def registered_tools(self) -> list[str]:
        """Return names of all registered tools."""
        return list(_REGISTRY.keys())

    # ── Private ───────────────────────────────────────────────────────────────

    def _get_instance(self, name: str) -> BaseTool | None:
        """Return a cached tool instance, creating it on first access."""
        if name not in _REGISTRY:
            return None
        if name not in self._instances:
            self._instances[name] = _REGISTRY[name]()
        return self._instances[name]
