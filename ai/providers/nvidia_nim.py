"""
NVIDIA NIM provider — OpenAI-compatible REST API via httpx.

Key:      NVIDIA_API_KEY environment variable
Endpoint: https://integrate.api.nvidia.com/v1/chat/completions

Model cascade (tried in order, same key, same endpoint):
  1. nvidia/llama-3.3-nemotron-super-49b-v1  — primary
  2. z-ai/glm-5.2                            — fallback within NVIDIA Build API

If the primary model fails with a retryable error (rate-limit, timeout, or
server error) the provider automatically retries with the fallback model before
returning a failure to the router.  A permanent error (bad API key: 401/403)
skips the cascade immediately — both models share the same key.

Error classification
────────────────────
  HTTP 429             → ERR_QUOTA      (rate-limited; try next model)
  HTTP 401 / 403       → ERR_PERMANENT  (bad key; stop cascade, no retry)
  HTTP 4xx (other)     → ERR_TRANSIENT  (model unavailable/bad request; try next model)
  HTTP 5xx             → ERR_TRANSIENT  (server error; try next model)
  httpx.TimeoutException → ERR_TIMEOUT  (try next model)
  NVIDIA_API_KEY missing → ERR_UNCONFIGURED
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
from config.ai_config import DEFAULT_TEMPERATURE, MAX_RESPONSE_TOKENS, PROVIDER_MODELS, NVIDIA_REQUEST_TIMEOUT

logger = logging.getLogger(__name__)

_ENDPOINT = "https://integrate.api.nvidia.com/v1/chat/completions"
_MAX_CONTEXT_CHARS = 4_000

# Errors that allow falling through to the next model in the cascade.
# Permanent errors (bad key) skip the cascade — the key is shared by all models.
_RETRYABLE_FOR_NEXT_MODEL: frozenset[str] = frozenset({
    ERR_QUOTA,
    ERR_TRANSIENT,
    ERR_TIMEOUT,
})

# Model cascade: tried in order until one succeeds.
_NVIDIA_MODELS: list[str] = [
    PROVIDER_MODELS.get("nvidia_nim",          "nvidia/llama-3.3-nemotron-super-49b-v1"),
    PROVIDER_MODELS.get("nvidia_nim_fallback",  "deepseek-ai/deepseek-v4-flash"),
]


_MODEL_TIMEOUTS: dict[str, float] = {
    _NVIDIA_MODELS[0]: 35.0,   # Nemotron 49B        — ~0.3–5 s observed
    _NVIDIA_MODELS[1]: 35.0,   # DeepSeek V4 Flash   — ~0.9 s observed
}
_DEFAULT_MODEL_TIMEOUT = 35.0


class NvidiaNimProvider(AIProvider):
    provider_name   = "nvidia_nim"
    # Router reads this instead of the global REQUEST_TIMEOUT.
    request_timeout = NVIDIA_REQUEST_TIMEOUT
    # Reflects whichever model last responded; updated per successful call.
    model_name      = _NVIDIA_MODELS[0]

    def is_configured(self) -> bool:
        return bool(os.environ.get("NVIDIA_API_KEY"))

    async def health_check(self) -> bool:
        """
        Returns True when NVIDIA_API_KEY is present.
        No live API call — health is discovered on the first real request.
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
        api_key = os.environ.get("NVIDIA_API_KEY")
        if not api_key:
            return ProviderResponse(
                text="", provider=self.provider_name, model=_NVIDIA_MODELS[0],
                success=False, error="NVIDIA_API_KEY not set",
                error_type=ERR_UNCONFIGURED,
            )

        messages = self._build_messages(prompt, context, history, system)
        last_response: ProviderResponse | None = None

        for model in _NVIDIA_MODELS:
            response = await self._call_model(model, messages, api_key)
            last_response = response

            if response.success:
                # Update instance model_name so health_status() reflects reality.
                self.model_name = model
                logger.info(
                    "NvidiaNimProvider: request answered by model=%s", model,
                )
                return response

            # Bad key or unconfigured — shared across all models; stop immediately.
            if response.error_type in (ERR_PERMANENT, ERR_UNCONFIGURED):
                logger.error(
                    "NvidiaNimProvider: non-retryable error [%s] on model=%s "
                    "— stopping cascade",
                    response.error_type, model,
                )
                return response

            # Retryable: rate-limit, timeout, server/model error — try next model.
            idx = _NVIDIA_MODELS.index(model)
            remaining = _NVIDIA_MODELS[idx + 1:]
            if remaining:
                logger.warning(
                    "NvidiaNimProvider: model=%s failed [%s] — trying %s",
                    model, response.error_type, remaining[0],
                )

        # All models in the cascade exhausted.
        return last_response or ProviderResponse(
            text="", provider=self.provider_name, model=_NVIDIA_MODELS[-1],
            success=False, error="All NVIDIA models exhausted",
            error_type=ERR_TRANSIENT,
        )

    # ── Private ───────────────────────────────────────────────────────────────

    async def _call_model(
        self,
        model: str,
        messages: list[dict],
        api_key: str,
    ) -> ProviderResponse:
        """Issue a single non-streaming chat-completion request for *model*."""
        payload = {
            "model":       model,
            "messages":    messages,
            "temperature": DEFAULT_TEMPERATURE,
            "max_tokens":  MAX_RESPONSE_TOKENS,
        }
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type":  "application/json",
        }

        httpx_timeout = _MODEL_TIMEOUTS.get(model, _DEFAULT_MODEL_TIMEOUT)
        try:
            async with httpx.AsyncClient(timeout=httpx_timeout) as client:
                resp = await client.post(_ENDPOINT, json=payload, headers=headers)

            if resp.status_code != 200:
                error_type = _classify_http_status(resp.status_code)
                error_msg  = f"HTTP {resp.status_code}: {resp.text[:200]}"
                logger.error(
                    "NvidiaNimProvider model=%s [%s]: %s", model, error_type, error_msg,
                )
                return ProviderResponse(
                    text="", provider=self.provider_name, model=model,
                    success=False, error=error_msg, error_type=error_type,
                )

            data = resp.json()
            # Standard OpenAI-compatible field; reasoning models also populate
            # reasoning_content but we only need the final answer in content.
            text = data["choices"][0]["message"]["content"].strip()
            if not text:
                return ProviderResponse(
                    text="", provider=self.provider_name, model=model,
                    success=False, error="Empty response from NVIDIA NIM",
                    error_type=ERR_TRANSIENT,
                )

            tokens = data.get("usage", {}).get("total_tokens", 0)
            return ProviderResponse(
                text=text, provider=self.provider_name, model=model,
                success=True, tokens_used=tokens, error_type=ERR_NONE,
            )

        except httpx.TimeoutException as exc:
            error_msg = f"Timeout: {exc}"
            logger.warning("NvidiaNimProvider model=%s timeout: %s", model, error_msg)
            return ProviderResponse(
                text="", provider=self.provider_name, model=model,
                success=False, error=error_msg, error_type=ERR_TIMEOUT,
            )

        except Exception as exc:
            error_msg = f"{type(exc).__name__}: {exc}"
            logger.error(
                "NvidiaNimProvider model=%s error: %s", model, error_msg[:200],
            )
            return ProviderResponse(
                text="", provider=self.provider_name, model=model,
                success=False, error=error_msg, error_type=ERR_TRANSIENT,
            )

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
    """
    Map an HTTP status code to an ERR_* constant.

    401 / 403  → ERR_PERMANENT  Bad API key — stop the cascade.
    429        → ERR_QUOTA      Model-level rate limit — try next model.
    Other 4xx  → ERR_TRANSIENT  Model unavailable / bad request — try next model.
    5xx        → ERR_TRANSIENT  Server-side error — try next model.
    """
    if status in (401, 403):
        return ERR_PERMANENT
    if status == 429:
        return ERR_QUOTA
    # 4xx (400, 404, 422, …) and 5xx are all retryable at the model level
    return ERR_TRANSIENT
