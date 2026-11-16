"""AI Chat Service API client for SSE streaming, conversation history, and approval management."""
from __future__ import annotations

import json
import os
from collections.abc import Generator
from typing import Any

import httpx

DEFAULT_AI_API_URL = os.environ.get("AI_API_URL", "http://localhost:8002/api/v1")
DEFAULT_AI_TIMEOUT = float(os.environ.get("AI_CLIENT_TIMEOUT", "120.0"))


class AIAPIError(Exception):
    """Exception raised for API errors from the AI Chat service."""

    def __init__(self, message: str, status_code: int = 400, error_code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_code = error_code


class AIClient:
    """Client for AI Service API v1 endpoints supporting streaming SSE and HITL workflows."""

    def __init__(self, base_url: str | None = None, timeout: float = DEFAULT_AI_TIMEOUT) -> None:
        self.base_url = (base_url or DEFAULT_AI_API_URL).rstrip("/")
        self.timeout = timeout

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """Parse JSON response or raise AIAPIError."""
        try:
            data = response.json()
        except Exception:
            data = {"message": response.text or f"HTTP {response.status_code}"}

        if response.is_success:
            return data

        err_msg = data.get("message") or data.get("detail") or f"Request failed with status {response.status_code}"
        err_code = data.get("error_code") or data.get("error")
        raise AIAPIError(str(err_msg), status_code=response.status_code, error_code=err_code)

    def stream_message(
        self,
        message: str,
        conversation_id: str | None,
        access_token: str,
    ) -> Generator[dict[str, Any], None, None]:
        """Send chat message and stream Server-Sent Events (SSE).
        
        Yields parsed events: {"event": str, "data": dict | str}
        Events: status, tool, token, citations, approval_required, done, error.
        """
        url = f"{self.base_url}/chat/messages"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "text/event-stream",
        }
        payload = {
            "message": message,
            "conversation_id": conversation_id,
        }

        with httpx.Client(timeout=self.timeout) as client:
            with client.stream("POST", url, json=payload, headers=headers) as response:
                if not response.is_success:
                    response.read()
                    self._handle_response(response)

                current_event = "message"
                current_data_lines: list[str] = []

                for line in response.iter_lines():
                    line = line.strip()
                    if not line:
                        # Empty line signals dispatch of the event
                        if current_data_lines:
                            data_str = "\n".join(current_data_lines)
                            try:
                                parsed_data = json.loads(data_str)
                            except Exception:
                                parsed_data = data_str

                            yield {
                                "event": current_event,
                                "data": parsed_data,
                            }
                            current_data_lines = []
                            current_event = "message"
                        continue

                    if line.startswith("event:"):
                        current_event = line.split(":", 1)[1].strip()
                    elif line.startswith("data:"):
                        current_data_lines.append(line.split(":", 1)[1].strip())

                # Flush any trailing event
                if current_data_lines:
                    data_str = "\n".join(current_data_lines)
                    try:
                        parsed_data = json.loads(data_str)
                    except Exception:
                        parsed_data = data_str
                    yield {
                        "event": current_event,
                        "data": parsed_data,
                    }

    def get_active_approval(
        self,
        conversation_id: str,
        access_token: str,
        workflow_type: str | None = None,
    ) -> dict[str, Any] | None:
        """Fetch active pending approval for conversation, if any."""
        url = f"{self.base_url}/chat/approvals/active"
        headers = {"Authorization": f"Bearer {access_token}"}
        params: dict[str, str] = {"conversation_id": conversation_id}
        if workflow_type:
            params["workflow_type"] = workflow_type

        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url, headers=headers, params=params)
            if resp.status_code == 404 or not resp.content:
                return None
            data = self._handle_response(resp)
            return data if data else None

    def get_approval(self, approval_id: str, access_token: str) -> dict[str, Any]:
        """Fetch detailed state of a pending approval."""
        url = f"{self.base_url}/chat/approvals/{approval_id}"
        headers = {"Authorization": f"Bearer {access_token}"}
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url, headers=headers)
            return self._handle_response(resp)

    def decide_approval(
        self,
        approval_id: str,
        decision: str,
        access_token: str,
    ) -> dict[str, Any]:
        """Submit human decision (CONFIRM / REJECT) for a pending approval."""
        url = f"{self.base_url}/chat/approvals/{approval_id}/decision"
        headers = {"Authorization": f"Bearer {access_token}"}
        payload = {"decision": decision.upper()}
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(url, json=payload, headers=headers)
            return self._handle_response(resp)

    def resume_approval(
        self,
        approval_id: str,
        authorization_id: str,
        access_token: str,
        summary_hash: str | None = None,
    ) -> dict[str, Any]:
        """Resume graph execution after direct customer PIN authentication."""
        url = f"{self.base_url}/chat/approvals/{approval_id}/resume"
        headers = {"Authorization": f"Bearer {access_token}"}
        payload: dict[str, Any] = {"authorization_id": authorization_id}
        if summary_hash:
            payload["summary_hash"] = summary_hash

        with httpx.Client(timeout=20.0) as client:
            resp = client.post(url, json=payload, headers=headers)
            return self._handle_response(resp)

    def get_conversation(self, conversation_id: str, access_token: str) -> dict[str, Any]:
        """Fetch conversation details and historical messages."""
        url = f"{self.base_url}/conversations/{conversation_id}"
        headers = {"Authorization": f"Bearer {access_token}"}
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url, headers=headers)
            return self._handle_response(resp)

    def list_conversations(
        self,
        access_token: str,
        query: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> list[dict[str, Any]]:
        """List user's active conversations with optional title query search."""
        url = f"{self.base_url}/conversations"
        headers = {"Authorization": f"Bearer {access_token}"}
        params: dict[str, Any] = {"page": page, "page_size": page_size}
        if query:
            params["q"] = query

        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url, headers=headers, params=params)
            data = self._handle_response(resp)
            if isinstance(data, list):
                return data
            return data.get("items") or data.get("conversations", []) if isinstance(data, dict) else []

    def create_conversation(self, title: str, access_token: str) -> dict[str, Any]:
        """Create a new conversation session."""
        url = f"{self.base_url}/conversations"
        headers = {"Authorization": f"Bearer {access_token}"}
        payload = {"title": title.strip()}
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(url, json=payload, headers=headers)
            return self._handle_response(resp)

    def rename_conversation(
        self,
        conversation_id: str,
        new_title: str,
        access_token: str,
    ) -> dict[str, Any]:
        """Rename an existing conversation title."""
        url = f"{self.base_url}/conversations/{conversation_id}"
        headers = {"Authorization": f"Bearer {access_token}"}
        payload = {"title": new_title.strip()}
        with httpx.Client(timeout=10.0) as client:
            resp = client.patch(url, json=payload, headers=headers)
            return self._handle_response(resp)

    def delete_conversation(self, conversation_id: str, access_token: str) -> bool:
        """Soft delete a conversation and its messages."""
        url = f"{self.base_url}/conversations/{conversation_id}"
        headers = {"Authorization": f"Bearer {access_token}"}
        with httpx.Client(timeout=10.0) as client:
            resp = client.delete(url, headers=headers)
            if resp.status_code in (200, 204):
                return True
            self._handle_response(resp)
            return True

    def upload_document(
        self,
        file_bytes: bytes,
        filename: str,
        name: str,
        category: str,
        version: str,
        access_token: str,
        doc_group_id: str | None = None,
    ) -> dict[str, Any]:
        """Upload raw policy/knowledge document and queue asynchronous ingestion."""
        url = f"{self.base_url}/documents"
        headers = {"Authorization": f"Bearer {access_token}"}
        data: dict[str, Any] = {
            "name": name,
            "category": category,
            "version": version,
        }
        if doc_group_id:
            data["doc_group_id"] = doc_group_id

        files = {"file": (filename, file_bytes, "application/octet-stream")}
        with httpx.Client(timeout=30.0) as client:
            resp = client.post(url, data=data, files=files, headers=headers)
            return self._handle_response(resp)

    def list_documents(
        self,
        access_token: str,
        category: str | None = None,
        active: bool | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        """List documents with optional category and active status filtering."""
        url = f"{self.base_url}/documents"
        headers = {"Authorization": f"Bearer {access_token}"}
        params: dict[str, Any] = {"page": page, "page_size": page_size}
        if category:
            params["category"] = category
        if active is not None:
            params["active"] = active

        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url, headers=headers, params=params)
            return self._handle_response(resp)

    def get_document(self, document_id: str, access_token: str) -> dict[str, Any]:
        """Retrieve full details of a document including indexed chunk metadata."""
        url = f"{self.base_url}/documents/{document_id}"
        headers = {"Authorization": f"Bearer {access_token}"}
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url, headers=headers)
            return self._handle_response(resp)

    def activate_document(self, document_id: str, access_token: str) -> dict[str, Any]:
        """Explicitly activate document and deactivate previous versions."""
        url = f"{self.base_url}/documents/{document_id}/activate"
        headers = {"Authorization": f"Bearer {access_token}"}
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(url, headers=headers)
            return self._handle_response(resp)

    def deactivate_document(self, document_id: str, access_token: str) -> dict[str, Any]:
        """Explicitly deactivate document so it is excluded from RAG retrieval."""
        url = f"{self.base_url}/documents/{document_id}/deactivate"
        headers = {"Authorization": f"Bearer {access_token}"}
        with httpx.Client(timeout=10.0) as client:
            resp = client.post(url, headers=headers)
            return self._handle_response(resp)

    def reprocess_document(self, document_id: str, access_token: str) -> dict[str, Any]:
        """Delete existing indexed vectors and re-run the ingestion pipeline."""
        url = f"{self.base_url}/documents/{document_id}/reprocess"
        headers = {"Authorization": f"Bearer {access_token}"}
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(url, headers=headers)
            return self._handle_response(resp)

    def delete_document(self, document_id: str, access_token: str) -> bool:
        """Delete document from vector store, disk storage, and database."""
        url = f"{self.base_url}/documents/{document_id}"
        headers = {"Authorization": f"Bearer {access_token}"}
        with httpx.Client(timeout=15.0) as client:
            resp = client.delete(url, headers=headers)
            if resp.status_code in (200, 204):
                return True
            self._handle_response(resp)
            return True

    def get_document_versions(self, document_id: str, access_token: str) -> list[dict[str, Any]]:
        """Retrieve all versions belonging to the same document group."""
        url = f"{self.base_url}/documents/{document_id}/versions"
        headers = {"Authorization": f"Bearer {access_token}"}
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url, headers=headers)
            data = self._handle_response(resp)
            return data if isinstance(data, list) else data.get("items", [])

    # ------------------------------------------------------------------
    # AI Admin APIs
    # ------------------------------------------------------------------
    def get_ai_stats(self, access_token: str) -> dict[str, Any]:
        """Fetch aggregate AI assistant statistics."""
        url = f"{self.base_url}/admin/ai-stats"
        headers = {"Authorization": f"Bearer {access_token}"}
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url, headers=headers)
            return self._handle_response(resp)

    def list_admin_conversations(
        self,
        access_token: str,
        page: int = 1,
        page_size: int = 50,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch conversations across all users for compliance/audit monitoring."""
        url = f"{self.base_url}/admin/conversations"
        headers = {"Authorization": f"Bearer {access_token}"}
        params: dict[str, Any] = {"page": page, "page_size": page_size}
        if status:
            params["status"] = status
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url, headers=headers, params=params)
            data = self._handle_response(resp)
            return data if isinstance(data, list) else data.get("items", [])

    def get_admin_conversation_messages(
        self, conversation_id: str, access_token: str
    ) -> list[dict[str, Any]]:
        """Fetch turn-by-turn masked messages for a specific conversation."""
        url = f"{self.base_url}/admin/conversations/{conversation_id}/messages"
        headers = {"Authorization": f"Bearer {access_token}"}
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url, headers=headers)
            data = self._handle_response(resp)
            return data if isinstance(data, list) else data.get("items", [])

    def list_agent_executions(
        self,
        access_token: str,
        conversation_id: str | None = None,
        node: str | None = None,
        status: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> list[dict[str, Any]]:
        """Fetch step traces of LangGraph node and tool executions."""
        url = f"{self.base_url}/admin/agent-executions"
        headers = {"Authorization": f"Bearer {access_token}"}
        params: dict[str, Any] = {"page": page, "page_size": page_size}
        if conversation_id:
            params["conversation_id"] = conversation_id
        if node:
            params["node"] = node
        if status:
            params["status"] = status
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url, headers=headers, params=params)
            data = self._handle_response(resp)
            return data if isinstance(data, list) else data.get("items", [])

    def get_ai_config(self, access_token: str) -> dict[str, Any]:
        """Fetch active non-secret AI runtime configuration."""
        url = f"{self.base_url}/admin/ai-config"
        headers = {"Authorization": f"Bearer {access_token}"}
        with httpx.Client(timeout=10.0) as client:
            resp = client.get(url, headers=headers)
            return self._handle_response(resp)

    def update_ai_config(
        self, payload: dict[str, Any], access_token: str
    ) -> dict[str, Any]:
        """Update non-secret AI runtime settings (model, temperature, top-k, min score)."""
        url = f"{self.base_url}/admin/ai-config"
        headers = {"Authorization": f"Bearer {access_token}"}
        with httpx.Client(timeout=10.0) as client:
            resp = client.patch(url, json=payload, headers=headers)
            return self._handle_response(resp)
