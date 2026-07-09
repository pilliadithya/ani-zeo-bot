"""
ai.providers package — concrete AI provider implementations.

Each provider subclasses AIProvider (base_provider.py) and
implements generate_response().  Import providers via this package
or directly — the router references them by name via PROVIDER_REGISTRY.
"""
from ai.providers.base_provider import AIProvider, Message, ProviderResponse
from ai.providers.gemini import GeminiProvider
from ai.providers.glm import GLMProvider
from ai.providers.groq import GroqProvider
from ai.providers.openrouter import OpenRouterProvider

__all__ = [
    "AIProvider",
    "Message",
    "ProviderResponse",
    "GeminiProvider",
    "GLMProvider",
    "GroqProvider",
    "OpenRouterProvider",
]
