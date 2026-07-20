---
name: Date Injection
description: How the current date is injected into every AI system prompt at runtime.
---

## Rule

`build_system_prompt()` in `ai/prompts.py` is the single source of truth for the AI system prompt with a live date. It returns `SYSTEM_PROMPT + date_block` where `date_block` is generated fresh via `datetime.now()` on every call.

**Why:** The AI has a training cutoff and would otherwise assume stale dates for time-sensitive answers (seasonal anime, airing schedules, "this year's" releases, etc.).

## Two injection paths in message_handler.py

1. **Context path** (`_build_context_for_route` returns a string):
   `return build_system_prompt() + context_block`
   — date sits between the base prompt and the ContextBuilder block.

2. **No-context path** (`route_system` stays `None` after the context block):
   `if route_system is None: route_system = build_system_prompt()`
   — guarantees providers never fall back to the bare `SYSTEM_PROMPT`.

**Why two paths:** Providers do `system_override or SYSTEM_PROMPT` — if `route_system` is `None`, the fallback is the undated constant. The explicit assignment after the context block closes that gap without touching any provider.

## Date format

```
Current date: Monday, 20 July 2026 (Year: 2026, Month: July, Day: 20).
Always use the above date as today's reference. Never assume an earlier date.
```

Fields given separately (Year, Month, Day) so the AI can parse date-relative phrases correctly.

## What was NOT changed

- `ContextBuilder` — untouched; date is outside the context block
- All providers — untouched; they receive the assembled string as `system_override`
- `SYSTEM_PROMPT` constant — kept as the undated base; `build_system_prompt()` wraps it
- Onboarding, intent detection, watchlist, Telegram UI — none touched
