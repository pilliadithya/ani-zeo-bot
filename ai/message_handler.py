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

import logging
import time

from telegram import Update
from telegram.error import BadRequest
from telegram.ext import ContextTypes
from telegram.constants import ParseMode

from ai.formatter import ResponseFormatter
from ai.providers.base_provider import Message
from ai.router import AIRouter
from config.ai_config import MAX_HISTORY_TURNS

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
_router = AIRouter()


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

    logger.info("AI chat | user=%d | %r", user_id, text[:120])
    await message.chat.send_action("typing")

    history = _load_history(user_id)

    try:
        response = await _router.route(
            prompt=text,
            history=history or None,
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
