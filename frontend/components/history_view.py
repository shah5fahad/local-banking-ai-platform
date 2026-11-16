"""Chat history component for listing, searching, renaming, and deleting conversations."""
from __future__ import annotations

import datetime
from typing import Any

import streamlit as st

from clients.ai_client import AIAPIError, AIClient
from components.citations import render_citations
from state.session import get_access_token, get_ai_client


def format_iso_timestamp(ts_str: str | None) -> str:
    """Format an ISO timestamp to a human-readable local time string."""
    if not ts_str:
        return ""
    try:
        dt = datetime.datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
        return dt.strftime("%b %d, %Y • %I:%M %p")
    except Exception:
        return ts_str


def render_conversation_manager() -> None:
    """Render full-featured conversation history manager: list, search, view, rename, delete."""
    token = get_access_token()
    if not token:
        st.warning("Please sign in to view your chat history.")
        return

    ai_client = get_ai_client()

    col_search, col_refresh = st.columns([4, 1])
    with col_search:
        search_query = st.text_input(
            "🔍 Search Conversations",
            placeholder="Search by topic, transfer recipient, account query...",
            help="Filter conversations by keyword in title",
            key="history_search_input",
        ).strip()

    with col_refresh:
        st.write("")
        st.write("")
        if st.button("🔄 Refresh", key="history_refresh_btn", use_container_width=True):
            st.rerun()

    # Fetch conversations with search filter
    try:
        conversations = ai_client.list_conversations(
            access_token=token,
            query=search_query if search_query else None,
            page=1,
            page_size=50,
        )
    except Exception as e:
        st.error(f"Failed to load conversations: {e}")
        return

    if not conversations:
        if search_query:
            st.info(f"No conversations found matching '{search_query}'.")
        else:
            st.info("You don't have any saved conversations yet. Start a chat with the AI Banking Assistant!")
            if st.button("Start New Chat →", key="history_start_chat_btn", type="primary"):
                st.switch_page("pages/1_Chat.py")
        return

    st.caption(f"Showing **{len(conversations)}** conversation(s)")

    for conv in conversations:
        cid = conv.get("id")
        title = conv.get("title") or "Untitled Conversation"
        created_at = format_iso_timestamp(conv.get("created_at"))
        updated_at = format_iso_timestamp(conv.get("updated_at"))
        msg_count = conv.get("message_count", 0)

        with st.container(border=True):
            col_info, col_actions = st.columns([3, 2])

            with col_info:
                st.subheader(f"💬 {title}")
                meta_text = f"📅 Created: `{created_at}`"
                if updated_at and updated_at != created_at:
                    meta_text += f" | 🕒 Updated: `{updated_at}`"
                meta_text += f" | ✉️ `{msg_count}` message(s)"
                st.caption(meta_text)

            with col_actions:
                st.write("")
                btn_c1, btn_c2, btn_c3 = st.columns(3)

                with btn_c1:
                    if st.button("📂 Open", key=f"open_conv_{cid}", use_container_width=True, type="primary"):
                        st.session_state.active_conversation_id = cid
                        # Pre-load messages
                        try:
                            full = ai_client.get_conversation(cid, access_token=token)
                            msgs = full.get("messages", [])
                            st.session_state.chat_messages = [
                                {
                                    "role": m.get("role"),
                                    "content": m.get("content_masked") or m.get("content", ""),
                                    "citations": m.get("citations"),
                                }
                                for m in msgs
                            ]
                        except Exception:
                            st.session_state.chat_messages = []
                        st.session_state.pending_approval = None
                        st.switch_page("pages/1_Chat.py")

                with btn_c2:
                    with st.popover("✏️ Rename", use_container_width=True):
                        st.markdown("**Rename Conversation**")
                        new_title = st.text_input("New Title", value=title, key=f"rename_input_{cid}").strip()
                        if st.button("Save Title", key=f"save_rename_{cid}", type="primary"):
                            if new_title and new_title != title:
                                try:
                                    ai_client.rename_conversation(cid, new_title, access_token=token)
                                    st.success("Renamed!")
                                    st.rerun()
                                except Exception as e:
                                    st.error(f"Rename failed: {e}")
                            else:
                                st.warning("Please enter a new title.")

                with btn_c3:
                    with st.popover("🗑️ Delete", use_container_width=True):
                        st.markdown("**Delete Conversation?**")
                        st.caption("This will delete the conversation and message history.")
                        if st.button("Confirm Delete", key=f"confirm_del_{cid}", type="primary"):
                            try:
                                ai_client.delete_conversation(cid, access_token=token)
                                if st.session_state.get("active_conversation_id") == cid:
                                    st.session_state.active_conversation_id = None
                                    st.session_state.chat_messages = []
                                    st.session_state.pending_approval = None
                                st.success("Conversation deleted.")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Delete failed: {e}")

            # Expandable Message Inspector
            with st.expander("👁️ View Message Transcript", expanded=False):
                try:
                    full_conv = ai_client.get_conversation(cid, access_token=token)
                    messages = full_conv.get("messages", [])
                    if messages:
                        for m in messages:
                            role = m.get("role", "user")
                            content = m.get("content_masked") or m.get("content", "")
                            msg_ts = format_iso_timestamp(m.get("created_at"))
                            citations = m.get("citations")

                            role_badge = "👤 **User**" if role == "user" else "🤖 **Assistant**"
                            st.markdown(f"{role_badge} *({msg_ts})*")
                            st.markdown(content)
                            if citations and isinstance(citations, list):
                                render_citations(citations)
                            st.markdown("---")
                    else:
                        st.caption("No messages recorded in this conversation.")
                except Exception as e:
                    st.caption(f"Could not load messages: {e}")
