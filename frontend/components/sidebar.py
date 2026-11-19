"""Sidebar component for user profile display, idle timer status, and session controls."""
from __future__ import annotations

import datetime
import time

import streamlit as st

from clients.banking_client import BankingAPIError
from state.session import (
    DEFAULT_TIMEOUT_MINUTES,
    check_idle_timeout,
    get_access_token,
    get_banking_client,
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
                    time.sleep(0.3)
                    st.rerun()

            # PIN management in sidebar
            with st.expander("🔐 Change Transaction PIN", expanded=False):
                with st.form("sidebar_pin_reset_form", clear_on_submit=True):
                    sb_pwd = st.text_input("Account Password", type="password", key="sb_pin_pwd")
                    sb_new_pin = st.text_input("New PIN (4-6 digits)", type="password", max_chars=6, key="sb_pin_new")
                    sb_conf_pin = st.text_input("Confirm New PIN", type="password", max_chars=6, key="sb_pin_conf")
                    sb_submit = st.form_submit_button("Update PIN", use_container_width=True)

                if sb_submit:
                    if not sb_pwd or not sb_new_pin or not sb_conf_pin:
                        st.error("Please fill in all fields.")
                    elif not sb_new_pin.strip().isdigit() or len(sb_new_pin.strip()) < 4 or len(sb_new_pin.strip()) > 6:
                        st.error("PIN must be 4 to 6 numeric digits.")
                    elif sb_new_pin.strip() != sb_conf_pin.strip():
                        st.error("PINs do not match.")
                    else:
                        try:
                            token = get_access_token()
                            if token:
                                b_client = get_banking_client()
                                res = b_client.set_transaction_pin(
                                    access_token=token,
                                    current_password=sb_pwd,
                                    new_pin=sb_new_pin.strip(),
                                    confirm_pin=sb_conf_pin.strip(),
                                )
                                st.success("Transaction PIN updated successfully!")
                        except BankingAPIError as be:
                            st.error(be.message)
                        except Exception as e:
                            st.error(str(e))

            st.markdown("---")
        else:
            st.info("🔒 You are not currently logged in.")
            st.caption("Please log in or create an account to access banking and AI features.")
            st.markdown("---")
