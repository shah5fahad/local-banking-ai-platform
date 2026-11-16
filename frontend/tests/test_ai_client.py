"""Unit tests for AIClient (SSE streaming and approval endpoints)."""
from __future__ import annotations

import httpx
import pytest

from clients.ai_client import AIAPIError, AIClient


class TestAIClientStreaming:
    def test_stream_message_parses_sse_events(self, monkeypatch: pytest.MonkeyPatch) -> None:
        sse_lines = [
            "event: status\n",
            'data: {"status": "classified", "intent": "TRANSFER", "node": "supervisor"}\n',
            "\n",
            "event: tool\n",
            'data: {"tool": "get_accounts", "success": true}\n',
            "\n",
            "event: citations\n",
            'data: {"citations": [{"title": "RBI Transfer Guidelines", "section": "2.1"}]}\n',
            "\n",
            "event: token\n",
            'data: {"token": "Please review the "}\n',
            "\n",
            "event: token\n",
            'data: {"token": "transfer details."}\n',
            "\n",
            "event: approval_required\n",
            'data: {"approval_id": "app-123", "workflow": "TRANSFER", "summary": {"amount": "₹5,000"}}\n',
            "\n",
            "event: done\n",
            'data: {"conversation_id": "conv-456", "message_id": "msg-789"}\n',
            "\n",
        ]

        class MockStreamResponse:
            is_success = True
            status_code = 200

            def iter_lines(self):
                for line in sse_lines:
                    yield line

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

        class MockClient:
            def __init__(self, **kwargs):
                pass

            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def stream(self, method, url, **kwargs):
                return MockStreamResponse()

        monkeypatch.setattr(httpx, "Client", MockClient)

        client = AIClient("http://ai-service")
        events = list(client.stream_message("Transfer ₹5000", "conv-456", "mock-token"))

        assert len(events) == 7
        assert events[0]["event"] == "status"
        assert events[0]["data"]["intent"] == "TRANSFER"

        assert events[1]["event"] == "tool"
        assert events[1]["data"]["tool"] == "get_accounts"

        assert events[2]["event"] == "citations"
        assert events[2]["data"]["citations"][0]["title"] == "RBI Transfer Guidelines"

        assert events[3]["event"] == "token"
        assert events[3]["data"]["token"] == "Please review the "

        assert events[4]["event"] == "token"
        assert events[4]["data"]["token"] == "transfer details."

        assert events[5]["event"] == "approval_required"
        assert events[5]["data"]["approval_id"] == "app-123"

        assert events[6]["event"] == "done"
        assert events[6]["data"]["conversation_id"] == "conv-456"


class TestAIClientApprovalMethods:
    def test_get_active_approval_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_get(self, url, **kwargs):
            return httpx.Response(
                200,
                json={
                    "approval_id": "app-1",
                    "workflow": "TRANSFER",
                    "status": "PENDING",
                    "summary": {"amount": "₹1,000"},
                },
            )

        monkeypatch.setattr(httpx.Client, "get", mock_get)
        client = AIClient("http://ai-service")
        appr = client.get_active_approval("conv-1", "tok")
        assert appr is not None
        assert appr["approval_id"] == "app-1"
        assert appr["workflow"] == "TRANSFER"

    def test_get_active_approval_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_get(self, url, **kwargs):
            return httpx.Response(404, json={"detail": "Not found"})

        monkeypatch.setattr(httpx.Client, "get", mock_get)
        client = AIClient("http://ai-service")
        appr = client.get_active_approval("conv-1", "tok")
        assert appr is None

    def test_decide_approval_confirm(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_post(self, url, **kwargs):
            return httpx.Response(
                200,
                json={"approval_id": "app-1", "decision": "CONFIRM", "status": "CONFIRMED"},
            )

        monkeypatch.setattr(httpx.Client, "post", mock_post)
        client = AIClient("http://ai-service")
        res = client.decide_approval("app-1", "CONFIRM", "tok")
        assert res["decision"] == "CONFIRM"

    def test_resume_approval_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_post(self, url, **kwargs):
            return httpx.Response(
                200,
                json={"approval_id": "app-1", "status": "EXECUTED", "reference": "TXN123"},
            )

        monkeypatch.setattr(httpx.Client, "post", mock_post)
        client = AIClient("http://ai-service")
        res = client.resume_approval("app-1", "auth-token-999", "tok", "hash-abc")
        assert res["status"] == "EXECUTED"
