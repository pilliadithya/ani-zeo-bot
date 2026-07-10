"""
AIRouter — central dispatcher for all AI provider calls.

Responsibilities:
  - Maintain the provider registry (name → class).
  - Enforce provider priority and automatic fallback.
  - Apply per-request timeouts.
  - Track provider health with error-type-aware cooldowns.
  - Skip retries for permanent errors (invalid key) and quota errors (429).
  - Expose health_status() for diagnostics.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

from config.ai_config import (
    ACTIVE_PROVIDER,
    FALLBACK_TIMEOUT,
    HEALTH_COOLDOWN,
    LOG_PROVIDER_CALLS,
    MAX_RETRIES,
    PERMANENT_COOLDOWN,
    PROVIDER_PRIORITY,
    QUOTA_COOLDOWN,
    REQUEST_TIMEOUT,
    RETRY_DELAY,
    MAX_HISTORY_SENT,
    NVIDIA_REQUEST_TIMEOUT,
)
from ai.providers.base_provider import (
    AIProvider,
    Message,
    ProviderResponse,
    ERR_NONE,
    ERR_PERMANENT,
    ERR_QUOTA,
    ERR_TRANSIENT,
    ERR_TIMEOUT,
    ERR_UNCONFIGURED,
)
from ai.providers.gemini import GeminiProvider
from ai.providers.groq import GroqProvider
from ai.providers.nvidia_nim import NvidiaNimProvider
from ai.providers.openrouter import OpenRouterProvider

logger = logging.getLogger(__name__)

# ── Provider registry ─────────────────────────────────────────────────────────
# Add new providers here — the router picks them up automatically via
# PROVIDER_PRIORITY in config/ai_config.py.

PROVIDER_REGISTRY: dict[str, type[AIProvider]] = {
    "gemini":     GeminiProvider,
    "groq":       GroqProvider,
    "nvidia_nim": NvidiaNimProvider,
    "openrouter": OpenRouterProvider,
}

# ── Errors that should never be retried ───────────────────────────────────────
_NO_RETRY_TYPES: frozenset[str] = frozenset({ERR_PERMANENT, ERR_QUOTA, ERR_UNCONFIGURED})


# ── Health tracker ────────────────────────────────────────────────────────────

@dataclass
class _HealthEntry:
    re_enable_at: float   # monotonic timestamp when provider becomes available again
    last_error_type: str  # last ERR_* that caused the cooldown
    last_error: str       # human-readable error text


class ProviderHealth:
    """
    Tracks per-provider availability with error-type-aware cooldowns.

      error_type = "permanent"    → PERMANENT_COOLDOWN  (1 h — bad key)
      error_type = "quota"        → QUOTA_COOLDOWN      (5 min — 429)
      error_type = "timeout"      → HEALTH_COOLDOWN     (60 s)
      error_type = "transient"    → HEALTH_COOLDOWN     (60 s)
    """

    def __init__(self) -> None:
        self._entries: dict[str, _HealthEntry] = {}

    def mark_failed(self, provider: str, error_type: str, error: str = "") -> None:
        if error_type == ERR_PERMANENT:
            cooldown = PERMANENT_COOLDOWN
        elif error_type == ERR_QUOTA:
            cooldown = QUOTA_COOLDOWN
        else:
            cooldown = HEALTH_COOLDOWN

        self._entries[provider] = _HealthEntry(
            re_enable_at=time.monotonic() + cooldown,
            last_error_type=error_type,
            last_error=error,
        )
        logger.warning(
            "ProviderHealth: %s disabled for %.0fs [%s]",
            provider, cooldown, error_type,
        )

    def is_available(self, provider: str) -> bool:
        entry = self._entries.get(provider)
        if entry is None:
            return True
        if time.monotonic() >= entry.re_enable_at:
            del self._entries[provider]
            return True
        return False

    def available_in_order(self, ordered: list[str]) -> list[str]:
        return [p for p in ordered if self.is_available(p)]

    def get_status(self, provider: str) -> dict:
        """Return a human-readable status dict for diagnostics."""
        entry = self._entries.get(provider)
        if entry is None:
            return {"status": "available", "error_type": "", "error": ""}
        remaining = entry.re_enable_at - time.monotonic()
        if remaining <= 0:
            return {"status": "available", "error_type": "", "error": ""}
        label = {
            ERR_PERMANENT: "invalid_key",
            ERR_QUOTA:     "rate_limited",
            ERR_TIMEOUT:   "timeout",
            ERR_TRANSIENT: "degraded",
        }.get(entry.last_error_type, entry.last_error_type)
        return {
            "status": label,
            "error_type": entry.last_error_type,
            "error": entry.last_error[:120] if entry.last_error else "",
            "retry_in_seconds": int(remaining),
        }


# ── Router ────────────────────────────────────────────────────────────────────

class AIRouter:
    """
    Routes AI requests through the provider chain with fallback.

    Usage:
        router = AIRouter()
        response = await router.route("What anime should I watch?")
        print(response.text)

    Retry policy:
        transient / timeout  → retry up to MAX_RETRIES times
        quota / permanent    → no retry; immediately move to next provider
        unconfigured         → skip silently (not counted as failure)
    """

    def __init__(
        self,
        priority: list[str] | None = None,
        tool_manager=None,
    ) -> None:
        self._priority: list[str] = priority or PROVIDER_PRIORITY
        self._health = ProviderHealth()
        self._instances: dict[str, AIProvider] = {}
        self._tool_manager = tool_manager

    # ── Public API ────────────────────────────────────────────────────────────

    def get_provider(self, name: str | None = None) -> AIProvider | None:
        return self._instantiate(name or ACTIVE_PROVIDER)

    def available_providers(self) -> list[str]:
        return self._health.available_in_order(self._priority)

    def list_providers(self) -> dict[str, bool]:
        return {
            name: (self._instantiate(name) or _NullProvider()).is_configured()
            for name in PROVIDER_REGISTRY
        }

    def health_status(self) -> dict[str, dict]:
        """
        Return per-provider health status for diagnostics / /aistatus command.

        Example output:
            {
              "gemini":     {"status": "available", "configured": True, ...},
              "glm":        {"status": "disabled",  "configured": False, ...},
              "nvidia_nim": {"status": "rate_limited", "retry_in_seconds": 180, ...},
            }
        """
        result: dict[str, dict] = {}
        for name in PROVIDER_REGISTRY:
            instance = self._instantiate(name)
            configured = bool(instance and instance.is_configured())
            health = self._health.get_status(name)
            if not configured:
                health = {
                    "status": "disabled",
                    "error_type": ERR_UNCONFIGURED,
                    "error": f"{name.upper()}_API_KEY not set",
                }
            result[name] = {"configured": configured, **health}
        return result

    async def route(
        self,
        prompt: str,
        context: dict | None = None,
        history: list[Message] | None = None,
        system: str | None = None,
        provider: str | None = None,
    ) -> ProviderResponse:
        """
        Send a prompt through the provider chain and return the first
        successful response.

        History is trimmed to MAX_HISTORY_SENT turns before dispatch
        to cap token consumption.
        """
        chain = self._build_chain(provider)
        if not chain:
            return self._no_providers_response()

        # Token optimisation: only send the last MAX_HISTORY_SENT turns
        trimmed_history = _trim_history(history)

        deadline = time.monotonic() + FALLBACK_TIMEOUT
        last_error = "No providers attempted"

        for name in chain:
            if time.monotonic() >= deadline:
                logger.warning("AIRouter: fallback timeout exceeded")
                break

            instance = self._instantiate(name)
            if instance is None or not instance.is_configured():
                logger.debug("AIRouter: skipping %s (not configured)", name)
                continue

            response, last_error = await self._try_provider(
                instance=instance,
                name=name,
                prompt=prompt,
                context=context,
                history=trimmed_history,
                system=system,
                deadline=deadline,
            )

            if response is not None:
                return response

        return ProviderResponse(
            text="",
            provider="none",
            model="none",
            success=False,
            error=last_error,
        )

    # ── Private helpers ───────────────────────────────────────────────────────

    def _build_chain(self, preferred: str | None) -> list[str]:
        available = self.available_providers()
        if preferred and preferred in PROVIDER_REGISTRY:
            rest = [p for p in available if p != preferred]
            return [preferred] + rest
        return available

    def _instantiate(self, name: str) -> AIProvider | None:
        if name not in PROVIDER_REGISTRY:
            logger.warning("AIRouter: unknown provider %r", name)
            return None
        if name not in self._instances:
            self._instances[name] = PROVIDER_REGISTRY[name]()
        return self._instances[name]

    async def _try_provider(
        self,
        instance: AIProvider,
        name: str,
        prompt: str,
        context: dict | None,
        history: list[Message] | None,
        system: str | None,
        deadline: float,
    ) -> tuple[ProviderResponse | None, str]:
        """
        Attempt one provider with smart retry logic.

        - permanent / quota / unconfigured errors → no retry, immediate fallback
        - transient / timeout errors              → retry up to MAX_RETRIES
        """
        last_error = "Unknown error"
        last_error_type = ERR_TRANSIENT

        for attempt in range(1, MAX_RETRIES + 1):
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return None, "Fallback timeout reached"

            # Honour a per-provider timeout override (e.g. slow reasoning models).
            provider_timeout = getattr(instance, "request_timeout", REQUEST_TIMEOUT)
            timeout = min(provider_timeout, remaining)
            t0 = time.monotonic()

            try:
                response: ProviderResponse = await asyncio.wait_for(
                    instance.generate_response(
                        prompt=prompt,
                        context=context,
                        history=history,
                        system=system,
                        tool_manager=self._tool_manager,
                    ),
                    timeout=timeout,
                )
                response.latency_ms = (time.monotonic() - t0) * 1000

                if LOG_PROVIDER_CALLS:
                    logger.info(
                        "AIRouter: %s %.0fms attempt=%d success=%s error_type=%r",
                        name, response.latency_ms, attempt,
                        response.success, response.error_type,
                    )

                if response.success:
                    return response, ""

                last_error = response.error or "Provider returned success=False"
                last_error_type = response.error_type or ERR_TRANSIENT

                # Unconfigured — skip silently without marking health
                if last_error_type == ERR_UNCONFIGURED:
                    return None, last_error

                # Permanent / quota — no retries, mark health, fall through
                if last_error_type in _NO_RETRY_TYPES:
                    logger.warning(
                        "AIRouter: %s [%s] — no retry, moving to next provider",
                        name, last_error_type,
                    )
                    self._health.mark_failed(name, last_error_type, last_error)
                    return None, last_error

                logger.warning("AIRouter: %s failed [%s]: %s", name, last_error_type, last_error[:120])

            except asyncio.TimeoutError:
                last_error = f"{name} timed out after {timeout:.1f}s"
                last_error_type = ERR_TIMEOUT
                logger.warning("AIRouter: %s", last_error)

            except Exception as exc:
                last_error = f"{name}: {type(exc).__name__}: {exc}"
                last_error_type = ERR_TRANSIENT
                logger.error("AIRouter: %s", last_error[:200])

            # Only sleep between retries if we have more attempts left
            if attempt < MAX_RETRIES:
                await asyncio.sleep(RETRY_DELAY)

        # All retries exhausted — mark health with general cooldown
        self._health.mark_failed(name, last_error_type, last_error)
        return None, last_error

    @staticmethod
    def _no_providers_response() -> ProviderResponse:
        return ProviderResponse(
            text="",
            provider="none",
            model="none",
            success=False,
            error="No providers available or configured",
        )


# ── Helpers ───────────────────────────────────────────────────────────────────

def _trim_history(history: list[Message] | None) -> list[Message] | None:
    """
    Return at most MAX_HISTORY_SENT * 2 messages from the tail of history.
    Caps token consumption without losing the most recent context.
    """
    if not history:
        return history
    max_msgs = MAX_HISTORY_SENT * 2
    return history[-max_msgs:] if len(history) > max_msgs else history


class _NullProvider(AIProvider):
    """Sentinel used only inside list_providers() to avoid None checks."""
    async def generate_response(self, prompt, context=None, history=None, system=None, tool_manager=None):
        return ProviderResponse(text="", provider="null", model="null", success=False)
