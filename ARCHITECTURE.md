# Ani Zeo Bot — Architecture

> Generated 2026-07-29. Reflects the codebase as imported; no modifications made.

---

## Overview

Ani Zeo is an AI-powered Telegram anime companion bot. Users interact via Telegram; the bot detects their intent, fetches relevant anime data, injects structured context into an AI prompt, and returns a natural-language response. All AI calls go through a multi-provider router with automatic fallback.

---

## Directory Structure

```
.
├── main.py                  # Entry point — calls bot.main()
├── bot.py                   # All Telegram handlers + polling loop
├── requirements.txt         # Python dependencies
├── profiles.json            # Persistent user profile store
├── watchlist.json           # Persistent per-user watchlists
├── favorites.json           # Persistent per-user favourites
│
├── ai/                      # AI routing, providers, prompts
│   ├── router.py
│   ├── message_handler.py
│   ├── prompts.py
│   ├── formatter.py
│   ├── cache.py
│   └── providers/
│       ├── base_provider.py
│       ├── gemini.py
│       ├── glm.py
│       ├── groq.py
│       ├── nvidia_nim.py
│       └── openrouter.py
│
├── config/
│   └── ai_config.py         # All AI tuning constants & feature flags
│
├── services/                # Intent detection, data retrieval, context building
│   ├── intent.py
│   ├── knowledge_router.py
│   ├── context_builder.py
│   ├── anime_intelligence.py
│   ├── anime_search.py
│   ├── anime_news.py
│   ├── web_search.py
│   ├── brave_search.py
│   └── language_detector.py
│
├── tools/                   # Discrete bot features (search, recs, airing, etc.)
│   ├── tool_manager.py
│   ├── base_tool.py
│   ├── anime_search.py
│   ├── anime_details.py
│   ├── recommendations.py
│   ├── airing.py
│   ├── genre.py
│   ├── season.py
│   ├── character_lookup.py
│   ├── studio_lookup.py
│   └── favorites.py
│
└── scripts/                 # Health checks & isolated test scripts
    ├── health_check.py
    ├── test_intent.py
    ├── test_knowledge_router.py
    ├── test_anime_news.py
    ├── test_anime_search.py
    ├── test_context_builder.py
    ├── test_date_injection.py
    ├── test_intelligence.py
    └── test_news_context.py
```

---

## End-to-End Message Pipeline

```
User (Telegram)
      │
      ▼
  bot.py  ── registers handlers, receives update
      │
      ▼
  ai/message_handler.py
      ├─ Maintains per-user conversation history (30-min sliding window, in-memory)
      ├─ Calls services/intent.py → IntentClassifier (regex-based)
      │       Returns: ANIME_SEARCH | WATCH_ORDER | ANIME_NEWS | TRENDING |
      │                GET_DETAILS | OPEN_QUESTION | RECOMMENDATION | …
      │
      ├─ Calls services/knowledge_router.py → KnowledgeRouter
      │       Maps intent → one or more Knowledge Sources:
      │         INTELLIGENCE  → services/anime_intelligence.py  (watch/read orders, aliases)
      │         SEARCH        → services/anime_search.py        (AniList GraphQL + Jikan REST)
      │         NEWS          → services/anime_news.py          (MAL RSS, Anime Corner RSS, AniList)
      │         WEB           → services/web_search.py          (Brave / SerpAPI)
      │
      ├─ Calls services/context_builder.py → ContextBuilder
      │       Converts raw service data → clean human-readable "Context Block"
      │
      ├─ Builds final prompt:
      │       SYSTEM_PROMPT (ai/prompts.py, includes live date)
      │       + Context Block
      │       + Conversation History
      │       + User Message
      │
      └─ Calls ai/router.py → AIRouter
              Provider priority (config/ai_config.py):
                1. Gemini   (GEMINI_API_KEY)       ← primary
                2. GLM      (ZHIPUAI_API_KEY)       ← optional fallback
                3. NVIDIA NIM (NVIDIA_API_KEY)      ← optional fallback
                4. Groq     (GROQ_API_KEY)          ← optional fallback
                5. OpenRouter (OPENROUTER_API_KEY)  ← optional fallback
              Health tracking with cooldowns — skips unhealthy providers automatically
                    │
                    ▼
              ai/formatter.py → ResponseFormatter
                    Strips preambles ("Sure!", "Of course!"), splits long messages
                    │
                    ▼
              bot.py  ── sends reply to Telegram user
```

---

## Key Components

### `bot.py`
Core Telegram integration. Registers slash-command handlers (`/start`, `/search`, `/ai`, `/watchlist`, `/recommend`, etc.), keyboard button handlers, and the free-text message handler. Contains hardcoded `WATCH_ORDERS` data and delegates AI conversation to `ai/message_handler.py`.

