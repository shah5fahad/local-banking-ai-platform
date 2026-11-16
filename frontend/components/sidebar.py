"""Sidebar component for user profile display, idle timer status, and session controls."""
from __future__ import annotations

import datetime
import time

import streamlit as st

from state.session import (
    DEFAULT_TIMEOUT_MINUTES,
    check_idle_timeout,
    get_current_roles,
    get_current_user,
    is_authenticated,
    logout_user,
)


def render_sidebar_auth() -> None:
    """Render authentication details, idle status, and session actions in the sidebar."""
    with st.sidebar:
        st.markdown("### 🏦 Local Banking AI")
        st.markdown("---")

        if is_authenticated():
            # Check timeout first
            if check_idle_timeout():
                st.rerun()

            user = get_current_user() or {}
            roles = get_current_roles()

            full_name = user.get("full_name") or "User"
            email = user.get("email") or ""

            st.markdown(f"**👤 {full_name}**")
            if email:
                st.caption(email)

            # Role badges
            badge_html = " ".join([f"`{r}`" for r in roles])
            st.markdown(f"**Roles:** {badge_html}")

            # Idle session info
            last_ts = st.session_state.get("last_activity_ts", time.time())
            elapsed_min = int((time.time() - last_ts) / 60)
            remaining_min = max(0, DEFAULT_TIMEOUT_MINUTES - elapsed_min)

            st.caption(f"⏱️ Session active (idle timeout in ~{remaining_min}m)")

            st.markdown("---")

            col1, col2 = st.columns([1, 1])
            with col1:
                if st.button("🚪 Logout", key="sidebar_logout_btn", use_container_width=True):
                    logout_user(notify_backend=True)
                    st.success("Logged out.")
                    st.rerun()

            st.markdown("---")
        else:
            st.info("🔒 You are not currently logged in.")
            st.caption("Please log in or create an account to access banking and AI features.")
            st.markdown("---")
