"""Integrations package for AI service."""
from __future__ import annotations

from app.integrations.banking_client import BankingClient, BankingClientError
from app.integrations.embeddings_factory import create_embeddings
from app.integrations.llm_factory import create_llm
from app.integrations.vectorstore_factory import (
    collection_name,
    create_vectorstore,
    get_vectorstore,
)

__all__ = [
    "BankingClient",
    "BankingClientError",
    "collection_name",
    "create_embeddings",
    "create_llm",
    "create_vectorstore",
    "get_vectorstore",
]