### `ai/router.py`
Central AI dispatcher. Maintains a provider registry, tracks per-provider health (failures + cooldown timers), and implements a waterfall fallback chain. Providers are instantiated lazily on first use.

### `ai/message_handler.py`
Orchestrates the full NLU → context → AI pipeline for each user message. Manages in-memory conversation history keyed by `user_id`. Injects the current date into every system prompt via `ai/prompts.py`.

### `ai/prompts.py`
Stores `SYSTEM_PROMPT` (the v4 personality definition with Tenglish/Hinglish/Tamilish language detection) and response-style templates. `build_system_prompt()` appends the live date dynamically.

### `ai/providers/`
Each file implements a concrete AI backend inheriting `base_provider.py`. The `is_available()` method checks the relevant `*_API_KEY` env var — a missing key silently disables that provider without crashing the bot.

### `ai/formatter.py`
Post-processes AI output: strips sycophantic openers, normalises whitespace, and splits responses that exceed Telegram's 4096-character message limit.

### `ai/cache.py`
In-memory TTL cache for AI responses. Currently disabled via a feature flag in `config/ai_config.py`.

### `config/ai_config.py`
Single source of truth for all AI tunables: active provider, provider priority list, timeouts, max token limits, retry counts, and feature flags (`ENABLE_KNOWLEDGE_ROUTER`, `ENABLE_WEB_SEARCH`, etc.).

### `services/intent.py`
Regex-based `IntentClassifier`. Maps user message text to a typed intent enum (e.g., `ANIME_SEARCH`, `WATCH_ORDER`, `ANIME_NEWS`, `TRENDING`, `GET_DETAILS`, `OPEN_QUESTION`). Supports word-level disambiguation for common short queries.

### `services/knowledge_router.py`
Routes a detected intent to the appropriate data-fetching service(s). Returns a structured result that `ContextBuilder` can consume. Uses a lazy callable pattern (`_try_sources`) to avoid coroutine leaks.

### `services/context_builder.py`
Transforms raw service payloads (search results, news items, watch orders) into a clean, human-readable "Context Block" string. Exposes `ContextBuilder.from_news_result()` and `to_text()` helpers. ANIME_NEWS / TRENDING intents always go through this — never raw RSS to the AI.

### `services/anime_intelligence.py`
Provides structured franchise watch/read orders and resolves common aliases (e.g. "AoT" → "Attack on Titan"). Houses the stop-pattern ordering rule for multi-season franchises.

### `services/anime_search.py`
Wraps the AniList GraphQL API (primary) and the Jikan REST API (fallback) for anime metadata queries.

### `services/anime_news.py`
RSS-based news aggregator. Source priority: MAL (primary) → Anime Corner (secondary) → AniList GraphQL trending (fallback).

### `services/web_search.py` / `services/brave_search.py`
Provider-based web search abstraction. Brave Search is the concrete implementation (requires `BRAVE_API_KEY` + `ENABLE_WEB_SEARCH=True`). Falls back gracefully if the key is absent.

### `services/language_detector.py`
Runtime detector for mixed-script inputs (Tenglish, Hinglish, Tamilish). Informs the AI's response language style.

### `tools/`
Discrete, reusable feature modules (anime search, details, recommendations, airing schedule, genre browser, season browser, character lookup, studio lookup, favourites). Each inherits `base_tool.py`. Registered and looked up via `tools/tool_manager.py` (lazy instantiation). Used by both slash commands in `bot.py` and by AI-driven flows.

### `Data Storage`
All persistence is flat JSON files in the project root — no database:

| File | Contents |
|---|---|
| `profiles.json` | Per-user preferences (nickname, language setting) |
| `watchlist.json` | Per-user watching / completed / plan-to-watch lists |
| `favorites.json` | Per-user favourited anime titles |

Conversation history is **not** persisted — it lives only in RAM for the duration of the process (30-minute sliding window per user).

---

## Required Secrets

| Secret | Required | Purpose |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | ✅ Yes | Telegram Bot API authentication |
| `GEMINI_API_KEY` | ✅ Yes | Primary AI provider (Google Gemini) |
| `ZHIPUAI_API_KEY` | Optional | GLM fallback AI provider |
| `NVIDIA_API_KEY` | Optional | NVIDIA NIM fallback AI provider |
| `GROQ_API_KEY` | Optional | Groq fallback AI provider |
| `OPENROUTER_API_KEY` | Optional | OpenRouter fallback AI provider |
| `BRAVE_API_KEY` | Optional | Web search via Brave Search API |

---

## Running the Bot

```bash
python main.py
```

The bot polls Telegram indefinitely. No web server is started. `TELEGRAM_BOT_TOKEN` and `GEMINI_API_KEY` must be set as Replit Secrets before starting.
