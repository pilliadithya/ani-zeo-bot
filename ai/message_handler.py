"""
handle_text_message — natural conversation entry point for all non-command text.

Registered in bot.py in handler group 1 (after handle_button in group 0).
Group 0 catches reply-keyboard button labels; group 1 handles all remaining text.

Pipeline:
  text message
      │
      ├── Known keyboard button label? → skip (group 0 already handled it)
      │
      ├── Send "typing" action
      │
      ├── Load per-user conversation history (sliding window, 30 min idle expiry)
      │
      ├── AIRouter.route(prompt, history)  [Gemini → GLM → NVIDIA NIM]
      │
      ├── Success → reply (Markdown if safe, else plain text) + save to history
      │
      └── Failure → friendly error message
"""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path

from telegram import Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from ai.formatter import ResponseFormatter
from ai.providers.base_provider import Message
from ai.prompts import SYSTEM_PROMPT
from ai.router import AIRouter
from config.ai_config import MAX_HISTORY_TURNS, ENABLE_INTENT_ROUTING
from services.intent import Intent, IntentClassifier
from services.anime_search import search_service
from services.context_builder import ContextBuilder
from watchlist import WatchlistManager, parse as parse_watchlist, is_watchlist_phrase
from watchlist.manager import normalise_status
from watchlist.store import VALID_STATUSES

logger = logging.getLogger(__name__)

# ── Reply-keyboard button labels ──────────────────────────────────────────────
# Handled by handle_button() in group 0 — skip here to avoid double-processing.
_KEYBOARD_LABELS: frozenset[str] = frozenset({
    "🔍 Search",
    "🏆 Top Anime",
    "📺 Season",
    "🎲 Random",
    "🎭 Character",
    "🏢 Studio",
    "📚 Genre",
    "🔥 Trending",
    "📰 News",
    "❓ Help",
})

# ── Conversation memory ───────────────────────────────────────────────────────
# In-process only — never persisted to disk. Expires after 30 min idle.

_IDLE_TIMEOUT: float = 30 * 60          # 30 minutes
_MAX_MESSAGES: int   = MAX_HISTORY_TURNS * 2  # user + assistant per turn

_conversations:  dict[int, list[Message]] = {}
_last_activity:  dict[int, float]         = {}


def _load_history(user_id: int) -> list[Message]:
    """Return current history, expiring stale sessions lazily."""
    now = time.monotonic()
    stale = [uid for uid, ts in _last_activity.items() if now - ts > _IDLE_TIMEOUT]
    for uid in stale:
        _conversations.pop(uid, None)
        _last_activity.pop(uid, None)
    _last_activity[user_id] = now
    return _conversations.setdefault(user_id, [])


def _save_turn(user_id: int, user_text: str, assistant_text: str) -> None:
    """Append a completed turn and trim to the sliding window."""
    history = _conversations.setdefault(user_id, [])
    history.append(Message(role="user",      content=user_text))
    history.append(Message(role="assistant", content=assistant_text))
    if len(history) > _MAX_MESSAGES:
        _conversations[user_id] = history[-_MAX_MESSAGES:]
    _last_activity[user_id] = time.monotonic()


def clear_history(user_id: int) -> None:
    """Clear a user's conversation history (callable by /reset command)."""
    _conversations.pop(user_id, None)
    _last_activity.pop(user_id, None)


# ── Singletons ────────────────────────────────────────────────────────────────
_router     = AIRouter()
_wl_mgr     = WatchlistManager()
_classifier = IntentClassifier()

# ── User profile reader ───────────────────────────────────────────────────────
# Reads profiles.json directly — avoids importing bot.py (circular dep).
_PROFILES_FILE = Path("profiles.json")


def _read_user_profile(user_id: int) -> dict:
    """Return the stored profile dict for *user_id*, or {} on any error."""
    try:
        data = json.loads(_PROFILES_FILE.read_text(encoding="utf-8"))
        return data.get(str(user_id), {})
    except Exception:
        return {}


# ── Context builder ───────────────────────────────────────────────────────────

async def _build_context_for_route(
    text: str,
    intent: Intent,
    user_id: int,
) -> str | None:
    """
    Build a context-enriched system prompt to pass to the AI router.

    Returns SYSTEM_PROMPT + clean context block when useful context exists,
    or None to let the router use SYSTEM_PROMPT unchanged.

    Pipeline:
      - Always injects user personalisation (nickname, language, intent).
      - For anime-specific intents, searches for the anime and injects
        a clean structured context block (not raw API JSON).
      - For all other intents, injects user-only context (no search call).
    """
    profile = _read_user_profile(user_id)

    if ContextBuilder.should_search(intent):
        result  = await search_service.search(text)
        ai_ctx  = ContextBuilder.from_search_result(result, intent, profile)
        logger.info(
            "ContextBuilder | user=%d | intent=%s | found=%s | title=%r",
            user_id, intent.name, ai_ctx.found,
            ai_ctx.anime.display_title if ai_ctx.anime else None,
        )
    else:
        ai_ctx = ContextBuilder.build_user_only(intent, profile, text)

    context_block = ContextBuilder.to_text(ai_ctx)
    if not context_block:
        return None

    return SYSTEM_PROMPT + context_block


