"""Unit tests for External Research node and domain allow-listing (T4.4)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from langchain_core.messages import AIMessage

from app.agents.nodes.external_research import EXTERNAL_DISCLAIMER, external_research_node
from app.agents.state import GraphState
from app.integrations.search.provider import SearchResult, extract_domain, is_domain_allowed


def test_domain_allowlist_matching() -> None:
    allowed_csv = "rbi.org.in, bankofengland.co.uk, sec.gov"

    assert is_domain_allowed("rbi.org.in", allowed_csv) is True
    assert is_domain_allowed("www.rbi.org.in", allowed_csv) is True
    assert is_domain_allowed("reports.sec.gov", allowed_csv) is True

    # Disallowed domains
    assert is_domain_allowed("randomblog.com", allowed_csv) is False
    assert is_domain_allowed("fake-rbi.org.in.phishing.com", allowed_csv) is False


def test_domain_allowlist_empty_allows_all() -> None:
    assert is_domain_allowed("example.com", "") is True
    assert is_domain_allowed("example.com", "   ") is True


def test_extract_domain() -> None:
    assert extract_domain("https://www.rbi.org.in/scripts/BS_PressReleaseDisplay.aspx") == "www.rbi.org.in"
    assert extract_domain("http://localhost:8000/api") == "localhost"
    assert extract_domain("invalid-url") == ""


def test_external_research_node_with_results() -> None:
    state: GraphState = {
        "user_message": "What is the current RBI repo rate?",
        "messages": [],
    }

    mock_results = [
        SearchResult(
            title="RBI Monetary Policy",
            url="https://rbi.org.in/press/repo",
            snippet="The current policy repo rate is 6.50 percent.",
            domain="rbi.org.in",
        )
    ]

    fake_llm = MagicMock()
    fake_llm.invoke.return_value = AIMessage(
        content="According to the RBI [1], the repo rate is 6.50%."
    )

    from app.core.config import AISettings
    test_settings = AISettings(search_provider="serper", search_api_key="mock-key")

    with (
        patch("app.agents.nodes.external_research.get_settings", return_value=test_settings),
        patch("app.agents.nodes.external_research.search_web", return_value=mock_results),
        patch("app.agents.nodes.external_research.create_llm", return_value=fake_llm),
    ):
        result = external_research_node(state)

    assert "citations" in result
    assert len(result["citations"]) == 1
    assert result["citations"][0]["doc_name"] == "RBI Monetary Policy"
    assert result["citations"][0]["section"] == "https://rbi.org.in/press/repo"
    # Must append external disclaimer
    assert EXTERNAL_DISCLAIMER.strip() in result["response"]


def test_external_research_node_no_search_appends_disclaimer() -> None:
    state: GraphState = {
        "user_message": "What is compound interest?",
        "messages": [],
    }

    fake_llm = MagicMock()
    fake_llm.invoke.return_value = AIMessage(content="Compound interest is interest calculated on principal + accumulated interest.")

    with (
        patch("app.agents.nodes.external_research.search_web", return_value=[]),
        patch("app.agents.nodes.external_research.create_llm", return_value=fake_llm),
    ):
        result = external_research_node(state)

    assert EXTERNAL_DISCLAIMER.strip() in result["response"]
