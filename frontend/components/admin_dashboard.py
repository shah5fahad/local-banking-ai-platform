"""Admin dashboard component for platform statistics, user management, audit trails, and configuration (T6.5)."""
from __future__ import annotations

import json
from typing import Any

import streamlit as st

from clients.ai_client import AIAPIError, AIClient
from clients.banking_client import BankingAPIError, BankingClient
from components.history_view import format_iso_timestamp
from state.session import get_access_token, get_ai_client, get_banking_client, has_role


def format_currency_inr(minor_units: int | None) -> str:
    """Format minor units (paise) to INR currency string."""
    if minor_units is None:
        return "₹0.00"
    rupees = minor_units / 100.0
    return f"₹{rupees:,.2f}"


def render_overview_stats(
    banking_client: BankingClient,
    ai_client: AIClient,
    access_token: str,
) -> None:
    """Render high-level platform and AI system statistics."""
    st.subheader("📊 System Overview & Performance Metrics")

    col_btn, _ = st.columns([1, 4])
    with col_btn:
        if st.button("🔄 Refresh Metrics", key="adm_stats_refresh"):
            st.rerun()

    # 1. Banking Platform Metrics
    st.markdown("##### 🏦 Core Banking Platform")
    try:
        b_stats = banking_client.get_admin_stats(access_token)
        col1, col2, col3 = st.columns(3)
        col1.metric("Registered Users", b_stats.get("total_users", 0))
        col2.metric("Active Users", b_stats.get("active_users", 0))
        col3.metric("Total Bank Accounts", b_stats.get("total_accounts", 0))

        col4, col5, col6 = st.columns(3)
        col4.metric("Total Transactions", b_stats.get("total_transactions", 0))
        col5.metric("Loans Submitted", b_stats.get("total_loans_submitted", 0))
        col6.metric(
            "Total Loan Volume",
            format_currency_inr(b_stats.get("total_loan_amount_minor", 0)),
        )
    except Exception as exc:
        st.error(f"Failed to fetch banking stats: {exc}")

    st.markdown("---")

    # 2. AI Chat & Execution Metrics
    st.markdown("##### 🤖 Banking AI & LangGraph Engine")
    try:
        a_stats = ai_client.get_ai_stats(access_token)
        c1, c2, c3 = st.columns(3)
        c1.metric("Total Conversations", a_stats.get("total_conversations", 0))
        c1_active = a_stats.get("active_conversations", 0)
        c2.metric("Active Conversations", c1_active)
        c3.metric("Total Messages", a_stats.get("total_messages", 0))

        c4, c5, c6 = st.columns(3)
        c4.metric("Agent Node Executions", a_stats.get("total_agent_executions", 0))
        avg_lat = a_stats.get("avg_latency_ms")
        c5.metric("Avg Node Latency", f"{avg_lat} ms" if avg_lat is not None else "N/A")
        c6.metric(
            "Pending Approvals",
            f"{a_stats.get('active_pending_approvals', 0)} / {a_stats.get('total_pending_approvals', 0)}",
        )
    except Exception as exc:
        st.error(f"Failed to fetch AI system stats: {exc}")


