"""Unit tests for the Policy RAG node (T4.3)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from langchain_core.documents import Document as LCDocument
from langchain_core.messages import AIMessage

from app.agents.nodes.policy_rag import policy_rag_node
from app.agents.state import GraphState


def test_policy_rag_node_success_with_citations() -> None:
    """Test policy_rag_node when relevant chunks are found."""
    state: GraphState = {
        "user_message": "What is the bank's loan policy?",
        "messages": [],
    }

    mock_doc = LCDocument(
        page_content="Personal loan interest rate is 10.5% with tenure up to 60 months.",
        metadata={
            "doc_name": "Retail Loan Policy",
            "version": "1.0",
            "page": 4,
            "section": "Interest Rates",
            "active": True,
        },
    )

    mock_vectorstore = MagicMock()
    mock_vectorstore.similarity_search_with_score.return_value = [(mock_doc, 0.85)]

    fake_llm = MagicMock()
    fake_llm.invoke.return_value = AIMessage(
        content="According to the policy [1], personal loans have an interest rate of 10.5%."
    )

    with (
        patch("app.agents.nodes.policy_rag.get_vectorstore", return_value=mock_vectorstore),
        patch("app.agents.nodes.policy_rag.create_llm", return_value=fake_llm),
    ):
        result = policy_rag_node(state)

    assert "citations" in result
    assert len(result["citations"]) == 1
    citation = result["citations"][0]
    assert citation["doc_name"] == "Retail Loan Policy"
    assert citation["version"] == "1.0"
    assert citation["page"] == 4
    assert citation["section"] == "Interest Rates"
    assert "[1]" in result["response"]


def test_policy_rag_node_abstains_when_below_threshold() -> None:
    """Test policy_rag_node abstaining when all chunk scores are below rag_min_score."""
    state: GraphState = {
        "user_message": "What is the bank's spaceship loan policy?",
        "messages": [],
    }

    mock_doc = LCDocument(
        page_content="Unrelated text",
        metadata={"doc_name": "General", "active": True},
    )

    # Score 0.1 is below default rag_min_score (0.3)
    mock_vectorstore = MagicMock()
    mock_vectorstore.similarity_search_with_score.return_value = [(mock_doc, 0.1)]

    with patch("app.agents.nodes.policy_rag.get_vectorstore", return_value=mock_vectorstore):
        result = policy_rag_node(state)

    assert "couldn't find" in result["response"].lower()
    assert result["citations"] == []


def test_policy_rag_node_ignores_inactive_documents() -> None:
    """Test that inactive policy documents are filtered out from RAG generation."""
    state: GraphState = {
        "user_message": "What is the bank's policy?",
        "messages": [],
    }

    inactive_doc = LCDocument(
        page_content="Old outdated policy text",
        metadata={"doc_name": "Old Policy", "active": False},
    )

    mock_vectorstore = MagicMock()
    mock_vectorstore.similarity_search_with_score.return_value = [(inactive_doc, 0.9)]

    with patch("app.agents.nodes.policy_rag.get_vectorstore", return_value=mock_vectorstore):
        result = policy_rag_node(state)

    assert "couldn't find" in result["response"].lower()
    assert result["citations"] == []
