"""
ResponseFormatter — post-processes AI provider output before it is sent
to Telegram.

Responsibilities:
  - Strip AI preamble filler phrases ("Sure!", "Of course!", etc.).
  - Strip code fences and normalise whitespace.
  - Enforce Telegram message length limits.
  - Split oversized messages at natural paragraph breaks.
  - Provide structured formatters for recommendations and errors.
"""
from __future__ import annotations

import re

# Telegram hard limits
TELEGRAM_MAX_LENGTH:   int = 4_096
TELEGRAM_CAPTION_LIMIT: int = 1_024

# Soft limit — messages are trimmed here to end on a complete sentence.
SOFT_LIMIT: int = 3_800

# ── AI preamble patterns ──────────────────────────────────────────────────────
# These opener phrases add no value and break the card-style layout.
# Applied once, at the very start of the reply, before any other processing.

_PREAMBLE_RE = re.compile(
    r"^("
    # Single-word openers
    r"Sure[!.]?|"
    r"Absolutely[!.]?|"
    r"Certainly[!.]?|"
    r"Definitely[!.]?|"
    r"Of\s+course[!.]?|"
    # Greeting openers
    r"Great\s+(question|choice|pick)[!.]?|"
    r"Good\s+(question|choice|ask)[!.]?|"
    r"Excellent\s+(question|choice)[!.]?|"
    # "Happy to …" / "I'd be happy to …" patterns
    r"(?:I'?d\s+be\s+)?(?:happy|glad|delighted)\s+to\s+help[^.!]*[.!]?|"
    r"(?:I'?m\s+)?(?:happy|glad)\s+you\s+asked[^.!]*[.!]?|"
    r"I'?d\s+love\s+to\s+help[^.!]*[.!]?|"
    # "Let me …" starters
    r"Let\s+me\s+(?:help|show|explain|break|walk)[^.!]*[.!]?|"
    # "Hey [Name]!" greetings — strip the greeting and the name
    r"Hey\s+\w+[!,]\s*"
    r")"
    r"[,!\s]*",
    re.IGNORECASE,
)


class ResponseFormatter:
    """
    Stateless formatter.  All methods are classmethods — no instantiation
    needed.  Call ResponseFormatter.format_reply(text) directly.
    """

    @classmethod
    def format_reply(cls, text: str) -> str:
        """
        Main entry point.  Cleans and trims an AI-generated reply
        so it is safe to send as a Telegram message.

        Pipeline:
          1. Strip AI preamble filler phrases
          2. Strip code fences
          3. Normalise whitespace
          4. Trim to soft limit
        """
        text = cls._strip_ai_preamble(text)
        text = cls._strip_code_fences(text)
        text = cls._normalise_whitespace(text)
        text = cls._trim_to_soft_limit(text)
        return text

    @classmethod
    def format_error(cls, error: str | None = None) -> str:
        """Return a user-friendly error message."""
        if error:
            return (
                f"Something went wrong: {error}\n\n"
                "Please try again or use a command like /help."
            )
        return "I couldn't generate a response right now. Please try again shortly."

    @classmethod
    def format_recommendations(cls, recommendations: list[dict]) -> str:
        """
        Format a list of recommendation dicts into a numbered Telegram message.

        Expected dict shape: {"title": str, "reason": str}
        """
        if not recommendations:
            return "No recommendations found."
        lines = ["🎯 Anime Recommendations\n"]
        for i, rec in enumerate(recommendations, 1):
            title  = rec.get("title", "Unknown")
            reason = rec.get("reason", "")
            lines.append(f"{i}. {title}")
            if reason:
                lines.append(f"   {reason}")
        return "\n".join(lines)

    @classmethod
    def split_long_message(cls, text: str) -> list[str]:
        """
        Split a message that exceeds TELEGRAM_MAX_LENGTH into chunks,
        preferring paragraph breaks over hard character boundaries.
        """
        if len(text) <= TELEGRAM_MAX_LENGTH:
            return [text]

        parts: list[str] = []
        while text:
            chunk = text[:TELEGRAM_MAX_LENGTH]
            # Prefer paragraph break, then single newline, then hard cut.
            for sep in ("\n\n", "\n"):
                idx = chunk.rfind(sep)
                if idx > TELEGRAM_MAX_LENGTH // 2:
                    chunk = text[:idx]
                    break
            parts.append(chunk.strip())
            text = text[len(chunk):].strip()

        return parts

    # ── Private helpers ───────────────────────────────────────────────────────

    @classmethod
    def _strip_ai_preamble(cls, text: str) -> str:
        """
        Remove AI filler opener phrases from the start of a reply.

        Handles patterns like:
          "Sure! Here's the watch order..."  →  "Here's the watch order..."
          "Of course! Dragon Ball has..."    →  "Dragon Ball has..."
          "Hey Adi! Here's what you need:"   →  "Here's what you need:"
          "Absolutely! Let me help you."     →  ""  (if nothing follows)

        Only strips from the very beginning of the text, never mid-reply.
        Runs once; does not loop (prevents over-stripping).
        """
        stripped = _PREAMBLE_RE.sub("", text, count=1).strip()
        # If stripping left nothing (the entire reply was filler), return original
        return stripped if stripped else text

    @classmethod
    def _strip_code_fences(cls, text: str) -> str:
        """Remove Markdown code fences (``` … ```) from AI output."""
        return re.sub(r"```[a-z]*\n?", "", text).replace("```", "")

    @classmethod
    def _normalise_whitespace(cls, text: str) -> str:
        """Collapse 3+ consecutive blank lines and strip leading/trailing space."""
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @classmethod
    def _trim_to_soft_limit(cls, text: str) -> str:
        """
        Trim to SOFT_LIMIT, ending at the last complete sentence where possible.
        Appends '[...]' to indicate truncation.
        """
        if len(text) <= SOFT_LIMIT:
            return text

        truncated = text[:SOFT_LIMIT]
        last_sentence = max(
            truncated.rfind("."),
            truncated.rfind("!"),
            truncated.rfind("?"),
        )
        if last_sentence > int(SOFT_LIMIT * 0.7):
            truncated = truncated[: last_sentence + 1]

        return truncated + "\n\n[...]"
