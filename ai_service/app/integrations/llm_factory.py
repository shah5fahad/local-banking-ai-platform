"""LLM provider factory - env-driven provider selection.

Providers: openai (default), anthropic, google, nvidia, fake (for tests).
LLM_PROVIDER, LLM_MODEL, LLM_TEMPERATURE, LLM_MAX_TOKENS read from AISettings.
"""
from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import Any
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, HumanMessage

try:
    from langchain_core.language_models.fake_chat_models import FakeListChatModel
except ImportError:
    from langchain_core.language_models.fake import FakeListChatModel  # type: ignore[no-redef]

from app.core.config import AISettings

logger = logging.getLogger(__name__)


def extract_message_text(content: Any) -> str:
    """Extract plain text string from LLM message content (handles str, list of dicts/strings)."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                parts.append(str(item.get("text", "")))
            elif hasattr(item, "text"):
                parts.append(str(getattr(item, "text", "")))
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(content) if content is not None else ""


def sanitize_messages_for_llm(
    messages: Sequence[AnyMessage] | None,
    user_message: str | None = None,
) -> list[AnyMessage]:
    """Sanitize message list for models like Gemini:
    1. Strip trailing assistant messages (prevent 'model prefilling' error).
    2. Ensure message list is never empty (contents are required).
    """
    clean: list[AnyMessage] = list(messages or [])
    while clean and isinstance(clean[-1], AIMessage):
        clean.pop()

    if not clean and user_message:
        clean = [HumanMessage(content=user_message)]

    return clean


class FakeChatModel(FakeListChatModel):
    """Fake chat model for testing with tool binding support."""

    def bind_tools(self, *args: Any, **kwargs: Any) -> FakeChatModel:
        return self


_test_fake_llm: BaseChatModel | None = None


def set_test_fake_llm(llm: BaseChatModel | None) -> None:
    """Set global fake LLM override for testing."""
    global _test_fake_llm
    _test_fake_llm = llm


def create_llm(settings: AISettings, temperature: float | None = None) -> BaseChatModel:
    """Create a ChatModel based on LLM_PROVIDER setting.

    Providers:
    - 'openai': uses langchain_openai.ChatOpenAI
    - 'anthropic': uses langchain_anthropic.ChatAnthropic
    - 'google': uses langchain_google_genai.ChatGoogleGenerativeAI
    - 'nvidia' / 'nim': uses langchain_nvidia_ai_endpoints.ChatNVIDIA
    - 'fake' (default for tests): uses FakeChatModel

    Falls back to 'fake' if provider is unknown or import fails.
    """
    if _test_fake_llm is not None:
        return _test_fake_llm

    provider = settings.llm_provider.lower()
    logger.warning("Using LLM provider: %s, model: %s, temperature: %s", settings.llm_provider, settings.llm_model, temperature if temperature is not None else settings.llm_temperature)
    model = settings.llm_model
    temp = temperature if temperature is not None else settings.llm_temperature

    if provider == "openai":
        try:
            from langchain_openai import ChatOpenAI

            return ChatOpenAI(
                model=model,
                temperature=temp,
                api_key=settings.llm_api_key or None,  # type: ignore[arg-type]
                max_tokens=settings.llm_max_tokens,
            )
        except ImportError:
            logger.warning("langchain_openai not installed, falling back to FakeListChatModel")
    elif provider == "anthropic":
        try:
            from langchain_anthropic import ChatAnthropic

            return ChatAnthropic(
                model=model,
                temperature=temp,
                api_key=settings.llm_api_key or None,  # type: ignore[arg-type]
                max_tokens=settings.llm_max_tokens,
            )
        except ImportError:
            logger.warning("langchain_anthropic not installed, falling back to FakeListChatModel")
    elif provider in ("google", "gemini", "google_genai", "google-genai"):
        try:
            from langchain_google_genai import ChatGoogleGenerativeAI

            return ChatGoogleGenerativeAI(
                model=model,
                temperature=temp,
                google_api_key=settings.llm_api_key or None,  # type: ignore[arg-type]
                max_output_tokens=settings.llm_max_tokens,
                max_retries=1,
            )
        except ImportError:
            logger.warning("langchain_google_genai not installed, falling back to FakeListChatModel")
    elif provider in ("nvidia", "nim"):
        try:
            from langchain_nvidia_ai_endpoints import ChatNVIDIA

            kwargs: dict[str, Any] = {
                "model": model,
                "temperature": temp,
                "api_key": settings.llm_api_key or None,  # nvapi-... key
                "max_tokens": settings.llm_max_tokens,
            }
            # Optional: self-hosted NIM or a custom endpoint
            base_url = getattr(settings, "llm_base_url", None)
            if base_url:
                kwargs["base_url"] = base_url

            return ChatNVIDIA(**kwargs)
        except ImportError:
            logger.warning("langchain_nvidia_ai_endpoints not installed, falling back to FakeListChatModel")

    # Fallback: fake LLM for tests
    try:
        from langchain_core.language_models.fake_chat_models import FakeListChatModel

        return FakeListChatModel(responses=["I am a fake LLM response for testing."])
    except ImportError:
        from langchain_core.language_models.fake import FakeListChatModel  # type: ignore[no-redef]

        return FakeListChatModel(responses=["I am a fake LLM response for testing."])
