"""
tools package — AI-callable tool layer for Ani Zeo.

Architecture:
  AI Router → ToolManager → Individual Tools → Jikan / AniList APIs

AI providers never import Jikan or AniList directly.  They call tools
through ToolManager, which ensures AI and slash commands share the same
underlying data-fetching code.

All tools are currently stubs (Sprint 3 implements the API logic).

Public surface:
    from tools.tool_manager import ToolManager
    from tools.base_tool import BaseTool
"""
from tools.base_tool import BaseTool
from tools.tool_manager import ToolManager
from tools.anime_search import AnimeSearchTool
from tools.anime_details import AnimeDetailsTool
from tools.recommendations import RecommendationsTool
from tools.favorites import FavoritesTool
from tools.character_lookup import CharacterLookupTool
from tools.studio_lookup import StudioLookupTool
from tools.genre import GenreTool
from tools.season import SeasonTool
from tools.airing import AiringTool

__all__ = [
    "BaseTool",
    "ToolManager",
    "AnimeSearchTool",
    "AnimeDetailsTool",
    "RecommendationsTool",
    "FavoritesTool",
    "CharacterLookupTool",
    "StudioLookupTool",
    "GenreTool",
    "SeasonTool",
    "AiringTool",
]