def render_users_and_roles(
    banking_client: BankingClient,
    access_token: str,
    is_admin: bool,
) -> None:
    """Render user management, active status toggle, and role assignment."""
    st.subheader("👥 Users & Role Management")
    st.markdown("Manage registered customer accounts, lockout status, and administrative role assignments.")

    try:
        users = banking_client.list_admin_users(access_token, page=1, page_size=100)
    except Exception as exc:
        st.error(f"Failed to load users: {exc}")
        return

    if not users:
        st.info("No registered users found.")
        return

    for u in users:
        u_id = u.get("id", "")
        name = u.get("full_name", "N/A")
        email = u.get("email", "N/A")
        phone = u.get("phone", "N/A")
        is_active = bool(u.get("is_active", True))
        roles: list[str] = u.get("roles", [])
        failed_logins = u.get("failed_login_count", 0)
        locked_until = u.get("locked_until")
        created_at = format_iso_timestamp(u.get("created_at"))

        with st.container(border=True):
            col_info, col_status, col_actions = st.columns([3, 2, 3])
            with col_info:
                st.markdown(f"**👤 {name}** (`{email}`)")
                st.caption(f"Phone: `{phone}` &nbsp;|&nbsp; Registered: {created_at} &nbsp;|&nbsp; ID: `{u_id}`")
            with col_status:
                status_badge = "🟢 Active" if is_active else "🔴 Deactivated"
                role_badges = " ".join([f"`{r}`" for r in roles])
                st.markdown(f"**Status:** {status_badge} &nbsp;|&nbsp; **Roles:** {role_badges}")
                if locked_until:
                    st.warning(f"🔒 Account locked until: {format_iso_timestamp(locked_until)}")
                elif failed_logins > 0:
                    st.caption(f"Failed Logins: {failed_logins}/5")

            with col_actions:
                col_btn_status, col_btn_role = st.columns(2)
                with col_btn_status:
                    if is_active:
                        if st.button("🔴 Deactivate", key=f"deact_usr_{u_id}", disabled=not is_admin, use_container_width=True):
                            try:
                                banking_client.update_user_status(u_id, False, access_token)
                                st.toast(f"Deactivated {name}", icon="🔴")
                                st.rerun()
                            except Exception as e:
                                st.error(str(e))
                    else:
                        if st.button("🟢 Activate", key=f"act_usr_{u_id}", disabled=not is_admin, use_container_width=True):
                            try:
                                banking_client.update_user_status(u_id, True, access_token)
                                st.toast(f"Activated {name}", icon="🟢")
                                st.rerun()
                            except Exception as e:
                                st.error(str(e))

                with col_btn_role:
                    with st.popover("🛡️ Roles", disabled=not is_admin, use_container_width=True):
                        st.markdown(f"**Edit Roles for {name}**")
                        new_roles = st.multiselect(
                            "Select Assigned Roles",
                            options=["CUSTOMER", "ADMIN", "AUDITOR"],
                            default=roles,
                            key=f"roles_select_{u_id}",
                        )
                        if st.button("Save Roles", key=f"save_roles_{u_id}", type="primary"):
                            if not new_roles:
                                st.error("User must have at least one assigned role.")
                            else:
                                try:
                                    banking_client.update_user_roles(u_id, new_roles, access_token)
                                    st.toast(f"Updated roles for {name}", icon="🛡️")
                                    st.rerun()
                                except Exception as e:
                                    st.error(str(e))


def render_admin_transactions(
    banking_client: BankingClient,
    access_token: str,
) -> None:
    """Render platform transactions with masked accounts and settlement status."""
    st.subheader("💳 Platform Transactions (All Customers)")
    st.markdown("Real-time view of transfers, card payments, and settlements across all customer accounts.")

    try:
        txns = banking_client.list_admin_transactions(access_token, page=1, page_size=100)
    except Exception as exc:
        st.error(f"Failed to fetch transactions: {exc}")
        return

    if not txns:
        st.info("No transactions found on the platform.")
        return

    rows = []
    for t in txns:
        status = t.get("status", "UNKNOWN")
        badge = "🟢 " + status if status in ("COMPLETED", "EXECUTED") else ("🔴 " + status if "FAIL" in status else "⏳ " + status)
        rows.append({
            "Reference": t.get("reference"),
            "User ID": t.get("user_id"),
            "Type": t.get("type"),
            "Amount": format_currency_inr(t.get("amount_minor")),
            "Fee": format_currency_inr(t.get("fee_minor")),
            "Total Debit": format_currency_inr(t.get("total_debit_minor")),
            "Source Account": t.get("source_account_masked") or "N/A",
            "Channel": t.get("channel") or "-",
            "Status": badge,
            "Date": format_iso_timestamp(t.get("created_at")),
            "Failure Reason": t.get("failure_reason") or "-",
        })

    st.dataframe(rows, use_container_width=True)


