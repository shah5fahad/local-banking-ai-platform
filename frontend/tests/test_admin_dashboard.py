"""Unit tests for Admin Dashboard UI and admin client methods (T6.5)."""
from __future__ import annotations

import httpx
import pytest
from streamlit.testing.v1 import AppTest

from clients.ai_client import AIClient
from clients.banking_client import BankingClient
from components.admin_dashboard import format_currency_inr


class TestBankingClientAdmin:
    def test_get_admin_stats(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_get(self, url, **kwargs):
            return httpx.Response(
                200,
                json={
                    "total_users": 150,
                    "active_users": 142,
                    "total_accounts": 210,
                    "total_transactions": 3400,
                    "total_loans_submitted": 25,
                    "total_loan_amount_minor": 125000000,
                },
            )

        monkeypatch.setattr(httpx.Client, "get", mock_get)
        client = BankingClient("http://banking-service")
        stats = client.get_admin_stats("admin-token")
        assert stats["total_users"] == 150
        assert stats["total_loan_amount_minor"] == 125000000

    def test_list_admin_users(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_get(self, url, **kwargs):
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "u-1",
                        "email": "user1@bank.local",
                        "phone": "+919876543210",
                        "full_name": "User One",
                        "is_active": True,
                        "failed_login_count": 0,
                        "roles": ["CUSTOMER"],
                        "created_at": "2026-11-10T00:00:00Z",
                    }
                ],
            )

        monkeypatch.setattr(httpx.Client, "get", mock_get)
        client = BankingClient("http://banking-service")
        users = client.list_admin_users("admin-token")
        assert len(users) == 1
        assert users[0]["email"] == "user1@bank.local"

    def test_update_user_status(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_patch(self, url, **kwargs):
            assert kwargs.get("json") == {"is_active": False}
            return httpx.Response(200, json={"id": "u-1", "is_active": False})

        monkeypatch.setattr(httpx.Client, "patch", mock_patch)
        client = BankingClient("http://banking-service")
        res = client.update_user_status("u-1", False, "admin-token")
        assert res["is_active"] is False

    def test_update_user_roles(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_put(self, url, **kwargs):
            assert kwargs.get("json") == {"roles": ["CUSTOMER", "ADMIN"]}
            return httpx.Response(200, json={"id": "u-1", "roles": ["CUSTOMER", "ADMIN"]})

        monkeypatch.setattr(httpx.Client, "put", mock_put)
        client = BankingClient("http://banking-service")
        res = client.update_user_roles("u-1", ["CUSTOMER", "ADMIN"], "admin-token")
        assert "ADMIN" in res["roles"]

    def test_list_admin_transactions(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_get(self, url, **kwargs):
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "t-1",
                        "reference": "TXN1001",
                        "user_id": "u-1",
                        "type": "TRANSFER",
                        "amount_minor": 500000,
                        "fee_minor": 500,
                        "total_debit_minor": 500500,
                        "currency": "INR",
                        "status": "COMPLETED",
                        "channel": "IMPS",
                        "source_account_masked": "XXXXXX1234",
                        "created_at": "2026-11-11T10:00:00Z",
                    }
                ],
            )

        monkeypatch.setattr(httpx.Client, "get", mock_get)
        client = BankingClient("http://banking-service")
        txns = client.list_admin_transactions("admin-token")
        assert len(txns) == 1
        assert txns[0]["reference"] == "TXN1001"

    def test_list_admin_loans(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_get(self, url, **kwargs):
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "loan-1",
                        "user_id": "u-1",
                        "loan_type": "PERSONAL",
                        "amount_minor": 20000000,
                        "tenure_months": 24,
                        "monthly_income_minor": 8000000,
                        "status": "APPROVED",
                        "created_at": "2026-11-11T09:00:00Z",
                    }
                ],
            )

        monkeypatch.setattr(httpx.Client, "get", mock_get)
        client = BankingClient("http://banking-service")
        loans = client.list_admin_loans("admin-token")
        assert len(loans) == 1
        assert loans[0]["status"] == "APPROVED"

    def test_get_and_update_admin_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        cfg_data = {
            "transfer_per_txn_limit_minor": 20000000,
            "transfer_daily_limit_minor": 100000000,
            "transfer_approval_expiry_seconds": 300,
            "duplicate_window_seconds": 120,
            "txn_auth_method": "PIN",
            "txn_auth_max_attempts": 3,
        }

        def mock_get(self, url, **kwargs):
            return httpx.Response(200, json=cfg_data)

        def mock_patch(self, url, **kwargs):
            return httpx.Response(200, json=kwargs.get("json", {}))

        monkeypatch.setattr(httpx.Client, "get", mock_get)
        monkeypatch.setattr(httpx.Client, "patch", mock_patch)

        client = BankingClient("http://banking-service")
        res_get = client.get_admin_config("admin-token")
        assert res_get["txn_auth_method"] == "PIN"

        res_patch = client.update_admin_config({"transfer_per_txn_limit_minor": 25000000}, "admin-token")
        assert res_patch["transfer_per_txn_limit_minor"] == 25000000

    def test_list_and_get_audit_logs(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_get(self, url, **kwargs):
            if "/audit-logs/" in url:
                return httpx.Response(200, json={"id": "log-1", "action": "LOGIN", "outcome": "SUCCESS"})
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "log-1",
                        "actor_user_id": "u-1",
                        "actor_type": "CUSTOMER",
                        "action": "TRANSFER_EXECUTE",
                        "resource_type": "bank_transaction",
                        "resource_id": "t-1",
                        "outcome": "SUCCESS",
                        "timestamp": "2026-11-11T12:00:00Z",
                    }
                ],
            )

        monkeypatch.setattr(httpx.Client, "get", mock_get)
        client = BankingClient("http://banking-service")
        logs = client.list_audit_logs("admin-token", action="TRANSFER_EXECUTE")
        assert len(logs) == 1
        assert logs[0]["action"] == "TRANSFER_EXECUTE"

        single = client.get_audit_log("log-1", "admin-token")
        assert single["action"] == "LOGIN"


