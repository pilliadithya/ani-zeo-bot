# Ani Zeo Bot

An AI-powered Telegram anime companion bot. Helps users discover anime, manage watchlists, and get personalized recommendations.

## Run & Operate

- `python main.py` — start the Telegram bot (runs continuously)
- Required secrets: `TELEGRAM_BOT_TOKEN`, `GEMINI_API_KEY`

## Stack

- Python 3.12
- `python-telegram-bot` 21.10 — Telegram Bot API
- `google-genai` 2.10.0 — Gemini AI (primary), GLM + NVIDIA NIM (fallbacks)
- AniList GraphQL API + Jikan REST API — anime data
- JSON files for persistent storage (watchlist, favorites, profiles)

## Where things live

- `bot.py` — main bot file, all Telegram handlers
- `ai/` — AI routing, providers (Gemini, GLM, NVIDIA NIM, Groq, OpenRouter)
- `config/ai_config.py` — AI tuning constants (model, timeouts, retries)
- `services/` — intent detection
- `tools/` — anime search, details, recommendations, genre, airing, etc.
- `watchlist.json`, `profiles.json` — user data (persisted locally)

## User preferences

_Populate as you build — explicit user instructions worth remembering across sessions._

## Gotchas

- The bot file was originally named `bot (1).py`; it is now `bot.py`. `main.py` imports it.
- AI provider fallback order: Gemini → GLM → NVIDIA NIM (set in `config/ai_config.py`)
- `ZHIPUAI_API_KEY` and `NVIDIA_API_KEY` are optional — only needed for fallback providers