def render_admin_loans(
    banking_client: BankingClient,
    access_token: str,
) -> None:
    """Render loan applications submitted across the platform."""
    st.subheader("🏦 Loan Applications & Underwriting Review")
    st.markdown("All pre-approved and submitted retail and commercial loan applications.")

    try:
        loans = banking_client.list_admin_loans(access_token, page=1, page_size=100)
    except Exception as exc:
        st.error(f"Failed to fetch loan applications: {exc}")
        return

    if not loans:
        st.info("No loan applications submitted yet.")
        return

    rows = []
    for l in loans:
        st_val = l.get("status", "UNKNOWN")
        st_badge = "🟢 APPROVED" if st_val == "APPROVED" else ("🔴 REJECTED" if st_val == "REJECTED" else "⏳ " + st_val)
        rows.append({
            "Application ID": l.get("id"),
            "User ID": l.get("user_id"),
            "Loan Type": l.get("loan_type"),
            "Requested Amount": format_currency_inr(l.get("amount_minor")),
            "Tenure (Months)": l.get("tenure_months"),
            "Monthly Income": format_currency_inr(l.get("monthly_income_minor")),
            "Status": st_badge,
            "Submitted Date": format_iso_timestamp(l.get("created_at")),
            "Decision Date": format_iso_timestamp(l.get("approved_at")) or "-",
            "Rejection Reason": l.get("rejection_reason") or "-",
        })

    st.dataframe(rows, use_container_width=True)


def render_masked_chat_monitor(
    ai_client: AIClient,
    access_token: str,
) -> None:
    """Render masked conversation monitor for compliance inspection."""
    st.subheader("💬 Masked Chat Monitor (Compliance & Audit)")
    st.markdown(
        "Inspect customer conversations for compliance. In accordance with the security invariant, "
        "all account numbers, passwords, PINs, and personal identity data are masked (`[MASKED]`)."
    )

    try:
        convs = ai_client.list_admin_conversations(access_token, page=1, page_size=50)
    except Exception as exc:
        st.error(f"Failed to load monitored conversations: {exc}")
        return

    if not convs:
        st.info("No active or historical chat conversations found.")
        return

    for c in convs:
        cid = c.get("id", "")
        title = c.get("title") or "Untitled Conversation"
        b_uid = c.get("banking_user_id", "")
        msg_count = c.get("message_count", 0)
        c_status = c.get("status", "ACTIVE")
        updated = format_iso_timestamp(c.get("updated_at"))

        with st.container(border=True):
            col_hd, col_btn = st.columns([4, 1])
            with col_hd:
                st.markdown(f"**💬 {title}** &nbsp;(`{cid}`)")
                st.caption(
                    f"Customer ID: `{b_uid}` &nbsp;|&nbsp; Messages: {msg_count} &nbsp;|&nbsp; "
                    f"Status: `{c_status}` &nbsp;|&nbsp; Last Activity: {updated}"
                )
            with col_btn:
                inspect = st.toggle("🔍 Inspect", key=f"inspect_conv_{cid}")

            if inspect:
                st.markdown("##### 📜 Turn-by-Turn Masked Dialogue")
                try:
                    msgs = ai_client.get_admin_conversation_messages(cid, access_token)
                    if not msgs:
                        st.info("No messages recorded in this conversation.")
                    else:
                        for m in msgs:
                            role = m.get("role", "user")
                            role_label = "👤 User" if role == "user" else ("🤖 Banking Assistant" if role == "assistant" else f"⚙️ {role.capitalize()}")
                            ts = format_iso_timestamp(m.get("created_at"))
                            with st.chat_message(role):
                                st.markdown(f"**{role_label}** &nbsp;•&nbsp; `{ts}`")
                                st.markdown(m.get("content_masked", ""))
                                cit_str = m.get("citations_json")
                                if cit_str:
                                    try:
                                        cits = json.loads(cit_str)
                                        if isinstance(cits, list) and cits:
                                            with st.expander(f"📚 Regulatory Citations ({len(cits)})"):
                                                for cit in cits:
                                                    st.caption(f"- **{cit.get('title', 'Policy')}** § {cit.get('section', 'General')}: {cit.get('quote', '')}")
                                    except Exception:
                                        pass
                except Exception as ex:
                    st.error(f"Failed to fetch conversation transcript: {ex}")


