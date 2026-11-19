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


def _is_testing() -> bool:
    """Return True if running inside an automated test harness (e.g. pytest or AppTest)."""
    try:
        from streamlit.runtime.scriptrunner_utils.script_run_context import get_script_run_ctx
        ctx = get_script_run_ctx()
        if ctx and "test" in getattr(ctx, "session_id", "").lower():
            return True
    except Exception:
        pass
    return False


def get_cookie_controller() -> Any | None:
    """Safely retrieve or initialize CookieController singleton when running in browser."""
    if _is_testing():
        return None
    try:
        from streamlit_cookies_controller import CookieController
        if "cookie_controller" not in st.session_state:
            st.session_state.cookie_controller = CookieController()
        return st.session_state.cookie_controller
    except Exception:
        return None


def get_cookie(name: str) -> str | None:
    """Retrieve a cookie value by name from st.context or CookieController."""
    # 1. Native Streamlit 1.35+ context cookies (immediate, available on initial request / refresh)
    try:
        if hasattr(st, "context") and hasattr(st.context, "cookies"):
            val = st.context.cookies.get(name)
            if isinstance(val, str) and val.strip():
                return val.strip()
    except Exception:
        pass

    # 2. CookieController component fallback (only if already initialized)
    try:
        if "cookie_controller" in st.session_state and st.session_state.cookie_controller is not None:
            val = st.session_state.cookie_controller.get(name)
            if isinstance(val, str) and val.strip():
                return val.strip()
    except Exception:
        pass

    return None


def set_cookie(name: str, value: str, max_age: int = 7 * 24 * 3600) -> None:
    """Set a cookie in the client browser with path=/ and SameSite=Lax."""
    # Set via CookieController component
    try:
        controller = get_cookie_controller()
        if controller:
            controller.set(
                name=name,
                value=value,
                path="/",
                max_age=max_age,
                same_site="lax",
            )
    except Exception:
        pass

    # Also inject client-side script for immediate document.cookie persistence
    try:
        js = (
            f"<script>(function(){{"
            f"document.cookie = '{name}=' + encodeURIComponent('{value}') + '; path=/; max-age={max_age}; SameSite=Lax';"
            f"}})();</script>"
        )
        st.html(js, unsafe_allow_javascript=True)
    except Exception:
        pass


def delete_cookie(name: str) -> None:
    """Remove a cookie from the client browser."""
    # Remove via CookieController component
    try:
        controller = get_cookie_controller()
        if controller:
            controller.remove(name=name, path="/", same_site="lax")
    except Exception:
        pass

    # Also expire via client-side script
    try:
        js = (
            f"<script>(function(){{"
            f"document.cookie = '{name}=; path=/; max-age=0; expires=Thu, 01 Jan 1970 00:00:00 GMT; SameSite=Lax';"
            f"}})();</script>"
        )
        st.html(js, unsafe_allow_javascript=True)
    except Exception:
        pass


def restore_session_from_cookies() -> bool:
    """Attempt to restore user authentication session from browser cookies on page refresh."""
    token = get_cookie("access_token")
    refresh_token = get_cookie("refresh_token")

    if not token and not refresh_token:
        return False

    # Check idle timeout based on session_last_activity cookie
    last_act_str = get_cookie("session_last_activity")
    if last_act_str:
        try:
            last_act = float(last_act_str)
            if time.time() - last_act > DEFAULT_TIMEOUT_MINUTES * 60:
                st.session_state.timed_out = True
                logout_user(notify_backend=False)
                return False
        except (ValueError, TypeError):
            pass

    client = get_banking_client()
    user_profile = None

    if token:
        try:
            user_profile = client.get_me(token)
        except Exception:
            user_profile = None

    # If access token has expired or failed, try rotating via refresh token
    if not user_profile and refresh_token:
        try:
            new_tokens = client.refresh(refresh_token)
            token = new_tokens.get("access_token")
            refresh_token = new_tokens.get("refresh_token")
            if token:
                user_profile = client.get_me(token)
                set_cookie("access_token", token)
                if refresh_token:
                    set_cookie("refresh_token", refresh_token)
        except Exception:
            token = None
            refresh_token = None
            user_profile = None

    if user_profile and token:
        st.session_state.access_token = token
        st.session_state.refresh_token = refresh_token
        st.session_state.authenticated = True
        st.session_state.timed_out = False
        st.session_state.last_activity_ts = time.time()
        st.session_state.user = user_profile
        roles = user_profile.get("roles", ["CUSTOMER"])
        st.session_state.roles = roles if isinstance(roles, list) else ["CUSTOMER"]
        set_cookie("session_last_activity", str(time.time()))
        return True

    # Tokens are invalid/revoked; clean up cookies
    delete_cookie("access_token")
    delete_cookie("refresh_token")
    delete_cookie("session_last_activity")
    return False


def init_session() -> None:
    """Initialize session state keys with secure defaults if not present and restore from cookies."""
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

    # If unauthenticated, attempt to restore session from cookies
    if not st.session_state.authenticated and not st.session_state.timed_out:
        restore_session_from_cookies()


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
    """Update session state upon successful authentication and persist tokens in cookies."""
    init_session()
    access_token = tokens.get("access_token")
    refresh_token = tokens.get("refresh_token")

    st.session_state.access_token = access_token
    st.session_state.refresh_token = refresh_token
    st.session_state.authenticated = True
    st.session_state.timed_out = False
    now_ts = time.time()
    st.session_state.last_activity_ts = now_ts

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

    # Persist in cookies so session survives page refresh
    if access_token:
        set_cookie("access_token", access_token)
    if refresh_token:
        set_cookie("refresh_token", refresh_token)
    set_cookie("session_last_activity", str(now_ts))


def logout_user(notify_backend: bool = True) -> None:
    """Revoke tokens, clear server session state, and delete cookies."""
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

    delete_cookie("access_token")
    delete_cookie("refresh_token")
    delete_cookie("session_last_activity")


def check_idle_timeout(timeout_minutes: int = DEFAULT_TIMEOUT_MINUTES) -> bool:
    """Enforce idle timeout policy (default 15 minutes of inactivity).
    
    Returns True if session timed out and was terminated, False otherwise.
    """
    if not st.session_state.get("authenticated", False):
        return False

    timeout_seconds = timeout_minutes * 60
    elapsed = time.time() - st.session_state.get("last_activity_ts", time.time())

    if elapsed > timeout_seconds:
        st.session_state.timed_out = True
        logout_user(notify_backend=False)
        return True

    # Update activity timestamp on valid interaction
    now_ts = time.time()
    st.session_state.last_activity_ts = now_ts
    set_cookie("session_last_activity", str(now_ts))
    return False


def refresh_access_token_if_needed() -> bool:
    """Attempt refresh token rotation using stored refresh token."""
    init_session()
    refresh_token = st.session_state.get("refresh_token") or get_cookie("refresh_token")
    if not refresh_token:
        return False

    try:
        client = get_banking_client()
        new_tokens = client.refresh(refresh_token)
        acc = new_tokens.get("access_token")
        ref = new_tokens.get("refresh_token")
        st.session_state.access_token = acc
        st.session_state.refresh_token = ref
        now_ts = time.time()
        st.session_state.last_activity_ts = now_ts
        if acc:
            set_cookie("access_token", acc)
        if ref:
            set_cookie("refresh_token", ref)
        set_cookie("session_last_activity", str(now_ts))
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
