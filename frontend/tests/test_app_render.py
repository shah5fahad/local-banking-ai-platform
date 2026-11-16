"""Test Streamlit AppTest rendering of app.py."""
from __future__ import annotations

import os
from streamlit.testing.v1 import AppTest


def test_app_unauthenticated_render() -> None:
    """Ensure app.py boots up and renders login and register tabs cleanly."""
    at = AppTest.from_file("../app.py", default_timeout=10)
    at.run()
    assert not at.exception
    # Should render title and tabs
    assert len(at.title) >= 1
    assert "Local Banking AI Platform" in at.title[0].value
    # Check tabs exist
    assert len(at.tabs) >= 2


def test_app_authenticated_render() -> None:
    """Ensure app.py renders dashboard when authenticated in session state."""
    at = AppTest.from_file("../app.py", default_timeout=10)
    # Seed session state
    at.session_state["authenticated"] = True
    at.session_state["user"] = {
        "id": "u-123",
        "full_name": "Alice Smith",
        "email": "alice@bank.local",
        "roles": ["CUSTOMER"],
    }
    at.session_state["roles"] = ["CUSTOMER"]
    at.session_state["access_token"] = "mock_token"
    at.run()
    assert not at.exception
    # Welcome message with user name
    assert any("Alice Smith" in t.value for t in at.title)
    # Check navigation buttons exist
    button_labels = [b.label for b in at.button]
    assert any("Open AI Chat" in lbl for lbl in button_labels)
    assert any("View History" in lbl for lbl in button_labels)
