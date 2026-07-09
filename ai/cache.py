"""
ResponseCache — in-memory TTL cache for AI responses.

Prevents redundant provider calls for repeated identical prompts within
the same session.  Not distributed — each bot process has its own store.

Currently disabled via config.ai_config.ENABLE_RESPONSE_CACHE.
Wire into router.py in a later sprint when caching is switched on.
"""
from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass

from config.ai_config import CACHE_TTL_SECONDS


@dataclass
class _CacheEntry:
    response: str
    expires_at: float


class ResponseCache:
    """
    Simple key-value TTL cache.
    Key is a hash of (provider_name, prompt_text).

    Usage (Sprint 3+):
        cache = ResponseCache()
        hit = cache.get("gemini", prompt)
        if hit:
            return hit
        result = await provider.generate_response(prompt)
        cache.set("gemini", prompt, result.text)
    """

    def __init__(self, ttl: int = CACHE_TTL_SECONDS) -> None:
        self._ttl = ttl
        self._store: dict[str, _CacheEntry] = {}

    # ── Public API ─────────────────────────────────────────────────────────────

    def get(self, provider: str, prompt: str) -> str | None:
        """Return a cached response string, or None if missing or expired."""
        key = self._key(provider, prompt)
        entry = self._store.get(key)
        if entry is None:
            return None
        if time.monotonic() > entry.expires_at:
            del self._store[key]
            return None
        return entry.response

    def set(self, provider: str, prompt: str, response: str) -> None:
        """Cache a response with the configured TTL."""
        self._store[self._key(provider, prompt)] = _CacheEntry(
            response=response,
            expires_at=time.monotonic() + self._ttl,
        )

    def invalidate(self, provider: str, prompt: str) -> None:
        """Remove a specific cached entry."""
        self._store.pop(self._key(provider, prompt), None)

    def clear(self) -> None:
        """Flush the entire cache."""
        self._store.clear()

    def size(self) -> int:
        """Number of currently live (non-expired) entries."""
        now = time.monotonic()
        return sum(1 for e in self._store.values() if e.expires_at > now)

    def stats(self) -> dict[str, int]:
        """Diagnostic snapshot: total stored vs live entries."""
        now = time.monotonic()
        live = sum(1 for e in self._store.values() if e.expires_at > now)
        return {"total": len(self._store), "live": live, "expired": len(self._store) - live}

    # ── Private ────────────────────────────────────────────────────────────────

    @staticmethod
    def _key(provider: str, prompt: str) -> str:
        raw = f"{provider}:{prompt}"
        return hashlib.sha256(raw.encode()).hexdigest()[:24]
