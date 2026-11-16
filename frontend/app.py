"""Local Banking AI Platform - Main Streamlit Application."""
from __future__ import annotations

import streamlit as st

from components.auth_forms import render_login_form, render_signup_form
from components.customer_dashboard import render_customer_dashboard
from components.sidebar import render_sidebar_auth
from state.session import (
    check_idle_timeout,
    get_banking_client,
    get_current_roles,
    get_current_user,
    init_session,
    is_authenticated,
    logout_user,
)

st.set_page_config(
    page_title="Local Banking AI Platform",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Initialize server-side session state & idle timer
init_session()
timed_out = check_idle_timeout()

# Render auth profile and logout in sidebar
render_sidebar_auth()

if timed_out or st.session_state.get("timed_out"):
    st.error("⏳ **Session Expired:** You were logged out due to 15 minutes of inactivity. Please log in again to continue.")
    st.session_state.timed_out = False

if not is_authenticated():
    st.title("🏦 Local Banking AI Platform")
    st.markdown(
        "Welcome to the **Local Banking AI Platform**, a private, on-premise banking assistant "
        "featuring human-in-the-loop transaction approvals, multi-factor authorization, and secure banking operations."
    )

    auth_tab1, auth_tab2 = st.tabs(["🔑 Sign In", "📝 Create Account"])

    with auth_tab1:
        render_login_form()

    with auth_tab2:
        render_signup_form()

    st.markdown("---")
    with st.expander("ℹ️ Development & Demo Credentials", expanded=False):
        st.markdown(
            "For local development and testing, you may use:\n"
            "- **Admin Account:** `admin@bank.local` / `Admin@Bank2024!`\n"
            "- **Customer Account:** Register a new account above with a 12+ char password, or use test accounts.\n"
        )
else:
    user = get_current_user() or {}
    roles = get_current_roles()
    full_name = user.get("full_name", "Customer")

    st.title(f"👋 Welcome, {full_name}!")
    st.markdown("Your secure banking session is active. Choose an action below or use the sidebar to navigate.")

    token = st.session_state.get("access_token")
    if token:
        client = get_banking_client()
        render_customer_dashboard(client, token)
        st.markdown("---")

    col1, col2 = st.columns(2)

    with col1:
        with st.container(border=True):
            st.subheader("💬 AI Banking Assistant")
            st.write(
                "Inquire about account balances, prepare fund transfers, apply for loans, "
                "pay credit card bills, and search regulatory banking guidelines."
            )
            if st.button("Open AI Chat →", key="nav_chat_btn", use_container_width=True, type="primary"):
                st.switch_page("pages/1_Chat.py")

        with st.container(border=True):
            st.subheader("🏦 Direct Banking")
            st.write(
                "Directly manage linked bank accounts, verify transfer beneficiaries with PIN, "
                "check real-time balances, and view transaction history."
            )
            if st.button("Direct Banking →", key="nav_direct_banking_btn", use_container_width=True):
                st.switch_page("pages/5_Banking.py")

    with col2:
        with st.container(border=True):
            st.subheader("📜 Chat History & Transcripts")
            st.write("Browse, search, rename, and review past multi-turn AI conversations and citations.")
            if st.button("View History →", key="nav_history_btn", use_container_width=True):
                st.switch_page("pages/2_History.py")

        if "ADMIN" in roles or "AUDITOR" in roles:
            with st.container(border=True):
                st.subheader("📚 Banking Documents")
                st.write(
                    "Upload and index regulatory policies into the ChromaDB Vector Store "
                    "for verified RAG retrieval. *(Admin & Auditor)*"
                )
                if st.button("Manage Documents →", key="nav_docs_btn", use_container_width=True):
                    st.switch_page("pages/3_Documents.py")

        if "ADMIN" in roles or "AUDITOR" in roles:
            with st.container(border=True):
                st.subheader("🛠️ Admin Dashboard")
                st.write(
                    "Manage system users, reassign roles, configure transaction limits, and monitor "
                    "masked chats, audit trails, and agent telemetry."
                )
                if st.button("Admin Controls →", key="nav_admin_btn", use_container_width=True):
                    st.switch_page("pages/4_Admin.py")

    st.markdown("---")
    with st.expander("🔐 Active Login Sessions & Security Info", expanded=False):
        token = st.session_state.get("access_token")
        if token:
            try:
                client = get_banking_client()
                sessions = client.get_sessions(token)
                if sessions:
                    st.write(f"You currently have **{len(sessions)}** active session(s):")
                    for s in sessions:
                        is_curr = " *(Current Session)*" if s.get("is_current") else ""
                        st.markdown(
                            f"- **Session ID:** `{s.get('id')}`{is_curr} — "
                            f"**Created:** `{s.get('created_at')}` — **IP:** `{s.get('ip') or 'Local'}`"
                        )
                else:
                    st.write("Active session established.")
            except Exception as e:
                st.caption(f"Session info unavailable: {e}")
