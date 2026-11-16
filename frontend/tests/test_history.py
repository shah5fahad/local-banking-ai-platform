"""Unit tests for Chat history (list, search, rename, delete) - T6.3."""
from __future__ import annotations

import httpx
import pytest
from streamlit.testing.v1 import AppTest

from clients.ai_client import AIClient
from components.history_view import format_iso_timestamp


class TestAIClientConversationMethods:
    def test_list_conversations_with_query(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured_params = {}

        def mock_get(self, url, **kwargs):
            nonlocal captured_params
            captured_params = kwargs.get("params", {})
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "c-1",
                            "title": "Transfer to Bob",
                            "status": "ACTIVE",
                            "created_at": "2026-11-10T10:00:00Z",
                            "message_count": 4,
                        }
                    ],
                    "total": 1,
                    "page": 1,
                    "page_size": 20,
                },
            )

        monkeypatch.setattr(httpx.Client, "get", mock_get)
        client = AIClient("http://ai-service")
        items = client.list_conversations("mock-token", query="Bob")

        assert len(items) == 1
        assert items[0]["title"] == "Transfer to Bob"
        assert captured_params.get("q") == "Bob"

    def test_create_conversation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_post(self, url, **kwargs):
            return httpx.Response(
                201,
                json={"id": "c-new", "title": "New Chat", "status": "ACTIVE"},
            )

        monkeypatch.setattr(httpx.Client, "post", mock_post)
        client = AIClient("http://ai-service")
        conv = client.create_conversation("New Chat", "mock-token")
        assert conv["id"] == "c-new"
        assert conv["title"] == "New Chat"

    def test_rename_conversation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_patch(self, url, **kwargs):
            payload = kwargs.get("json", {})
            return httpx.Response(
                200,
                json={"id": "c-1", "title": payload.get("title"), "status": "ACTIVE"},
            )

        monkeypatch.setattr(httpx.Client, "patch", mock_patch)
        client = AIClient("http://ai-service")
        conv = client.rename_conversation("c-1", "Updated Title", "mock-token")
        assert conv["title"] == "Updated Title"

    def test_delete_conversation(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_delete(self, url, **kwargs):
            return httpx.Response(204)

        monkeypatch.setattr(httpx.Client, "delete", mock_delete)
        client = AIClient("http://ai-service")
        assert client.delete_conversation("c-1", "mock-token") is True


class TestTimestampFormatting:
    def test_format_iso_timestamp_valid(self) -> None:
        formatted = format_iso_timestamp("2026-11-10T14:30:00Z")
        assert "Nov 10, 2026" in formatted
        assert "02:30 PM" in formatted or "2:30 PM" in formatted

    def test_format_iso_timestamp_none_or_empty(self) -> None:
        assert format_iso_timestamp(None) == ""
        assert format_iso_timestamp("") == ""


class TestHistoryPageAppTest:
    def test_history_page_authenticated_renders(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Ensure 2_History.py boots and displays search input and tabs."""
        # Mock conversations response
        def mock_get(self, url, **kwargs):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "conv-101",
                            "title": "Home Loan Inquiry",
                            "status": "ACTIVE",
                            "created_at": "2026-11-11T09:00:00Z",
                            "updated_at": "2026-11-11T09:15:00Z",
                            "message_count": 6,
                        }
                    ],
                    "total": 1,
                    "page": 1,
                    "page_size": 50,
                },
            )

        monkeypatch.setattr(httpx.Client, "get", mock_get)

        at = AppTest.from_file("../pages/2_History.py", default_timeout=10)
        at.session_state["authenticated"] = True
        at.session_state["user"] = {
            "id": "u-1",
            "full_name": "Charlie",
            "email": "charlie@bank.local",
            "roles": ["CUSTOMER"],
        }
        at.session_state["roles"] = ["CUSTOMER"]
        at.session_state["access_token"] = "valid-token"

        at.run()
        assert not at.exception
        # Check title and search
        assert any("History" in t.value for t in at.title)
        assert len(at.tabs) >= 2
        # Check subheader with conversation title
        subheaders = [s.value for s in at.subheader]
        assert any("Home Loan Inquiry" in sh for sh in subheaders)
        # Check buttons exist (Open, Refresh, etc.)
        button_labels = [b.label for b in at.button]
        assert any("Open" in lbl for lbl in button_labels)
        assert any("Refresh" in lbl for lbl in button_labels)