def render_audit_viewer(
    banking_client: BankingClient,
    access_token: str,
) -> None:
    """Render searchable, immutable audit log trail."""
    st.subheader("🛡️ Immutable Audit Log Trail")
    st.markdown("Audit record of all administrative, transactional, authentication, and security events.")

    col1, col2, col3, col_ref = st.columns([2, 2, 2, 1])
    with col1:
        action_filter = st.text_input("Filter Action", placeholder="e.g. TRANSFER_EXECUTE, LOGIN", key="audit_filter_action").strip()
    with col2:
        outcome_filter = st.selectbox("Filter Outcome", options=["All Outcomes", "SUCCESS", "FAILURE"], key="audit_filter_outcome")
    with col3:
        actor_filter = st.text_input("Filter Actor ID", placeholder="User UUID or 'system'", key="audit_filter_actor").strip()
    with col_ref:
        st.write("")
        st.write("")
        if st.button("🔄 Refresh", key="audit_refresh_btn", use_container_width=True):
            st.rerun()

    api_outcome = None if outcome_filter == "All Outcomes" else outcome_filter
    try:
        logs = banking_client.list_audit_logs(
            access_token=access_token,
            action=action_filter or None,
            outcome=api_outcome,
            actor=actor_filter or None,
            page=1,
            page_size=100,
        )
    except Exception as exc:
        st.error(f"Failed to load audit logs: {exc}")
        return

    if not logs:
        st.info("No audit logs found matching criteria.")
        return

    rows = []
    for log in logs:
        outcome = log.get("outcome", "")
        out_badge = "🟢 SUCCESS" if outcome == "SUCCESS" else "🔴 FAILURE"
        rows.append({
            "Timestamp": format_iso_timestamp(log.get("timestamp")),
            "Action": log.get("action"),
            "Actor Type": log.get("actor_type"),
            "Actor ID": log.get("actor_user_id") or "SYSTEM",
            "Resource": f"{log.get('resource_type', '')}:{log.get('resource_id', '')}",
            "Outcome": out_badge,
            "IP Address": log.get("ip_address") or "-",
            "Request ID": log.get("request_id") or "-",
            "Details": json.dumps(log.get("details") or {}, indent=2),
        })

    st.dataframe(rows, use_container_width=True)


