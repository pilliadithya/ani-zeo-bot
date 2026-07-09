"""
AI configuration constants for Ani Zeo.

All tunable values live here — never hardcode them in router.py or providers.
Changing a provider, model, or timeout requires editing only this file.
"""
from __future__ import annotations

# ── Active provider ──────────────────────────────────────────────────────────
ACTIVE_PROVIDER: str = "gemini"

# ── Provider priority (fallback order) ──────────────────────────────────────
# gemini → groq → nvidia_nim → openrouter
# glm is kept in the registry but excluded from auto-fallback unless added here.
PROVIDER_PRIORITY: list[str] = ["gemini", "groq", "nvidia_nim", "openrouter"]

# ── Per-provider model identifiers ──────────────────────────────────────────
PROVIDER_MODELS: dict[str, str] = {
    "gemini":     "gemini-flash-lite-latest",
    "groq":       "llama3-8b-8192",
    "nvidia_nim": "meta/llama-3.3-70b-instruct",
    "openrouter": "openai/gpt-4o-mini",
    "glm":        "glm-4-flash",
}

# ── Timeouts (seconds) ──────────────────────────────────────────────────────
REQUEST_TIMEOUT: int  = 15   # per-provider request timeout
FALLBACK_TIMEOUT: int = 35   # total time budget across all fallbacks

# ── Retry settings ───────────────────────────────────────────────────────────
# Retries apply only to transient / timeout errors.
# Permanent and quota errors are never retried — the router moves immediately
# to the next provider and applies the appropriate cooldown.
MAX_RETRIES: int   = 2
RETRY_DELAY: float = 1.0     # seconds between retry attempts

# ── Provider health cooldowns ──────────────────────────────────────────────────
# How long a failed provider is skipped before being retried.
HEALTH_COOLDOWN:     float = 60.0     # transient / timeout (60 s)
QUOTA_COOLDOWN:      float = 300.0    # 429 / rate-limited  (5 min)
PERMANENT_COOLDOWN:  float = 3_600.0  # invalid API key     (1 h)

# ── Context / token limits ───────────────────────────────────────────────────
MAX_CONTEXT_LENGTH: int  = 6_000   # characters of context injected into prompt
MAX_RESPONSE_TOKENS: int = 512     # max tokens requested from provider (reduced from 800)
MAX_HISTORY_TURNS: int   = 15      # turns stored in conversation memory per user
MAX_HISTORY_SENT: int    = 8       # turns actually sent to the API per request

# ── Temperature ───────────────────────────────────────────────────────────────
DEFAULT_TEMPERATURE: float = 0.7

# ── Feature flags ─────────────────────────────────────────────────────────────
ENABLE_AI_CHAT: bool        = True    # natural-language conversation active
ENABLE_TOOL_CALLING: bool   = False   # AI-driven tool calls
ENABLE_RESPONSE_CACHE: bool = False   # in-memory response caching
ENABLE_INTENT_ROUTING: bool = False   # keyword intent classifier

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_PROVIDER_CALLS: bool = True

# ── Cache ──────────────────────────────────────────────────────────────────────
CACHE_TTL_SECONDS: int = 3_600
