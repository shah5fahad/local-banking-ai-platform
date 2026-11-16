"""Unit tests for Document Knowledge Base UI and AIClient document methods (T6.4)."""
from __future__ import annotations

import httpx
import pytest
from streamlit.testing.v1 import AppTest

from clients.ai_client import AIClient
from components.document_manager import format_bytes


class TestAIClientDocumentMethods:
    def test_upload_document(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured_data = {}
        captured_headers = {}

        def mock_post(self, url, **kwargs):
            nonlocal captured_data, captured_headers
            captured_data = kwargs.get("data", {})
            captured_headers = kwargs.get("headers", {})
            return httpx.Response(
                202,
                json={
                    "id": "doc-uuid-1",
                    "name": "Master Circular",
                    "category": "REGULATORY",
                    "version": "1.0",
                    "status": "UPLOADED",
                    "uploaded_at": "2026-11-11T12:00:00Z",
                },
            )

        monkeypatch.setattr(httpx.Client, "post", mock_post)
        client = AIClient("http://ai-service")
        resp = client.upload_document(
            file_bytes=b"dummy content",
            filename="circular.pdf",
            name="Master Circular",
            category="REGULATORY",
            version="1.0",
            access_token="admin-token",
            doc_group_id="group-abc",
        )

        assert resp["id"] == "doc-uuid-1"
        assert resp["status"] == "UPLOADED"
        assert captured_data["name"] == "Master Circular"
        assert captured_data["category"] == "REGULATORY"
        assert captured_data["version"] == "1.0"
        assert captured_data["doc_group_id"] == "group-abc"
        assert captured_headers.get("Authorization") == "Bearer admin-token"

    def test_list_documents(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured_params = {}

        def mock_get(self, url, **kwargs):
            nonlocal captured_params
            captured_params = kwargs.get("params", {})
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "doc-1",
                            "name": "KYC Norms",
                            "category": "REGULATORY",
                            "version": "2.0",
                            "doc_group_id": "grp-1",
                            "status": "INDEXED",
                            "active": True,
                            "size_bytes": 102400,
                            "uploaded_at": "2026-11-10T10:00:00Z",
                            "uploaded_by": "admin-1",
                        }
                    ],
                    "total": 1,
                    "page": 1,
                    "page_size": 50,
                },
            )

        monkeypatch.setattr(httpx.Client, "get", mock_get)
        client = AIClient("http://ai-service")
        resp = client.list_documents(
            access_token="admin-token",
            category="REGULATORY",
            active=True,
            page=1,
            page_size=50,
        )

        assert resp["total"] == 1
        assert len(resp["items"]) == 1
        assert resp["items"][0]["name"] == "KYC Norms"
        assert captured_params["category"] == "REGULATORY"
        assert captured_params["active"] is True

    def test_get_document(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_get(self, url, **kwargs):
            return httpx.Response(
                200,
                json={
                    "id": "doc-1",
                    "name": "KYC Norms",
                    "category": "REGULATORY",
                    "version": "2.0",
                    "doc_group_id": "grp-1",
                    "status": "INDEXED",
                    "active": True,
                    "sha256": "abc123hash",
                    "mime": "application/pdf",
                    "size_bytes": 102400,
                    "uploaded_by": "admin-1",
                    "uploaded_at": "2026-11-10T10:00:00Z",
                    "error": None,
                    "chunks": [
                        {"id": "c-1", "chunk_index": 0, "page": 1, "section": "1.1", "vector_id": "vec-1", "token_count": 150}
                    ],
                },
            )

        monkeypatch.setattr(httpx.Client, "get", mock_get)
        client = AIClient("http://ai-service")
        doc = client.get_document("doc-1", "admin-token")
        assert doc["id"] == "doc-1"
        assert len(doc["chunks"]) == 1
        assert doc["chunks"][0]["page"] == 1

    def test_activate_document(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_post(self, url, **kwargs):
            return httpx.Response(
                200,
                json={
                    "id": "doc-1",
                    "name": "KYC Norms",
                    "category": "REGULATORY",
                    "version": "2.0",
                    "doc_group_id": "grp-1",
                    "status": "INDEXED",
                    "active": True,
                    "uploaded_at": "2026-11-10T10:00:00Z",
                    "chunks": [],
                },
            )

        monkeypatch.setattr(httpx.Client, "post", mock_post)
        client = AIClient("http://ai-service")
        res = client.activate_document("doc-1", "admin-token")
        assert res["active"] is True

    def test_deactivate_document(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_post(self, url, **kwargs):
            return httpx.Response(
                200,
                json={
                    "id": "doc-1",
                    "name": "KYC Norms",
                    "category": "REGULATORY",
                    "version": "2.0",
                    "doc_group_id": "grp-1",
                    "status": "INDEXED",
                    "active": False,
                    "uploaded_at": "2026-11-10T10:00:00Z",
                    "chunks": [],
                },
            )

        monkeypatch.setattr(httpx.Client, "post", mock_post)
        client = AIClient("http://ai-service")
        res = client.deactivate_document("doc-1", "admin-token")
        assert res["active"] is False

    def test_reprocess_document(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_post(self, url, **kwargs):
            return httpx.Response(
                200,
                json={
                    "document_id": "doc-1",
                    "status": "PROCESSING",
                    "message": "Document re-ingestion started",
                },
            )

        monkeypatch.setattr(httpx.Client, "post", mock_post)
        client = AIClient("http://ai-service")
        res = client.reprocess_document("doc-1", "admin-token")
        assert res["status"] == "PROCESSING"

    def test_delete_document(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_delete(self, url, **kwargs):
            return httpx.Response(204)

        monkeypatch.setattr(httpx.Client, "delete", mock_delete)
        client = AIClient("http://ai-service")
        assert client.delete_document("doc-1", "admin-token") is True

    def test_get_document_versions(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_get(self, url, **kwargs):
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "doc-v1",
                        "name": "KYC Norms v1",
                        "category": "REGULATORY",
                        "version": "1.0",
                        "doc_group_id": "grp-1",
                        "status": "INDEXED",
                        "active": False,
                        "uploaded_at": "2026-01-01T10:00:00Z",
                    },
                    {
                        "id": "doc-v2",
                        "name": "KYC Norms v2",
                        "category": "REGULATORY",
                        "version": "2.0",
                        "doc_group_id": "grp-1",
                        "status": "INDEXED",
                        "active": True,
                        "uploaded_at": "2026-11-10T10:00:00Z",
                    },
                ],
            )

        monkeypatch.setattr(httpx.Client, "get", mock_get)
        client = AIClient("http://ai-service")
        vers = client.get_document_versions("doc-v2", "admin-token")
        assert len(vers) == 2
        assert vers[0]["version"] == "1.0"
        assert vers[1]["version"] == "2.0"


class TestDocumentManagerHelpers:
    def test_format_bytes(self) -> None:
        assert format_bytes(None) == "0 B"
        assert format_bytes(0) == "0 B"
        assert "500.0 B" in format_bytes(500)
        assert "1.0 KB" in format_bytes(1024)
        assert "1.0 MB" in format_bytes(1024 * 1024)
        assert "1.5 MB" in format_bytes(int(1.5 * 1024 * 1024))
        assert "2.0 GB" in format_bytes(2 * 1024 * 1024 * 1024)


class TestDocumentsPageAppTest:
    def test_documents_page_blocks_customer_role(self) -> None:
        """Route guard must block non-admin / non-auditor roles."""
        at = AppTest.from_file("../pages/3_Documents.py", default_timeout=10)
        at.session_state["authenticated"] = True
        at.session_state["user"] = {
            "id": "cust-1",
            "full_name": "Alice Customer",
            "email": "alice@bank.local",
            "roles": ["CUSTOMER"],
        }
        at.session_state["roles"] = ["CUSTOMER"]
        at.session_state["access_token"] = "cust-token"

        at.run()
        # Should have stopped with error
        assert any("Access Denied" in e.value for e in at.error)

    def test_documents_page_renders_for_admin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Admin user can view documents, metrics, tabs, and upload form."""
        def mock_get(self, url, **kwargs):
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "doc-99",
                            "name": "RBI Digital Payment Security Guidelines",
                            "category": "REGULATORY",
                            "version": "1.0",
                            "doc_group_id": "group-rbi-1",
                            "status": "INDEXED",
                            "active": True,
                            "size_bytes": 524288,
                            "uploaded_at": "2026-11-11T10:00:00Z",
                            "uploaded_by": "admin-super",
                        }
                    ],
                    "total": 1,
                    "page": 1,
                    "page_size": 100,
                },
            )

        monkeypatch.setattr(httpx.Client, "get", mock_get)

        at = AppTest.from_file("../pages/3_Documents.py", default_timeout=10)
        at.session_state["authenticated"] = True
        at.session_state["user"] = {
            "id": "admin-1",
            "full_name": "Admin Officer",
            "email": "admin@bank.local",
            "roles": ["ADMIN"],
        }
        at.session_state["roles"] = ["ADMIN"]
        at.session_state["access_token"] = "admin-token"

        at.run()
        assert not at.exception
        # Check header
        assert any("Regulatory Documents" in t.value for t in at.title)
        # Check tabs exist (Document Library & Upload Document)
        assert len(at.tabs) >= 2
        # Check metrics displayed
        assert any(m.label == "Total Documents" for m in at.metric)
        assert any(m.label == "Active in RAG" for m in at.metric)
        # Check document title rendered
        assert any("RBI Digital Payment" in md.value for md in at.markdown)

    def test_documents_page_renders_for_auditor_in_readonly_mode(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Auditor user is allowed access but notified of read-only mode."""
        def mock_get(self, url, **kwargs):
            return httpx.Response(
                200,
                json={
                    "items": [],
                    "total": 0,
                    "page": 1,
                    "page_size": 100,
                },
            )

        monkeypatch.setattr(httpx.Client, "get", mock_get)

        at = AppTest.from_file("../pages/3_Documents.py", default_timeout=10)
        at.session_state["authenticated"] = True
        at.session_state["user"] = {
            "id": "auditor-1",
            "full_name": "Auditor Staff",
            "email": "auditor@bank.local",
            "roles": ["AUDITOR"],
        }
        at.session_state["roles"] = ["AUDITOR"]
        at.session_state["access_token"] = "auditor-token"

        at.run()
        assert not at.exception
        # Info banner for auditor mode
        assert any("Auditor Mode Enabled" in info.value for info in at.info)