# ── Watchlist action dispatcher ───────────────────────────────────────────────

def _handle_watchlist_action(action, user_id: int) -> str:
    """
    Dispatch a parsed WatchlistAction to WatchlistManager and return the
    reply string.  Called synchronously — all storage I/O is blocking JSON.
    """
    from watchlist.nlp import WatchlistAction  # local import avoids circular ref

    if action.action == "show":
        return _wl_mgr.show(user_id)

    if action.action == "add":
        _, msg = _wl_mgr.add(user_id, action.anime, action.status or "planned")
        return msg

    if action.action == "remove":
        _, msg = _wl_mgr.remove(user_id, action.anime)
        return msg

    if action.action == "mark":
        _, msg = _wl_mgr.update_status(user_id, action.anime, action.status or "planned")
        return msg

    return "Sorry, I didn't understand that watchlist command."


# ── Main handler ──────────────────────────────────────────────────────────────

async def handle_text_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
) -> None:
    """
    Telegram MessageHandler callback for non-command text.

    Registered in bot.py:
        app.add_handler(
            MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message),
            group=1,
        )
    """
    message = update.message
    if not message or not message.text:
        return

    text    = message.text.strip()
    user_id = update.effective_user.id if update.effective_user else 0

    if text in _KEYBOARD_LABELS:
        return

    # ── Watchlist NLP intercept ───────────────────────────────────────────────
    # Handle watchlist phrases directly without sending them to the AI router.
    if is_watchlist_phrase(text):
        action = parse_watchlist(text)
        if action is not None:
            await message.chat.send_action("typing")
            reply = _handle_watchlist_action(action, user_id)
            try:
                await message.reply_text(reply, parse_mode="Markdown")
            except Exception:
                await message.reply_text(reply)
            logger.info(
                "Watchlist NLP | user=%d | action=%s anime=%r status=%r",
                user_id, action.action, action.anime, action.status,
            )
            return
    # ── End watchlist intercept ───────────────────────────────────────────────

    # ── Intent detection ──────────────────────────────────────────────────────
    # Classify before routing.  The detected intent is stored in user_data so
    # any handler in bot.py can read it; it does NOT change which AI provider
    # is called — routing remains purely health/fallback driven.
    intent: Intent = Intent.UNKNOWN
    if ENABLE_INTENT_ROUTING:
        intent, confidence = _classifier.classify_with_confidence(text)
        context.user_data["last_intent"]       = intent
        context.user_data["last_intent_label"] = _classifier.display_name(intent)
        logger.info(
            "Intent | user=%d | %s (%s) | confidence=%.1f | %r",
            user_id,
            intent.name,
            _classifier.display_name(intent),
            confidence,
            text[:80],
        )
    # ── End intent detection ──────────────────────────────────────────────────

    # ── Context building ──────────────────────────────────────────────────────
    # Build a clean structured context block and inject it into the system
    # prompt.  The AI NEVER receives raw API JSON — only the clean text block
    # produced by ContextBuilder.to_text().
    # Returns None when no useful context exists → router uses SYSTEM_PROMPT.
    route_system: str | None = None
    if ENABLE_INTENT_ROUTING:
        try:
            route_system = await _build_context_for_route(text, intent, user_id)
        except Exception as exc:
            # Context building failure must never block the AI response.
            logger.warning("ContextBuilder | failed | user=%d | %s", user_id, exc)
    # ── End context building ──────────────────────────────────────────────────

    logger.info("AI chat | user=%d | %r", user_id, text[:120])
    await message.chat.send_action("typing")

    history = _load_history(user_id)

    try:
        response = await _router.route(
            prompt=text,
            history=history or None,
            system=route_system,
        )
    except Exception as exc:
        logger.error("AI chat | unexpected error | user=%d | %s", user_id, exc)
        await message.reply_text("Something went wrong. Please try again.")
        return

    if not response.success or not response.text:
        logger.warning(
            "AI chat | all providers failed | user=%d | %s",
            user_id, response.error,
        )
        await message.reply_text(
            "I'm having trouble connecting right now. Please try again shortly."
        )
        return

    reply = ResponseFormatter.format_reply(response.text)
    if not reply:
        return

    # Send with Markdown; fall back to plain text if Telegram rejects the formatting.
    chunks = ResponseFormatter.split_long_message(reply)
    for chunk in chunks:
        try:
            await message.reply_text(chunk, parse_mode=ParseMode.MARKDOWN)
        except BadRequest:
            await message.reply_text(chunk)

    _save_turn(user_id, text, response.text)

    logger.info(
        "AI chat | replied | user=%d | provider=%s | %.0fms",
        user_id, response.provider, response.latency_ms,
    )
