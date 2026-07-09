"""
Google Gemini provider — powered by the google-genai SDK (v2+).

SDK:    google-genai  (pip install google-genai)
Key:    GEMINI_API_KEY environment variable
Model:  configured in config/ai_config.py  (gemini-flash-lite-latest)

Error classification
────────────────────
  429 RESOURCE_EXHAUSTED  → error_type = "quota"     (5 min cooldown, no retry)
  400/401/403 / bad key   → error_type = "permanent" (1 h cooldown, no retry)
  5xx / network error     → error_type = "transient" (60 s cooldown, retried)
  asyncio.TimeoutError    → error_type = "timeout"   (caught by router, retried once)
"""
from __future__ import annotations

import logging
import os
import re

from google import genai
from google.genai import types as genai_types

from ai.providers.base_provider import (
    AIProvider,
    Message,
    ProviderResponse,
    ERR_NONE,
    ERR_PERMANENT,
    ERR_QUOTA,
    ERR_TRANSIENT,
    ERR_TIMEOUT,
    ERR_UNCONFIGURED,
)
from ai.prompts import ANIME_CONTEXT_TEMPLATE, SYSTEM_PROMPT
from config.ai_config import DEFAULT_TEMPERATURE, MAX_RESPONSE_TOKENS, PROVIDER_MODELS

logger = logging.getLogger(__name__)

_MAX_CONTEXT_CHARS: int = 4_000


class GeminiProvider(AIProvider):
    """
    Google Gemini provider using the google-genai async client.

    One client instance is created per GeminiProvider instantiation and
    reused across all calls (the SDK manages its own connection pool).
    """

    provider_name = "gemini"
    model_name    = PROVIDER_MODELS.get("gemini", "gemini-flash-lite-latest")

    def __init__(self) -> None:
        self._client: genai.Client | None = None

    # ── AIProvider interface ───────────────────────────────────────────────────

    def is_configured(self) -> bool:
        return bool(os.environ.get("GEMINI_API_KEY"))

    async def health_check(self) -> bool:
        """
        Lightweight check — returns True when GEMINI_API_KEY is present.
        No live API call (saves quota). Real health is discovered on first use.
        """
        return self.is_configured()

    async def generate_response(
        self,
        prompt: str,
        context: dict | None = None,
        history: list[Message] | None = None,
        system: str | None = None,
        tool_manager=None,
    ) -> ProviderResponse:
        if not self.is_configured():
            return ProviderResponse(
                text="", provider=self.provider_name, model=self.model_name,
                success=False, error="GEMINI_API_KEY not set",
                error_type=ERR_UNCONFIGURED,
            )

        try:
            client = self._get_client()
            contents = self._build_contents(prompt, history)
            system_instruction = self._build_system_instruction(system, context)
            config = genai_types.GenerateContentConfig(
                system_instruction=system_instruction,
                temperature=DEFAULT_TEMPERATURE,
                max_output_tokens=MAX_RESPONSE_TOKENS,
            )

            response = await client.aio.models.generate_content(
                model=self.model_name,
                contents=contents,
                config=config,
            )

            text = self._extract_text(response)
            if not text:
                return ProviderResponse(
                    text="", provider=self.provider_name, model=self.model_name,
                    success=False, error="Empty response from Gemini",
                    error_type=ERR_TRANSIENT,
                )

            return ProviderResponse(
                text=text, provider=self.provider_name, model=self.model_name,
                success=True, error_type=ERR_NONE,
            )

        except Exception as exc:
            error_msg = f"{type(exc).__name__}: {exc}"
            error_type = _classify_gemini_error(error_msg)
            logger.error("GeminiProvider error [%s]: %s", error_type, error_msg[:200])
            return ProviderResponse(
                text="", provider=self.provider_name, model=self.model_name,
                success=False, error=error_msg, error_type=error_type,
            )

    # ── Private helpers ────────────────────────────────────────────────────────

    def _get_client(self) -> genai.Client:
        """Return a cached async-capable Gemini client."""
        if self._client is None:
            self._client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
        return self._client

    def _build_system_instruction(
        self,
        system_override: str | None,
        context: dict | None,
    ) -> str:
        base = system_override or SYSTEM_PROMPT
        if context:
            import json
            ctx = json.dumps(context, ensure_ascii=False)
            if len(ctx) > _MAX_CONTEXT_CHARS:
                ctx = ctx[:_MAX_CONTEXT_CHARS] + "..."
            return base + ANIME_CONTEXT_TEMPLATE.format(context_json=ctx)
        return base

    def _build_contents(
        self,
        prompt: str,
        history: list[Message] | None,
    ) -> list[genai_types.Content]:
        """Convert history + current prompt into a Gemini contents list."""
        contents: list[genai_types.Content] = []
        for msg in (history or []):
            role = "model" if msg.role == "assistant" else "user"
            contents.append(
                genai_types.Content(
                    role=role,
                    parts=[genai_types.Part(text=msg.content)],
                )
            )
        contents.append(
            genai_types.Content(
                role="user",
                parts=[genai_types.Part(text=prompt)],
            )
        )
        return contents

    @staticmethod
    def _extract_text(response) -> str:
        """
        Pull and normalise text from the Gemini response.

        Converts Gemini's double-asterisk bold (**text**) to Telegram
        single-asterisk bold (*text*) so Markdown renders correctly.
        """
        try:
            text = response.text or ""
        except (AttributeError, ValueError):
            try:
                text = "".join(
                    part.text
                    for candidate in response.candidates
                    for part in candidate.content.parts
                    if hasattr(part, "text")
                )
            except Exception:
                return ""

        # Convert **bold** → *bold*  (Gemini → Telegram Markdown)
        text = re.sub(r"\*\*([^*\n]+)\*\*", r"*\1*", text)
        return text.strip()


# ── Error classification ───────────────────────────────────────────────────────

def _classify_gemini_error(error_msg: str) -> str:
    """
    Map a Gemini exception message to an ERR_* constant.

    Signals used:
        429 / RESOURCE_EXHAUSTED  → quota
        400 INVALID_ARGUMENT
        401 / 403
        API_KEY_INVALID           → permanent
        5xx                       → transient
        timeout                   → timeout
    """
    msg = error_msg.upper()

    if "429" in msg or "RESOURCE_EXHAUSTED" in msg:
        return ERR_QUOTA

    if (
        "API_KEY_INVALID" in msg
        or "API KEY NOT VALID" in msg
        or "INVALID_API_KEY" in msg
        or ("400" in msg and "INVALID" in msg)
        or "401" in msg
        or "403" in msg
    ):
        return ERR_PERMANENT

    if "TIMEOUT" in msg or "TIMED OUT" in msg:
        return ERR_TIMEOUT

    return ERR_TRANSIENT
