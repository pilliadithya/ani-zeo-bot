"""
AI configuration constants for Ani Zeo.

All tunable values live here — never hardcode them in router.py or providers.
Changing a provider, model, or timeout requires editing only this file.
"""
from __future__ import annotations

# ── Active provider ──────────────────────────────────────────────────────────
ACTIVE_PROVIDER: str = "gemini"

# ── Provider priority (fallback order) ──────────────────────────────────────
# gemini → groq → nvidia_nim
# nvidia_nim internally cascades: Nemotron → GLM 5.2 (both on NVIDIA Build API,
# same NVIDIA_API_KEY). GLM 5.2 is therefore NOT a separate top-level provider.
PROVIDER_PRIORITY: list[str] = ["gemini", "groq", "nvidia_nim"]

# ── Per-provider model identifiers ──────────────────────────────────────────
# Sources (verified July 2026):
#   gemini              — google.com/gemini  (flash-lite: free, fast)
#   groq                — console.groq.com   (llama-3.3-70b-versatile: free production)
#   nvidia_nim          — build.nvidia.com   (Nemotron 49B: primary, uses NVIDIA_API_KEY)
#   nvidia_nim_fallback — build.nvidia.com   (GLM 5.2: secondary, same NVIDIA_API_KEY)
PROVIDER_MODELS: dict[str, str] = {
    "gemini":              "gemini-flash-lite-latest",
    "groq":                "llama-3.3-70b-versatile",
    "nvidia_nim":          "nvidia/llama-3.3-nemotron-super-49b-v1",
    "nvidia_nim_fallback": "z-ai/glm-5.2",
}

# ── Timeouts (seconds) ──────────────────────────────────────────────────────
REQUEST_TIMEOUT: int         = 15   # default per-provider request timeout
NVIDIA_REQUEST_TIMEOUT: int  = 65   # NVIDIA NIM: reasoning models can be slow
FALLBACK_TIMEOUT: int        = 120  # total time budget across all fallbacks

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
ENABLE_INTENT_ROUTING: bool = True    # keyword intent classifier

# ── Logging ───────────────────────────────────────────────────────────────────
LOG_PROVIDER_CALLS: bool = True

# ── Cache ──────────────────────────────────────────────────────────────────────
CACHE_TTL_SECONDS: int = 3_600

# ── Knowledge Router ───────────────────────────────────────────────────────────
# When True, _build_context_for_route() delegates to KnowledgeRouter.
# Set False to fall back to the original inline routing logic in message_handler.
ENABLE_KNOWLEDGE_ROUTER: bool = True

# ── Web Search ─────────────────────────────────────────────────────────────────
# Master switch.  When False, WebSearchService.search() returns [] immediately.
# Provider is resolved from the registry in services/web_search.py at startup.
# To add a new provider: create services/<name>_search.py, subclass
# BaseWebSearchProvider, and call register_provider("<name>", YourClass).
ENABLE_WEB_SEARCH: bool       = True
WEB_SEARCH_PROVIDER: str      = "brave"     # swappable: "brave" | "serpapi" | any registered key
WEB_SEARCH_MAX_RESULTS: int   = 3           # snippets injected per query
WEB_SEARCH_TIMEOUT: int       = 8           # seconds — hard cap per request
WEB_SEARCH_CACHE_TTL: int     = 1_800       # 30 min — topics don't change mid-conversation