def render_agent_executions(
    ai_client: AIClient,
    access_token: str,
) -> None:
    """Render LangGraph node execution traces and latency metrics."""
    st.subheader("⚡ LangGraph Agent Executions & Tool Traces")
    st.markdown("Step traces of agent node transitions, tool invocations, and supervisor routing decisions.")

    col1, col2, col3 = st.columns([2, 2, 1])
    with col1:
        node_filter = st.selectbox(
            "Filter by Node",
            options=["All Nodes", "input_guard", "supervisor", "banking_ops", "policy_rag", "external_research", "response"],
            key="exec_node_filter",
        )
    with col2:
        status_filter = st.selectbox(
            "Filter by Status",
            options=["All Statuses", "SUCCESS", "ERROR", "BLOCKED"],
            key="exec_status_filter",
        )
    with col3:
        st.write("")
        st.write("")
        if st.button("🔄 Refresh", key="exec_refresh_btn", use_container_width=True):
            st.rerun()

    api_node = None if node_filter == "All Nodes" else node_filter
    api_status = None if status_filter == "All Statuses" else status_filter

    try:
        executions = ai_client.list_agent_executions(
            access_token=access_token,
            node=api_node,
            status=api_status,
            page=1,
            page_size=100,
        )
    except Exception as exc:
        st.error(f"Failed to load agent executions: {exc}")
        return

    if not executions:
        st.info("No agent executions found.")
        return

    rows = []
    for ex in executions:
        st_val = ex.get("status", "")
        st_badge = "🟢 " + st_val if st_val == "SUCCESS" else ("🔴 " + st_val if st_val in ("ERROR", "BLOCKED") else st_val)
        rows.append({
            "Time": format_iso_timestamp(ex.get("created_at")),
            "Node": ex.get("node"),
            "Route": ex.get("route") or "-",
            "Tool": ex.get("tool_name") or "-",
            "Masked Tool Args": ex.get("tool_args_masked") or "-",
            "Status": st_badge,
            "Latency (ms)": ex.get("latency_ms") if ex.get("latency_ms") is not None else "-",
            "Tokens": ex.get("token_usage") if ex.get("token_usage") is not None else "-",
            "Error Code": ex.get("error_code") or "-",
            "Conversation ID": ex.get("conversation_id"),
        })

    st.dataframe(rows, use_container_width=True)


def render_system_config(
    banking_client: BankingClient,
    ai_client: AIClient,
    access_token: str,
    is_admin: bool,
) -> None:
    """Render runtime limit settings and AI hyperparameters configuration."""
    st.subheader("⚙️ System Configuration & Runtime Limits")

    col_bank, col_ai = st.columns(2)

    # 1. Banking Limits Form
    with col_bank:
        st.markdown("##### 🏦 Banking Limits & Parameters")
        try:
            b_cfg = banking_client.get_admin_config(access_token)
        except Exception as exc:
            st.error(f"Failed to fetch banking config: {exc}")
            b_cfg = {}

        with st.form("banking_config_form"):
            per_txn_rs = (b_cfg.get("transfer_per_txn_limit_minor", 20000000) or 0) // 100
            daily_rs = (b_cfg.get("transfer_daily_limit_minor", 100000000) or 0) // 100
            expiry_sec = b_cfg.get("transfer_approval_expiry_seconds", 300)
            dup_sec = b_cfg.get("duplicate_window_seconds", 120)
            auth_method = b_cfg.get("txn_auth_method", "PIN")

            new_per_txn = st.number_input(
                "Per-Transaction Transfer Limit (₹)",
                min_value=100,
                max_value=10000000,
                value=int(per_txn_rs),
                step=5000,
                disabled=not is_admin,
            )
            new_daily = st.number_input(
                "Daily Transfer Limit (₹)",
                min_value=100,
                max_value=50000000,
                value=int(daily_rs),
                step=10000,
                disabled=not is_admin,
            )
            new_expiry = st.number_input(
                "Transfer Approval Expiry (seconds)",
                min_value=30,
                max_value=3600,
                value=int(expiry_sec),
                step=30,
                disabled=not is_admin,
            )
            new_dup = st.number_input(
                "Duplicate Transaction Window (seconds)",
                min_value=10,
                max_value=600,
                value=int(dup_sec),
                step=10,
                disabled=not is_admin,
            )
            new_auth = st.selectbox(
                "Authentication Method",
                options=["PIN", "OTP"],
                index=0 if auth_method == "PIN" else 1,
                disabled=not is_admin,
            )

            btn_save_bank = st.form_submit_button("Save Banking Limits", type="primary", disabled=not is_admin)

        if btn_save_bank:
            try:
                banking_client.update_admin_config(
                    {
                        "transfer_per_txn_limit_minor": int(new_per_txn * 100),
                        "transfer_daily_limit_minor": int(new_daily * 100),
                        "transfer_approval_expiry_seconds": int(new_expiry),
                        "duplicate_window_seconds": int(new_dup),
                        "txn_auth_method": new_auth,
                    },
                    access_token,
                )
                st.success("✅ Banking configuration updated successfully!")
            except Exception as e:
                st.error(f"Failed to update banking config: {e}")

    # 2. AI Parameters Form
    with col_ai:
        st.markdown("##### 🤖 AI Model & Retrieval Hyperparameters")
        try:
            a_cfg = ai_client.get_ai_config(access_token)
        except Exception as exc:
            st.error(f"Failed to fetch AI config: {exc}")
            a_cfg = {}

        with st.form("ai_config_form"):
            current_model = a_cfg.get("llm_model", "gpt-4o-mini")
            current_temp = float(a_cfg.get("llm_temperature", 0.0))
            current_top_k = int(a_cfg.get("rag_top_k", 6))
            current_min_score = float(a_cfg.get("rag_min_score", 0.3))

            new_model = st.text_input(
                "LLM Model Name",
                value=current_model,
                disabled=not is_admin,
                help="Active model identifier for LangGraph agents",
            )
            new_temp = st.slider(
                "LLM Temperature",
                min_value=0.0,
                max_value=1.0,
                value=current_temp,
                step=0.05,
                disabled=not is_admin,
                help="0.0 provides deterministic, factual financial responses",
            )
            new_top_k = st.slider(
                "RAG Top-K Chunks",
                min_value=1,
                max_value=20,
                value=current_top_k,
                step=1,
                disabled=not is_admin,
                help="Number of document chunks retrieved per policy query",
            )
            new_min_score = st.slider(
                "RAG Min Relevance Score",
                min_value=0.0,
                max_value=1.0,
                value=current_min_score,
                step=0.05,
                disabled=not is_admin,
                help="Minimum vector similarity threshold for document chunks",
            )

            btn_save_ai = st.form_submit_button("Save AI Hyperparameters", type="primary", disabled=not is_admin)

        if btn_save_ai:
            try:
                ai_client.update_ai_config(
                    {
                        "llm_model": new_model.strip(),
                        "llm_temperature": float(new_temp),
                        "rag_top_k": int(new_top_k),
                        "rag_min_score": float(new_min_score),
                    },
                    access_token,
                )
                st.success("✅ AI configuration updated successfully!")
            except Exception as e:
                st.error(f"Failed to update AI config: {e}")


