"""Chat with AI Banking Assistant page featuring SSE streaming, tool status, approval cards, PIN dialog, and citations."""
from __future__ import annotations

import uuid
from typing import Any

import httpx
import streamlit as st

from components.approval_card import render_approval_card
from components.citations import render_citations
from components.pin_dialog import render_pin_modal_dialog
from components.sidebar import render_sidebar_auth
from state.session import get_access_token, get_ai_client, require_auth

st.set_page_config(page_title="AI Chat - Local Banking", page_icon="💬", layout="wide")

# 1. Route guard: ensure user is authenticated
require_auth()

# 2. Render user profile & logout in sidebar
render_sidebar_auth()

token = get_access_token()
ai_client = get_ai_client()

# 3. Initialize chat session state
if "active_conversation_id" not in st.session_state:
    st.session_state.active_conversation_id = None
if "chat_messages" not in st.session_state:
    st.session_state.chat_messages = []
if "pending_approval" not in st.session_state:
    st.session_state.pending_approval = None

# Sidebar Conversation Management
with st.sidebar:
    st.markdown("### 💬 Conversations")
    col_new, col_hist = st.columns([1, 1])
    with col_new:
        if st.button("➕ New Chat", use_container_width=True, key="btn_new_chat"):
            st.session_state.active_conversation_id = None
            st.session_state.chat_messages = []
            st.session_state.pending_approval = None
            st.rerun()
    with col_hist:
        if st.button("📜 History", use_container_width=True, key="btn_goto_history"):
            st.switch_page("pages/2_History.py")

    search_kw = st.text_input(
        "🔍 Search chats",
        placeholder="Filter by title...",
        key="sidebar_search_kw",
        label_visibility="collapsed",
    ).strip()

    # List recent user conversations from AI backend
    if token:
        try:
            recent_convs = ai_client.list_conversations(
                access_token=token,
                query=search_kw if search_kw else None,
                page=1,
                page_size=15,
            )
            if recent_convs:
                st.caption("Recent chats:")
                for c in recent_convs:
                    cid = c.get("id")
                    title = c.get("title") or f"Chat {cid[:8]}"
                    is_current = cid == st.session_state.active_conversation_id
                    btn_label = f"▸ {title}" if is_current else title
                    if st.button(btn_label, key=f"conv_btn_{cid}", use_container_width=True):
                        st.session_state.active_conversation_id = cid
                        # Load conversation messages
                        try:
                            full_conv = ai_client.get_conversation(cid, access_token=token)
                            msgs = full_conv.get("messages", [])
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
                        st.rerun()
            elif search_kw:
                st.caption(f"No chats matching '{search_kw}'")
        except Exception:
            pass

    st.markdown("---")

# Main Page Header & Active Conversation Controls
col_title, col_ctrl = st.columns([4, 1.5])
with col_title:
    current_cid = st.session_state.active_conversation_id
    if current_cid:
        # Look up current title if available
        active_title = "Active Conversation"
        try:
            cur_conv = ai_client.get_conversation(current_cid, access_token=token)
            active_title = cur_conv.get("title") or active_title
        except Exception:
            pass
        st.title(f"💬 {active_title}")
    else:
        st.title("💬 AI Banking Assistant")

with col_ctrl:
    if st.session_state.active_conversation_id:
        st.write("")
        st.write("")
        ctrl_c1, ctrl_c2 = st.columns(2)
        with ctrl_c1:
            with st.popover("✏️ Rename", use_container_width=True):
                st.caption("Change conversation title")
                edit_t = st.text_input("Title", value=active_title, key="header_rename_val").strip()
                if st.button("Save", key="header_save_title", type="primary"):
                    if edit_t and edit_t != active_title:
                        try:
                            ai_client.rename_conversation(current_cid, edit_t, access_token=token)
                            st.success("Renamed!")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error: {e}")
        with ctrl_c2:
            with st.popover("🗑️ Delete", use_container_width=True):
                st.caption("Delete this chat?")
                if st.button("Confirm", key="header_confirm_del", type="primary"):
                    try:
                        ai_client.delete_conversation(current_cid, access_token=token)
                        st.session_state.active_conversation_id = None
                        st.session_state.chat_messages = []
                        st.session_state.pending_approval = None
                        st.success("Deleted!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error: {e}")

st.caption(
    "Private, on-premise banking assistant. Ask balance inquiries, request fund transfers, "
    "explore loan eligibility, pay credit cards, or research regulatory policies."
)

