---
name: v4 NLU + Personality
description: Key decisions from the v4 sprint — language detection, new intent patterns, personality prompt design.
---

## Language Detector (`services/language_detector.py`)
Word-set lookup against unambiguous romanised marker words per language (Telugu/Hindi/Tamil).
Threshold: 1 marker word = confident detection.
Wired into `ai/message_handler._build_context_for_route()` — overrides profile language per-message.

**Why:** Profile language (set at onboarding) goes stale. Users mix languages mid-conversation.
Runtime detection means AI always responds in the language the user is actually writing.

**How to apply:** When extending marker sets, use only unambiguous words that never appear in plain English or anime titles. Avoid short generic words ("da", "la", "na").

## Intent gaps filled in v4
`GET_DETAILS` and `OPEN_QUESTION` previously had zero entries in `_PATTERNS` — any casual title query ("is Naruto good?", "just finished it") fell through to `UNKNOWN`.
Added 7 `GET_DETAILS` patterns and 11 `OPEN_QUESTION` patterns before the broad `SEARCH_ANIME` catch-all.

**Why:** UNKNOWN intent = no context search, lower-quality AI answer.

## Formatter preamble guard
`_strip_ai_preamble()` returns the original text if stripping would leave an empty string.
This prevents Telegram from receiving an empty message when the entire AI reply is a filler opener (edge case, never happens in real usage but important safety net).

## SYSTEM_PROMPT size
v4 SYSTEM_PROMPT is ~8531 chars (~2100 tokens). Acceptable for Gemini Flash and Groq Llama.
If token budget becomes a concern, trim the language adaptation examples first (they're the largest non-structural section).