def render_admin_dashboard() -> None:
    """Main administrative dashboard view incorporating all 8 control planes."""
    token = get_access_token()
    if not token:
        st.warning("Please sign in with administrator or auditor credentials.")
        return

    banking_client = get_banking_client()
    ai_client = get_ai_client()
    is_admin = has_role("ADMIN")

    if not is_admin:
        st.info(
            "ℹ️ **Auditor Mode Enabled**: You have read-only inspection access across platform stats, "
            "transactions, loan applications, masked chats, audit trails, and agent execution traces. "
            "Modifications (status changes, role assignments, limit updates) require Administrator privileges."
        )

    (
        tab_stats,
        tab_users,
        tab_txns,
        tab_loans,
        tab_chats,
        tab_audit,
        tab_execs,
        tab_cfg,
    ) = st.tabs(
        [
            "📊 Overview",
            "👥 Users & Roles",
            "💳 Transactions",
            "🏦 Loans",
            "💬 Masked Chats",
            "🛡️ Audit Trail",
            "⚡ Agent Executions",
            "⚙️ Configuration",
        ]
    )

    with tab_stats:
        render_overview_stats(banking_client, ai_client, token)

    with tab_users:
        render_users_and_roles(banking_client, token, is_admin)

    with tab_txns:
        render_admin_transactions(banking_client, token)

    with tab_loans:
        render_admin_loans(banking_client, token)

    with tab_chats:
        render_masked_chat_monitor(ai_client, token)

    with tab_audit:
        render_audit_viewer(banking_client, token)

    with tab_execs:
        render_agent_executions(ai_client, token)

    with tab_cfg:
        render_system_config(banking_client, ai_client, token, is_admin)