class TestAIClientAdmin:
    def test_get_ai_stats(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_get(self, url, **kwargs):
            return httpx.Response(
                200,
                json={
                    "total_conversations": 42,
                    "active_conversations": 18,
                    "total_messages": 210,
                    "total_agent_executions": 350,
                    "avg_latency_ms": 145.2,
                    "total_pending_approvals": 15,
                    "active_pending_approvals": 2,
                },
            )

        monkeypatch.setattr(httpx.Client, "get", mock_get)
        client = AIClient("http://ai-service")
        stats = client.get_ai_stats("admin-token")
        assert stats["total_conversations"] == 42
        assert stats["avg_latency_ms"] == 145.2

    def test_list_admin_conversations_and_messages(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_get(self, url, **kwargs):
            if "/messages" in url:
                return httpx.Response(
                    200,
                    json=[
                        {"id": "m-1", "role": "user", "content_masked": "Pay rent ₹10,000"},
                        {"id": "m-2", "role": "assistant", "content_masked": "Transfer prepared"},
                    ],
                )
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "c-101",
                        "banking_user_id": "u-1",
                        "title": "Rent Payment",
                        "status": "ACTIVE",
                        "message_count": 2,
                    }
                ],
            )

        monkeypatch.setattr(httpx.Client, "get", mock_get)
        client = AIClient("http://ai-service")
        convs = client.list_admin_conversations("admin-token")
        assert len(convs) == 1
        assert convs[0]["title"] == "Rent Payment"

        msgs = client.get_admin_conversation_messages("c-101", "admin-token")
        assert len(msgs) == 2
        assert msgs[0]["role"] == "user"

    def test_list_agent_executions(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_get(self, url, **kwargs):
            return httpx.Response(
                200,
                json=[
                    {
                        "id": "ex-1",
                        "conversation_id": "c-101",
                        "node": "banking_ops",
                        "status": "SUCCESS",
                        "latency_ms": 85,
                    }
                ],
            )

        monkeypatch.setattr(httpx.Client, "get", mock_get)
        client = AIClient("http://ai-service")
        execs = client.list_agent_executions("admin-token", node="banking_ops")
        assert len(execs) == 1
        assert execs[0]["node"] == "banking_ops"

    def test_get_and_update_ai_config(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def mock_get(self, url, **kwargs):
            return httpx.Response(
                200,
                json={
                    "llm_provider": "openai",
                    "llm_model": "gpt-4o-mini",
                    "llm_temperature": 0.0,
                    "llm_max_tokens": 2048,
                    "embedding_provider": "openai",
                    "embedding_model": "text-embedding-3-small",
                    "rag_top_k": 6,
                    "rag_min_score": 0.3,
                    "search_provider": "none",
                },
            )

        def mock_patch(self, url, **kwargs):
            return httpx.Response(200, json=kwargs.get("json", {}))

        monkeypatch.setattr(httpx.Client, "get", mock_get)
        monkeypatch.setattr(httpx.Client, "patch", mock_patch)

        client = AIClient("http://ai-service")
        cfg = client.get_ai_config("admin-token")
        assert cfg["llm_model"] == "gpt-4o-mini"

        updated = client.update_ai_config({"llm_temperature": 0.1}, "admin-token")
        assert updated["llm_temperature"] == 0.1


class TestAdminDashboardHelpers:
    def test_format_currency_inr(self) -> None:
        assert format_currency_inr(None) == "₹0.00"
        assert format_currency_inr(0) == "₹0.00"
        assert format_currency_inr(500000) == "₹5,000.00"
        assert format_currency_inr(125000050) == "₹1,250,000.50"


class TestAdminDashboardAppTest:
    def test_admin_page_blocks_customer(self) -> None:
        """Route guard must reject Customer role with Access Denied."""
        at = AppTest.from_file("../pages/4_Admin.py", default_timeout=10)
        at.session_state["authenticated"] = True
        at.session_state["user"] = {
            "id": "c-1",
            "email": "customer@bank.local",
            "roles": ["CUSTOMER"],
        }
        at.session_state["roles"] = ["CUSTOMER"]
        at.session_state["access_token"] = "cust-token"

        at.run()
        assert any("Access Denied" in err.value for err in at.error)

    def test_admin_page_renders_for_admin(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Admin user can view all 8 tabs, metrics, and configuration forms."""
        def mock_get(self, url, **kwargs):
            if "/admin/stats" in url:
                return httpx.Response(
                    200,
                    json={
                        "total_users": 100,
                        "active_users": 95,
                        "total_accounts": 120,
                        "total_transactions": 500,
                        "total_loans_submitted": 10,
                        "total_loan_amount_minor": 50000000,
                    },
                )
            if "/admin/ai-stats" in url:
                return httpx.Response(
                    200,
                    json={
                        "total_conversations": 30,
                        "active_conversations": 12,
                        "total_messages": 180,
                        "total_agent_executions": 240,
                        "avg_latency_ms": 110.5,
                        "total_pending_approvals": 8,
                        "active_pending_approvals": 1,
                    },
                )
            if "/admin/users" in url:
                return httpx.Response(200, json=[])
            if "/admin/transactions" in url:
                return httpx.Response(200, json=[])
            if "/admin/loan-applications" in url:
                return httpx.Response(200, json=[])
            if "/admin/conversations" in url:
                return httpx.Response(200, json=[])
            if "/audit-logs" in url:
                return httpx.Response(200, json=[])
            if "/admin/agent-executions" in url:
                return httpx.Response(200, json=[])
            if "/admin/config" in url:
                return httpx.Response(
                    200,
                    json={
                        "transfer_per_txn_limit_minor": 20000000,
                        "transfer_daily_limit_minor": 100000000,
                        "transfer_approval_expiry_seconds": 300,
                        "duplicate_window_seconds": 120,
                        "txn_auth_method": "PIN",
                    },
                )
            if "/admin/ai-config" in url:
                return httpx.Response(
                    200,
                    json={
                        "llm_model": "gpt-4o-mini",
                        "llm_temperature": 0.0,
                        "rag_top_k": 6,
                        "rag_min_score": 0.3,
                    },
                )
            return httpx.Response(200, json={})

        monkeypatch.setattr(httpx.Client, "get", mock_get)

        at = AppTest.from_file("../pages/4_Admin.py", default_timeout=10)
        at.session_state["authenticated"] = True
        at.session_state["user"] = {
            "id": "adm-1",
            "email": "admin@bank.local",
            "roles": ["ADMIN"],
        }
        at.session_state["roles"] = ["ADMIN"]
        at.session_state["access_token"] = "admin-token"

        at.run()
        assert not at.exception
        # Header title
        assert any("Administration & System Controls" in t.value for t in at.title)
        # 8 Tabs
        assert len(at.tabs) == 8
        # Overview metrics present
        metric_labels = [m.label for m in at.metric]
        assert "Registered Users" in metric_labels
        assert "Total Transactions" in metric_labels
        assert "Total Conversations" in metric_labels

    def test_admin_page_renders_for_auditor(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Auditor user is allowed access and presented with auditor read-only notice."""
        def mock_get(self, url, **kwargs):
            return httpx.Response(200, json={})

        monkeypatch.setattr(httpx.Client, "get", mock_get)

        at = AppTest.from_file("../pages/4_Admin.py", default_timeout=10)
        at.session_state["authenticated"] = True
        at.session_state["user"] = {
            "id": "aud-1",
            "email": "auditor@bank.local",
            "roles": ["AUDITOR"],
        }
        at.session_state["roles"] = ["AUDITOR"]
        at.session_state["access_token"] = "auditor-token"

        at.run()
        assert not at.exception
        # Check Auditor info notification
        assert any("Auditor Mode Enabled" in inf.value for inf in at.info)