# Check for active pending approval for the current conversation
if token and st.session_state.active_conversation_id and not st.session_state.pending_approval:
    try:
        active_appr = ai_client.get_active_approval(
            conversation_id=st.session_state.active_conversation_id,
            access_token=token,
        )
        if active_appr and active_appr.get("status") in ("PENDING", "CONFIRMED", "AUTH_REQUIRED"):
            st.session_state.pending_approval = active_appr
    except Exception:
        pass

# Render Chat History
for msg in st.session_state.chat_messages:
    role = msg.get("role", "user")
    content = msg.get("content", "")
    citations = msg.get("citations")

    with st.chat_message(role):
        st.markdown(content)
        if citations and isinstance(citations, list):
            render_citations(citations)
            
# Render Active Approval Card if one exists
if st.session_state.pending_approval:
    st.markdown("### ⚠️ Action Required: Pending Approval")
    render_approval_card(st.session_state.pending_approval)

# Handle Chat Input & Streaming Response
user_prompt = st.chat_input("Type your message or banking instruction...")

if user_prompt:
    # Append user prompt immediately
    st.session_state.chat_messages.append({"role": "user", "content": user_prompt})
    with st.chat_message("user"):
        st.markdown(user_prompt)

    # Stream assistant response
    with st.chat_message("assistant"):
        stream_placeholder = st.empty()
        full_response = ""
        citations_collected: list[dict[str, Any]] = []

        # Tool execution status box
        with st.status("🧠 Processing your request...", expanded=True) as status_box:
            try:
                event_stream = ai_client.stream_message(
                    message=user_prompt,
                    conversation_id=st.session_state.active_conversation_id,
                    access_token=token or "",
                )

                for event in event_stream:
                    evt_type = event.get("event")
                    evt_data = event.get("data")

                    if evt_type == "status":
                        status_label = evt_data.get("status", "running")
                        node_label = evt_data.get("node") or evt_data.get("route") or ""
                        intent = evt_data.get("intent")

                        if status_label == "classified":
                            status_box.write(f"🧭 Intent identified: **{intent or 'banking'}** (Route: `{node_label}`)")
                        elif status_label == "researching":
                            status_box.write(f"📖 Researching banking guidelines ({node_label})...")
                        else:
                            status_box.write(f"⚙️ Node active: `{node_label or status_label}`")

                    elif evt_type == "tool":
                        tool_name = evt_data.get("tool", "tool")
                        is_success = evt_data.get("success", True)
                        status_icon = "✅" if is_success else "❌"
                        status_box.write(f"{status_icon} Executed Banking tool: `{tool_name}`")

                    elif evt_type == "citations":
                        raw_cits = evt_data.get("citations") or []
                        if isinstance(raw_cits, list):
                            citations_collected = raw_cits
                            status_box.write(f"📚 Grounded with {len(citations_collected)} regulatory reference(s)")

                    elif evt_type == "approval_required":
                        status_box.update(
                            label="⚠️ Human Approval Required",
                            state="running",
                            expanded=False,
                        )
                        st.session_state.pending_approval = evt_data

                    elif evt_type == "token":
                        token_chunk = evt_data.get("token", "")
                        full_response += token_chunk
                        stream_placeholder.markdown(full_response + "▌")

                    elif evt_type == "done":
                        conv_id = evt_data.get("conversation_id")
                        if conv_id:
                            st.session_state.active_conversation_id = conv_id
                        status_box.update(
                            label="Response complete",
                            state="complete",
                            expanded=False,
                        )

                    elif evt_type == "error":
                        err_msg = evt_data.get("message") or str(evt_data)
                        status_box.update(label="Execution error", state="error", expanded=True)
                        st.error(f"Error during assistant processing: {err_msg}")

                # Finalize streamed text display without cursor
                stream_placeholder.markdown(full_response)

                # Render citations if any were collected
                if citations_collected:
                    render_citations(citations_collected)

                # Save message to state
                st.session_state.chat_messages.append(
                    {
                        "role": "assistant",
                        "content": full_response,
                        "citations": citations_collected,
                    }
                )

                # If an approval was triggered in this turn, trigger rerun so Approval Card renders immediately
                if st.session_state.pending_approval:
                    st.rerun()

            except httpx.TimeoutException:
                status_box.update(label="Connection timeout", state="error", expanded=True)
                st.error("Failed to communicate with AI Chat service: Request timed out. The upstream AI model or service took too long to respond. Please check your model settings and provider quota.")
            except Exception as e:
                status_box.update(label="Connection error", state="error", expanded=True)
                st.error(f"Failed to communicate with AI Chat service: {e}")
