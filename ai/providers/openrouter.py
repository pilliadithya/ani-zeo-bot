"""
OpenRouter provider — access to 200+ models via a single OpenAI-compatible API.

Endpoint: https://openrouter.ai/api/v1/chat/completions
SDK:      httpx (already a project dependency — no extra install needed)
Key:      OPENROUTER_API_KEY environment variable
Model:    configured in config/ai_config.py  (openai/gpt-4o-mini by default)

OpenRouter accepts the standard OpenAI messages format and returns the same
response shape, so this provider is structurally identical to GroqProvider
aside from the endpoint URL and auth headers.

Error classification
────────────────────
  HTTP 429                     → error_type = "quota"       (5 min cooldown, no retry)
  HTTP 401 / 403               → error_type = "permanent"   (1 h cooldown, no retry)
  HTTP 5xx                     → error_type = "transient"   (60 s cooldown, retried)
  httpx.TimeoutException       → error_type = "timeout"     (retried once)
  OPENROUTER_API_KEY missing   → error_type = "unconfigured"
"""
from __future__ import annotations

import json
import logging
import os

import httpx

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

_ENDPOINT        = "https://openrouter.ai/api/v1/chat/completions"
_MAX_CONTEXT_CHARS = 4_000

# Optional but recommended by OpenRouter for request attribution
_APP_NAME = "Ani Zeo"
_APP_URL  = "https://github.com/pilliadithya"


class OpenRouterProvider(AIProvider):
    """
    OpenRouter provider using httpx against the OpenAI-compatible endpoint.

    Sends the recommended X-Title and HTTP-Referer headers for attribution
    (https://openrouter.ai/docs#requests).
    """

    provider_name = "openrouter"
    model_name    = PROVIDER_MODELS.get("openrouter", "openai/gpt-4o-mini")

    def is_configured(self) -> bool:
        return bool(os.environ.get("OPENROUTER_API_KEY"))

    async def health_check(self) -> bool:
        """Returns True when OPENROUTER_API_KEY is present — no live API call."""
        return self.is_configured()

    async def generate_response(
        self,
        prompt: str,
        context: dict | None = None,
        history: list[Message] | None = None,
        system: str | None = None,
        tool_manager=None,
    ) -> ProviderResponse:
        api_key = os.environ.get("OPENROUTER_API_KEY")
        if not api_key:
            return ProviderResponse(
                text="", provider=self.provider_name, model=self.model_name,
                success=False, error="OPENROUTER_API_KEY not set",
                error_type=ERR_UNCONFIGURED,
            )

        try:
            messages = self._build_messages(prompt, context, history, system)
            payload = {
                "model":       self.model_name,
                "messages":    messages,
                "temperature": DEFAULT_TEMPERATURE,
                "max_tokens":  MAX_RESPONSE_TOKENS,
            }
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type":  "application/json",
                "HTTP-Referer":  _APP_URL,
                "X-Title":       _APP_NAME,
            }

            async with httpx.AsyncClient(timeout=25.0) as client:
                resp = await client.post(_ENDPOINT, json=payload, headers=headers)

            if resp.status_code != 200:
                error_type = _classify_http_status(resp.status_code, resp.text)
                error_msg  = f"HTTP {resp.status_code}: {resp.text[:200]}"
                logger.error("OpenRouterProvider [%s]: %s", error_type, error_msg)
                return ProviderResponse(
                    text="", provider=self.provider_name, model=self.model_name,
                    success=False, error=error_msg, error_type=error_type,
                )

            data = resp.json()
            text = data["choices"][0]["message"]["content"].strip()
            if not text:
                return ProviderResponse(
                    text="", provider=self.provider_name, model=self.model_name,
                    success=False, error="Empty response from OpenRouter",
                    error_type=ERR_TRANSIENT,
                )

            tokens = data.get("usage", {}).get("total_tokens", 0)
            return ProviderResponse(
                text=text, provider=self.provider_name, model=self.model_name,
                success=True, tokens_used=tokens, error_type=ERR_NONE,
            )

        except httpx.TimeoutException as exc:
            error_msg = f"Timeout: {exc}"
            logger.warning("OpenRouterProvider timeout: %s", error_msg)
            return ProviderResponse(
                text="", provider=self.provider_name, model=self.model_name,
                success=False, error=error_msg, error_type=ERR_TIMEOUT,
            )

        except Exception as exc:
            error_msg = f"{type(exc).__name__}: {exc}"
            logger.error("OpenRouterProvider error: %s", error_msg[:200])
            return ProviderResponse(
                text="", provider=self.provider_name, model=self.model_name,
                success=False, error=error_msg, error_type=ERR_TRANSIENT,
            )

    # ── Private ────────────────────────────────────────────────────────────────

    def _build_messages(
        self,
        prompt: str,
        context: dict | None,
        history: list[Message] | None,
        system_override: str | None,
    ) -> list[dict]:
        """Assemble the OpenAI-style messages list."""
        system_text = system_override or SYSTEM_PROMPT
        if context:
            ctx = json.dumps(context, ensure_ascii=False)
            if len(ctx) > _MAX_CONTEXT_CHARS:
                ctx = ctx[:_MAX_CONTEXT_CHARS] + "..."
            system_text += ANIME_CONTEXT_TEMPLATE.format(context_json=ctx)

        messages: list[dict] = [{"role": "system", "content": system_text}]
        for msg in (history or []):
            if msg.role == "system":
                continue
            role = "assistant" if msg.role == "assistant" else "user"
            messages.append({"role": role, "content": msg.content})
        messages.append({"role": "user", "content": prompt})
        return messages


def _classify_http_status(status: int, body: str = "") -> str:
    if status == 429:
        return ERR_QUOTA
    if status == 403 and "limit exceeded" in body.lower():
        # Key spending-limit exhausted — treat as quota (5 min cooldown) rather
        # than permanent, since the user can raise the limit on the dashboard.
        return ERR_QUOTA
    if 400 <= status < 500:
        # Other 4xx: bad key (401), unauthorised (403), bad request (400/422).
        return ERR_PERMANENT
    if status >= 500:
        return ERR_TRANSIENT
    return ERR_TRANSIENT
