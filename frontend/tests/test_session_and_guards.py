"""Unit tests for frontend session management, idle timeout, and route guards (T6.1)."""
from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest
import streamlit as st
from streamlit.runtime.scriptrunner.script_runner import StopException

from clients.banking_client import BankingClient
from state.session import (
    check_idle_timeout,
    get_access_token,
    get_current_roles,
    get_current_user,
    has_role,
    init_session,
    is_authenticated,
    login_user,
    logout_user,
    refresh_access_token_if_needed,
    require_auth,
    require_roles,
)


@pytest.fixture(autouse=True)
def clean_session_state(monkeypatch: pytest.MonkeyPatch):
    """Reset streamlit session state and patch st.stop to raise StopException."""
    monkeypatch.setattr(st, "stop", MagicMock(side_effect=StopException))
    for key in list(st.session_state.keys()):
        del st.session_state[key]
    init_session()
    yield
    for key in list(st.session_state.keys()):
        del st.session_state[key]


class TestSessionHandling:
    def test_init_session_defaults(self) -> None:
        init_session()
        assert st.session_state.authenticated is False
        assert st.session_state.user is None
        assert st.session_state.access_token is None
        assert st.session_state.refresh_token is None
        assert st.session_state.roles == []
        assert st.session_state.timed_out is False
        assert isinstance(st.session_state.last_activity_ts, float)

    def test_login_user_stores_tokens_in_memory_only(self) -> None:
        tokens = {
            "access_token": "secret_jwt_access_token_xyz",
            "refresh_token": "secret_jwt_refresh_token_abc",
        }
        profile = {
            "id": "usr-123",
            "email": "user@bank.local",
            "full_name": "Test Customer",
            "roles": ["CUSTOMER"],
        }
        login_user(tokens, user_profile=profile)

        assert is_authenticated() is True
        assert get_access_token() == "secret_jwt_access_token_xyz"
        assert st.session_state.refresh_token == "secret_jwt_refresh_token_abc"
        assert get_current_user() == profile
        assert get_current_roles() == ["CUSTOMER"]
        assert has_role("CUSTOMER") is True
        assert has_role("ADMIN") is False

        # Security invariant: verify tokens are stored in server-side session_state
        assert "access_token" in st.session_state
        assert "query_params" not in st.session_state

    def test_logout_user_clears_all_sensitive_data(self) -> None:
        tokens = {"access_token": "tok1", "refresh_token": "tok2"}
        profile = {"email": "test@bank.local", "roles": ["ADMIN"]}
        login_user(tokens, user_profile=profile)
        assert is_authenticated() is True

        logout_user(notify_backend=False)
        assert is_authenticated() is False
        assert get_access_token() is None
        assert st.session_state.refresh_token is None
        assert get_current_user() is None
        assert get_current_roles() == []


class TestIdleTimeout:
    def test_active_session_does_not_timeout(self) -> None:
        login_user({"access_token": "tok", "refresh_token": "ref"}, {"roles": ["CUSTOMER"]})
        assert is_authenticated() is True

        # Simulate interaction 5 minutes later (less than 15-minute threshold)
        st.session_state.last_activity_ts = time.time() - (5 * 60)
        timed_out = check_idle_timeout(timeout_minutes=15)

        assert timed_out is False
        assert is_authenticated() is True
        # Activity timestamp should have been updated
        assert time.time() - st.session_state.last_activity_ts < 2

    def test_inactive_session_exceeding_15_minutes_times_out(self) -> None:
        login_user({"access_token": "tok", "refresh_token": "ref"}, {"roles": ["CUSTOMER"]})
        assert is_authenticated() is True

        # Simulate inactivity of 16 minutes (> 15 minutes)
        st.session_state.last_activity_ts = time.time() - (16 * 60)
        timed_out = check_idle_timeout(timeout_minutes=15)

        assert timed_out is True
        assert st.session_state.timed_out is True
        assert is_authenticated() is False
        assert get_access_token() is None

    def test_check_idle_timeout_noop_when_unauthenticated(self) -> None:
        assert is_authenticated() is False
        timed_out = check_idle_timeout(timeout_minutes=15)
        assert timed_out is False


class TestRouteGuards:
    def test_require_auth_passes_when_authenticated(self) -> None:
        login_user({"access_token": "tok", "refresh_token": "ref"}, {"roles": ["CUSTOMER"]})
        # Should execute without throwing StopException
        require_auth()

    def test_require_auth_stops_when_not_authenticated(self) -> None:
        assert is_authenticated() is False
        with pytest.raises(StopException):
            require_auth()

    def test_require_auth_stops_when_timed_out(self) -> None:
        login_user({"access_token": "tok", "refresh_token": "ref"}, {"roles": ["CUSTOMER"]})
        st.session_state.timed_out = True
        with pytest.raises(StopException):
            require_auth()

    def test_require_roles_allows_matching_role(self) -> None:
        login_user({"access_token": "tok", "refresh_token": "ref"}, {"roles": ["ADMIN"]})
        # Admin accessing admin page should succeed
        require_roles("ADMIN")
        # Admin accessing customer page should succeed
        require_roles("CUSTOMER", "ADMIN")

    def test_require_roles_rejects_missing_role(self) -> None:
        login_user({"access_token": "tok", "refresh_token": "ref"}, {"roles": ["CUSTOMER"]})
        # Customer trying to access Admin page must be stopped (403 Forbidden)
        with pytest.raises(StopException):
            require_roles("ADMIN")

    def test_require_roles_allows_any_matching_allowed_role(self) -> None:
        login_user({"access_token": "tok", "refresh_token": "ref"}, {"roles": ["AUDITOR"]})
        # Documents page allows ADMIN or AUDITOR
        require_roles("ADMIN", "AUDITOR")
