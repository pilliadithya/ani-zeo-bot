"""
Abstract base interface that every AI provider must implement.

router.py only ever calls methods declared here — it never imports
a concrete provider directly, which allows providers to be swapped
or added without modifying the router.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class Message:
    """A single turn in a conversation."""
    role: str       # "user" | "assistant" | "system"
    content: str


# ── Error type constants ───────────────────────────────────────────────────────
# Used by router to decide whether to retry or immediately fail over.
ERR_NONE        = ""            # success
ERR_TRANSIENT   = "transient"   # 5xx, network blip — safe to retry
ERR_QUOTA       = "quota"       # 429 / rate-limit — skip retries, cool down 5 min
ERR_PERMANENT   = "permanent"   # invalid API key, 401/403 — cool down 1 h
ERR_TIMEOUT     = "timeout"     # request timed out — retry once
ERR_UNCONFIGURED = "unconfigured"  # key not set in env


@dataclass
class ProviderResponse:
    """
    Standardised response envelope returned by every provider.

    The router inspects `success` and `error_type` to decide whether to
    retry the same provider or fall through to the next one.

    error_type values:
        ""              — success (no error)
        "transient"     — safe to retry (5xx, network)
        "quota"         — 429 / rate-limit; skip retries, apply quota cooldown
        "permanent"     — invalid key, 401/403; skip retries, apply long cooldown
        "timeout"       — request timed out; retry once
        "unconfigured"  — API key not set; skip provider silently
    """
    text: str
    provider: str
    model: str
    success: bool         = True
    error: str | None     = None
    error_type: str       = ERR_NONE
    latency_ms: float     = 0.0
    tokens_used: int      = 0


class AIProvider(ABC):
    """
    Abstract base class for AI providers.

    Subclass this and implement generate_response() to add a new provider.
    Everything else in the codebase depends only on this interface.
    """

    # Subclasses declare their identity here.
    provider_name: str = "base"
    model_name: str    = "unknown"

    @abstractmethod
    async def generate_response(
        self,
        prompt: str,
        context: dict | None = None,
        history: list[Message] | None = None,
        system: str | None = None,
        tool_manager=None,
    ) -> ProviderResponse:
        """
        Generate a text response from the AI provider.

        Returns a ProviderResponse with success=True on success.
        On failure: success=False, error set, error_type set to one of the
        ERR_* constants so the router can decide whether to retry.
        """
        ...

    async def health_check(self) -> bool:
        """
        Lightweight availability probe — no live API call.
        Returns True when the required credentials are present.
        Override to add a live ping only where quota allows.
        """
        return self.is_configured()

    def is_configured(self) -> bool:
        """
        Returns True when the required API key / credentials exist
        in environment variables.  Must be overridden in each provider.
        """
        return False

    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__} "
            f"provider={self.provider_name!r} "
            f"model={self.model_name!r}>"
        )
