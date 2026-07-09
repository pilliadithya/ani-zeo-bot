"""
BaseTool — abstract interface every Ani Zeo tool must implement.

ToolManager only ever depends on this interface, never on concrete classes.
Adding a new tool means subclassing BaseTool and registering it in
tool_manager.py — nothing else changes.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class BaseTool(ABC):
    """
    Abstract base for all AI-callable tools.

    tool_name and tool_description are used to build AI function-calling
    schema payloads (Sprint 3).  run() is the single execution entry point.
    """

    tool_name:        str = "base"
    tool_description: str = ""

    @abstractmethod
    async def run(
        self,
        query: str = "",
        user_id: int = 0,
        **kwargs,
    ) -> dict:
        """
        Execute the tool and return a result dict.

        Args:
            query:    Free-text user query — used for intent-based dispatch.
            user_id:  Telegram user ID — used for personalised tools (favourites).
            **kwargs: Additional structured parameters passed by AI function-calling.

        Returns:
            A dict with result data on success.
            {"error": reason_string} on failure or when the tool is a stub.
        """
        ...

    def schema(self) -> dict:
        """
        Return a JSON-schema-compatible tool descriptor for AI function
        registration.  Concrete tools can override to add a parameters block.
        """
        return {
            "name":        self.tool_name,
            "description": self.tool_description,
        }

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} name={self.tool_name!r}>"
