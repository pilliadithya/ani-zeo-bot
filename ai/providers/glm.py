"""
Zhipu AI / GLM provider — ZhipuAI OpenAI-compatible REST API via httpx.

Key:      ZHIPUAI_API_KEY environment variable
Endpoint: https://open.bigmodel.cn/api/paas/v4/chat/completions
Model:    configured in config/ai_config.py  (default: glm-4-flash)

Error classification
────────────────────
  HTTP 429                → error_type = "quota"     (5 min cooldown, no retry)
  HTTP 401 / 403          → error_type = "permanent" (1 h cooldown, no retry)
  HTTP 5xx                → error_type = "transient" (60 s cooldown, retried)
  httpx.TimeoutException  → error_type = "timeout"   (retried once)
  ZHIPUAI_API_KEY missing → error_type = "unconfigured"
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

_ENDPOINT = "https://open.bigmodel.cn/api/paas/v4/chat/completions"
_MAX_CONTEXT_CHARS = 4_000


class GLMProvider(AIProvider):
    provider_name = "glm"
    model_name    = PROVIDER_MODELS.get("glm", "glm-4-flash")

    def is_configured(self) -> bool:
        return bool(os.environ.get("ZHIPUAI_API_KEY"))

    async def health_check(self) -> bool:
        """
        Returns True when ZHIPUAI_API_KEY is present.
        No live API call — health discovered on first real request.
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
        api_key = os.environ.get("ZHIPUAI_API_KEY")
        if not api_key:
            return ProviderResponse(
                text="", provider=self.provider_name, model=self.model_name,
                success=False, error="ZHIPUAI_API_KEY not set",
                error_type=ERR_UNCONFIGURED,
            )

        try:
            messages = self._build_messages(prompt, context, history, system)
            payload = {
                "model": self.model_name,
                "messages": messages,
                "temperature": DEFAULT_TEMPERATURE,
                "max_tokens": MAX_RESPONSE_TOKENS,
            }
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            }

            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(_ENDPOINT, json=payload, headers=headers)

            # Classify HTTP errors before raising
            if resp.status_code != 200:
                error_type = _classify_http_status(resp.status_code)
                error_msg = f"HTTP {resp.status_code}: {resp.text[:200]}"
                logger.error("GLMProvider [%s]: %s", error_type, error_msg)
                return ProviderResponse(
                    text="", provider=self.provider_name, model=self.model_name,
                    success=False, error=error_msg, error_type=error_type,
                )

            data = resp.json()
            text = data["choices"][0]["message"]["content"].strip()
            if not text:
                return ProviderResponse(
                    text="", provider=self.provider_name, model=self.model_name,
                    success=False, error="Empty response from GLM",
                    error_type=ERR_TRANSIENT,
                )

            tokens = data.get("usage", {}).get("total_tokens", 0)
            return ProviderResponse(
                text=text, provider=self.provider_name, model=self.model_name,
                success=True, tokens_used=tokens, error_type=ERR_NONE,
            )

        except httpx.TimeoutException as exc:
            error_msg = f"Timeout: {exc}"
            logger.warning("GLMProvider timeout: %s", error_msg)
            return ProviderResponse(
                text="", provider=self.provider_name, model=self.model_name,
                success=False, error=error_msg, error_type=ERR_TIMEOUT,
            )

        except Exception as exc:
            error_msg = f"{type(exc).__name__}: {exc}"
            logger.error("GLMProvider error: %s", error_msg[:200])
            return ProviderResponse(
                text="", provider=self.provider_name, model=self.model_name,
                success=False, error=error_msg, error_type=ERR_TRANSIENT,
            )

    # ── Private ───────────────────────────────────────────────────────────────

    def _build_messages(
        self,
        prompt: str,
        context: dict | None,
        history: list[Message] | None,
        system_override: str | None,
    ) -> list[dict]:
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


def _classify_http_status(status: int) -> str:
    if status == 429:
        return ERR_QUOTA
    if 400 <= status < 500:
        # All 4xx errors are deterministic client/config problems — don't retry.
        # 401/403 → bad key; 400/404/422 → bad request or model name.
        return ERR_PERMANENT
    if status >= 500:
        return ERR_TRANSIENT
    return ERR_TRANSIENT
