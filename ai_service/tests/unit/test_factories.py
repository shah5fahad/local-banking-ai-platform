"""Unit tests for LLMFactory, EmbeddingsFactory, and VectorStoreFactory."""
from __future__ import annotations

import pytest

from app.core.config import AISettings
from app.integrations.embeddings_factory import create_embeddings
from app.integrations.llm_factory import create_llm
from app.integrations.vectorstore_factory import (
    collection_name,
    create_vectorstore,
    get_vectorstore,
)


@pytest.fixture
def settings() -> AISettings:
    return AISettings(
        AI_DATABASE_URL="sqlite:///./test.db",
        AI_SECRET_KEY="test-secret-key-12345678901234567890",
        AI_BANKING_SERVICE_URL="http://banking:8000",
        LLM_PROVIDER="fake",
        EMBEDDING_PROVIDER="fake",
        EMBEDDING_MODEL="text-embedding-3-small",
        VECTOR_STORE_PROVIDER="memory",
    )


def test_create_llm_fake(settings: AISettings) -> None:
    llm = create_llm(settings)
    assert llm is not None
    # Test invoke
    res = llm.invoke("hello")
    assert res.content == "I am a fake LLM response for testing."


def test_create_llm_nvidia(settings: AISettings) -> None:
    settings.llm_provider = "nvidia"
    settings.llm_model = "meta/llama-3.1-70b-instruct"
    settings.llm_api_key = "nvapi-test"
    llm = create_llm(settings)
    from langchain_nvidia_ai_endpoints import ChatNVIDIA

    assert isinstance(llm, ChatNVIDIA)
    assert llm.model == "meta/llama-3.1-70b-instruct"


def test_create_llm_nim(settings: AISettings) -> None:
    settings.llm_provider = "nim"
    settings.llm_model = "meta/llama-3.1-8b-instruct"
    settings.llm_api_key = "nvapi-test"
    settings.llm_base_url = "http://localhost:8000/v1"
    llm = create_llm(settings)
    from langchain_nvidia_ai_endpoints import ChatNVIDIA

    assert isinstance(llm, ChatNVIDIA)
    assert llm.base_url == "http://localhost:8000/v1"


def test_create_embeddings_fake(settings: AISettings) -> None:
    embeddings = create_embeddings(settings)
    assert embeddings is not None
    vec = embeddings.embed_query("test query")
    assert len(vec) == 1536


def test_create_vectorstore_memory(settings: AISettings) -> None:
    embeddings = create_embeddings(settings)
    coll = collection_name(settings)
    assert "text_embedding_3_small" in coll

    store = create_vectorstore(embeddings, settings)
    assert store is not None
    store.add_texts(["Banking policies document sample"])
    results = store.similarity_search("policies", k=1)
    assert len(results) == 1
    assert "Banking policies" in results[0].page_content


def test_get_vectorstore_singleton(settings: AISettings) -> None:
    vs1 = get_vectorstore(settings)
    vs2 = get_vectorstore(settings)
    assert vs1 is vs2
