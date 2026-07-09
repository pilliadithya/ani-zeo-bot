"""
OpenRouter provider.

SDK:    openai (pip install openai) pointed at openrouter.ai base URL
Key:    OPENROUTER_API_KEY environment variable
Status: STUB — not connected until Sprint 2.

OpenRouter exposes an OpenAI-compatible endpoint, which means the
standard openai SDK works with a base_url override — no separate SDK.

Sprint 2 implementation notes:
  1. from openai import AsyncOpenAI
  2. client = AsyncOpenAI(
         api_key=os.environ["OPENROUTER_API_KEY"],
         base_url="https://openrouter.ai/api/v1",
     )
  3. Build messages list from system + history + prompt.
  4. response = await client.chat.completions.create(model=..., messages=...)
  5. Return response.choices[0].message.content.
"""
from __future__ import annotations

import os

from ai.providers.base_provider import AIProvider, Message, ProviderResponse
from config.ai_config import PROVIDER_MODELS

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterProvider(AIProvider):
    provider_name = "openrouter"
    model_name    = PROVIDER_MODELS.get("openrouter", "openai/gpt-4o-mini")

    def is_configured(self) -> bool:
        return bool(os.environ.get("OPENROUTER_API_KEY"))

    async def generate_response(
        self,
        prompt: str,
        context: dict | None = None,
        history: list[Message] | None = None,
        system: str | None = None,
        tool_manager=None,
    ) -> ProviderResponse:
        # TODO (Sprint 2): wire up openai.AsyncOpenAI with OpenRouter base URL
        return ProviderResponse(
            text="[OpenRouter not connected yet — Sprint 2]",
            provider=self.provider_name,
            model=self.model_name,
            success=False,
            error="Provider stub — not implemented",
        )
