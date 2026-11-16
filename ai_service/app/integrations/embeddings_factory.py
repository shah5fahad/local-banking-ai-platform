"""Embeddings provider factory.

Providers: openai, huggingface, google, fake.
EMBEDDING_PROVIDER, EMBEDDING_MODEL read from AISettings.
"""
from __future__ import annotations

import logging
from langchain_core.embeddings import Embeddings

from app.core.config import AISettings

logger = logging.getLogger(__name__)


def create_embeddings(settings: AISettings) -> Embeddings:
    """Create Embeddings based on EMBEDDING_PROVIDER setting."""
    provider = settings.embedding_provider.lower()
    model = settings.embedding_model

    if provider == "openai":
        try:
            from langchain_openai import OpenAIEmbeddings

            return OpenAIEmbeddings(model=model, api_key=settings.llm_api_key or None)  # type: ignore[arg-type]
        except ImportError:
            logger.warning("langchain_openai not installed, falling back to FakeEmbeddings")
    elif provider == "huggingface":
        try:
            from langchain_huggingface import HuggingFaceEmbeddings

            return HuggingFaceEmbeddings(model_name=model)
        except ImportError:
            logger.warning("langchain_huggingface not installed, falling back to FakeEmbeddings")
    elif provider == "google":
        try:
            from langchain_google_genai import GoogleGenerativeAIEmbeddings

            return GoogleGenerativeAIEmbeddings(
                model=model, google_api_key=settings.llm_api_key or None  # type: ignore[arg-type]
            )
        except ImportError:
            logger.warning("langchain_google_genai not installed, falling back to FakeEmbeddings")

    # Fallback: fake embeddings returning fixed-size deterministic vectors
    class _DeterministicFakeEmbeddings(Embeddings):
        def __init__(self, size: int = 1536) -> None:
            self.size = size

        def embed_documents(self, texts: list[str]) -> list[list[float]]:
            return [self.embed_query(t) for t in texts]

        def embed_query(self, text: str) -> list[float]:
            import hashlib
            h = hashlib.sha256(text.encode("utf-8")).digest()
            vals: list[float] = []
            while len(vals) < self.size:
                vals.extend([b / 255.0 for b in h])
            return vals[: self.size]

    return _DeterministicFakeEmbeddings(size=1536)
