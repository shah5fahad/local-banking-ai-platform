"""History page for managing previous chat conversations and viewing records."""
from __future__ import annotations

import streamlit as st

from components.history_view import render_conversation_manager
from components.sidebar import render_sidebar_auth
from state.session import require_auth

st.set_page_config(page_title="History - Local Banking", page_icon="📜", layout="wide")

# 1. Route guard: requires authentication
require_auth()

# 2. Render user profile & logout in sidebar
render_sidebar_auth()

st.title("📜 History & Past Records")
st.markdown("Browse, search, rename, and manage your conversation history.")

tab_chats, tab_info = st.tabs(["💬 Chat Conversations", "ℹ️ Data Privacy & Retention"])

with tab_chats:
    render_conversation_manager()

with tab_info:
    st.subheader("Data Privacy & User Isolation Policy")
    st.markdown(
        "- **User Ownership Isolation:** All conversations and message histories are strictly filtered by your user ID. "
        "Other bank customers and non-admin users cannot view or search your conversations.\n"
        "- **Credential & PIN Scrubbing:** Sensitive credentials, passwords, and transaction PINs are never stored "
        "in conversation history or database checkpoint records.\n"
        "- **Masked Logs:** Account numbers, card numbers, and PII are masked (`[MASKED]`) in all stored messages.\n"
        "- **Deletion:** Deleting a conversation permanently marks it as soft-deleted and removes it from active views."
    )
