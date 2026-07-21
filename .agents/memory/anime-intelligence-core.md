---
name: Anime Intelligence Core
description: Architecture and key quirks of the watch-order/manga-continuation intelligence layer added to Ani Zeo.
---

## What it is
`services/anime_intelligence.py` — standalone module providing alias resolution, franchise manifest fetching (AniList GraphQL), and continuation planning. Exposed as a module-level singleton `intelligence_service`.

## Pipeline wiring
`ai/message_handler._build_context_for_route()` checks `ContextBuilder.should_resolve_intelligence(intent)` BEFORE `should_search()`. On success it calls `ContextBuilder.from_intelligence_result()`; on exception it falls back to `search_service.search()`. This keeps intelligence failures non-fatal.

## Stop-pattern ordering rule
`_STOP_PATTERNS` in `anime_intelligence.py` uses `re.sub` which finds non-overlapping matches left-to-right. Combined multi-word patterns (e.g. `manga after anime`) MUST appear before their sub-parts (`manga after`, `after anime`) in the list, otherwise the shorter pattern consumes part of the phrase and leaves orphan words.

**Why:** `re.sub` with `|` alternation finds the *leftmost* match, not the *longest* one. Sub-parts listed before the combined phrase win and leave fragments.

**How to apply:** Whenever adding a new multi-word stop phrase whose sub-words are also listed separately, insert the combined pattern first.

## Word-level disambiguation
`AnimeResolver.resolve()` does a first-word ambiguous-table check (step 3) after the full-string checks. This lets "ds stone" → `words[0]="ds"` → hit the ambiguous table → "stone" keyword → Dr. Stone. Without this, multi-word queries with an ambiguous abbreviation as the first token fall through to AniList pass-through.

**How to apply:** New ambiguous-table entries automatically benefit from this. No changes needed when adding new `_AMBIGUOUS_TABLE` entries.

## `_order\b` stop word
A bare `\border\b` stop pattern sits at the end of `_STOP_PATTERNS` to catch "order" left orphaned after a multi-word phrase like "filler skipped order" has its "filler skipped" part removed. Safe because no canonical anime title in the alias table contains the standalone English word "order".

## AIContext new fields
`franchise_context: str = ""` and `intelligence_mode: str = ""` added to `AIContext` with empty-string defaults — fully backward-compatible. `ContextBuilder.to_text()` checks `franchise_context` first (short-circuit before anime/news sections) and renders a pre-formatted block.

## MANGA_CONTINUATION intent
Added to `services/intent.py` with 7 regex patterns. Placed BEFORE `WATCH_ORDER` in the patterns list so more-specific manga phrases match before generic watch-order phrases.
