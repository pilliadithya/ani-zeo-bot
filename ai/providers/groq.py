"""
Groq provider (Llama / Mixtral via Groq API).

SDK:    groq (pip install groq)
Key:    GROQ_API_KEY environment variable
Status: STUB — not connected until Sprint 2.

Sprint 2 implementation notes:
  1. from groq import AsyncGroq
  2. client = AsyncGroq(api_key=os.environ["GROQ_API_KEY"])
  3. Build messages list from system + history + prompt.
  4. response = await client.chat.completions.create(model=..., messages=...)
  5. Return response.choices[0].message.content.
"""
from __future__ import annotations

import os

from ai.providers.base_provider import AIProvider, Message, ProviderResponse
from config.ai_config import PROVIDER_MODELS


class GroqProvider(AIProvider):
    provider_name = "groq"
    model_name    = PROVIDER_MODELS.get("groq", "llama3-8b-8192")

    def is_configured(self) -> bool:
        return bool(os.environ.get("GROQ_API_KEY"))

    async def generate_response(
        self,
        prompt: str,
        context: dict | None = None,
        history: list[Message] | None = None,
        system: str | None = None,
        tool_manager=None,
    ) -> ProviderResponse:
        # TODO (Sprint 2): wire up groq.AsyncGroq
        return ProviderResponse(
            text="[Groq not connected yet — Sprint 2]",
            provider=self.provider_name,
            model=self.model_name,
            success=False,
            error="Provider stub — not implemented",
        )
