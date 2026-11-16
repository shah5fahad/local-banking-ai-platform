"""Vector store factory.

VECTOR_STORE_PROVIDER: chroma (default), faiss, memory.
Collection name encodes embedding model to prevent cross-model contamination.
"""
from __future__ import annotations

import logging
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import VectorStore

from app.core.config import AISettings

logger = logging.getLogger(__name__)


def collection_name(settings: AISettings) -> str:
    """Return the vector store collection name encoding the embedding model."""
    model_id = settings.embedding_model.replace("/", "_").replace("-", "_").lower()
    return f"policy_docs__{model_id}"


def create_vectorstore(
    embeddings: Embeddings, settings: AISettings, collection: str | None = None
) -> VectorStore:
    """Create a VectorStore based on VECTOR_STORE_PROVIDER setting."""
    coll = collection or collection_name(settings)
    provider = settings.vector_store_provider.lower()

    if provider == "chroma":
        try:
            from langchain_chroma import Chroma

            return Chroma(
                collection_name=coll,
                embedding_function=embeddings,
                persist_directory=str(settings.vector_store_path),
            )
        except ImportError:
            logger.warning("langchain_chroma not installed, falling back to InMemoryVectorStore")
    elif provider == "faiss":
        try:
            from langchain_community.vectorstores import FAISS

            # FAISS doesn't have persistent named collections; use in-memory
            return FAISS.from_texts(["init"], embeddings)
        except ImportError:
            logger.warning("langchain_community not installed, falling back to InMemoryVectorStore")

    # Fallback: in-memory
    from langchain_core.vectorstores import InMemoryVectorStore

    return InMemoryVectorStore(embeddings)


# Module-level singleton (lazy)
_vectorstore: VectorStore | None = None


def get_vectorstore(settings: AISettings) -> VectorStore:
    """Return singleton vector store instance."""
    global _vectorstore
    if _vectorstore is None:
        from app.integrations.embeddings_factory import create_embeddings

        embeddings = create_embeddings(settings)
        _vectorstore = create_vectorstore(embeddings, settings)
    return _vectorstore
