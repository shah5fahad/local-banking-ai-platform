"""Session state management, idle timeout enforcement, and route guards for Streamlit."""
from __future__ import annotations

import os
import time
from typing import Any

import streamlit as st

from clients.ai_client import AIAPIError, AIClient
from clients.banking_client import BankingAPIError, BankingClient

DEFAULT_TIMEOUT_MINUTES = int(os.environ.get("SESSION_IDLE_TIMEOUT_MINUTES", "15"))


def get_banking_client() -> BankingClient:
    """Retrieve or initialize the singleton BankingClient in session state."""
    if "banking_client" not in st.session_state:
        st.session_state.banking_client = BankingClient()
    return st.session_state.banking_client


def get_ai_client() -> AIClient:
    """Retrieve or initialize the singleton AIClient in session state."""
    if "ai_client" not in st.session_state:
        st.session_state.ai_client = AIClient()
    return st.session_state.ai_client


def init_session() -> None:
    """Initialize session state keys with secure defaults if not present."""
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    if "user" not in st.session_state:
        st.session_state.user = None
    if "access_token" not in st.session_state:
        st.session_state.access_token = None
    if "refresh_token" not in st.session_state:
        st.session_state.refresh_token = None
    if "roles" not in st.session_state:
        st.session_state.roles = []
    if "last_activity_ts" not in st.session_state:
        st.session_state.last_activity_ts = time.time()
    if "timed_out" not in st.session_state:
        st.session_state.timed_out = False


def is_authenticated() -> bool:
    """Check if a user is currently authenticated."""
    init_session()
    return bool(st.session_state.get("authenticated", False))


def get_current_user() -> dict[str, Any] | None:
    """Return user profile dict if authenticated, else None."""
    init_session()
    return st.session_state.get("user")


def get_current_roles() -> list[str]:
    """Return list of roles assigned to current user."""
    init_session()
    return st.session_state.get("roles", [])


def has_role(*allowed_roles: str) -> bool:
    """Check if the current user possesses at least one of the allowed roles."""
    roles = get_current_roles()
    return any(r in roles for r in allowed_roles)


def get_access_token() -> str | None:
    """Return current JWT access token or None."""
    init_session()
    return st.session_state.get("access_token")


def login_user(
    tokens: dict[str, Any],
    user_profile: dict[str, Any] | None = None,
) -> None:
    """Update session state upon successful authentication.
    
    Tokens are stored server-side in st.session_state only, satisfying the security invariant.
    """
    init_session()
    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")

    st.session_state.access_token = access_token
    st.session_state.refresh_token = refresh_token
    st.session_state.authenticated = True
    st.session_state.timed_out = False
    st.session_state.last_activity_ts = time.time()

    client = get_banking_client()
    if user_profile is None and access_token:
        try:
            user_profile = client.get_me(access_token)
        except Exception:
            user_profile = {}

    if user_profile:
        st.session_state.user = user_profile
        roles = user_profile.get("roles", ["CUSTOMER"])
        st.session_state.roles = roles if isinstance(roles, list) else ["CUSTOMER"]
    else:
        st.session_state.user = {"email": "user"}
        st.session_state.roles = ["CUSTOMER"]


def logout_user(notify_backend: bool = True) -> None:
    """Revoke tokens, clear server session state, and mark as logged out."""
    init_session()
    token = st.session_state.get("access_token")
    if notify_backend and token:
        try:
            client = get_banking_client()
            client.logout(token)
        except Exception:
            pass

    st.session_state.authenticated = False
    st.session_state.user = None
    st.session_state.access_token = None
    st.session_state.refresh_token = None
    st.session_state.roles = []
    st.session_state.last_activity_ts = 0.0


def check_idle_timeout(timeout_minutes: int = DEFAULT_TIMEOUT_MINUTES) -> bool:
    """Enforce idle timeout policy (default 15 minutes of inactivity).
    
    Returns True if session timed out and was terminated, False otherwise.
    """
    init_session()
    if not st.session_state.authenticated:
        return False

    timeout_seconds = timeout_minutes * 60
    elapsed = time.time() - st.session_state.last_activity_ts

    if elapsed > timeout_seconds:
        st.session_state.timed_out = True
        logout_user(notify_backend=False)
        return True

    # Update activity timestamp on valid interaction
    st.session_state.last_activity_ts = time.time()
    return False


def refresh_access_token_if_needed() -> bool:
    """Attempt refresh token rotation using stored refresh token."""
    init_session()
    refresh_token = st.session_state.get("refresh_token")
    if not refresh_token:
        return False

    try:
        client = get_banking_client()
        new_tokens = client.refresh(refresh_token)
        st.session_state.access_token = new_tokens.get("access_token")
        st.session_state.refresh_token = new_tokens.get("refresh_token")
        st.session_state.last_activity_ts = time.time()
        return True
    except BankingAPIError:
        logout_user(notify_backend=False)
        return False


def require_auth() -> None:
    """Route guard ensuring the current user is authenticated.
    
    If unauthenticated or timed out, displays a message and halts further page execution.
    """
    init_session()
    timed_out = check_idle_timeout()

    if timed_out or st.session_state.get("timed_out"):
        st.error("⏳ **Session Expired:** You have been logged out due to 15 minutes of inactivity. Please log in again to continue.")
        if st.button("Go to Login", key="guard_login_btn"):
            st.session_state.timed_out = False
            st.switch_page("app.py")
        st.stop()

    if not st.session_state.authenticated:
        st.warning("🔒 **Authentication Required:** You must be logged in to view this page.")
        if st.button("Log In / Register", key="guard_unauth_btn"):
            st.switch_page("app.py")
        st.stop()


def require_roles(*allowed_roles: str) -> None:
    """Route guard ensuring the user is authenticated AND possesses one of allowed_roles."""
    require_auth()

    if not has_role(*allowed_roles):
        st.error(
            f"🚫 **Access Denied (403 Forbidden):** This page requires one of the following roles: "
            f"`{', '.join(allowed_roles)}`. Your assigned roles: `{', '.join(get_current_roles())}`."
        )
        st.info("Please contact your system administrator if you believe this is an error.")
        st.stop()
