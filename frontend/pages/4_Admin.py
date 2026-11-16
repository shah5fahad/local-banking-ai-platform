"""Admin Controls & System Configuration page (Admin and Auditor)."""
from __future__ import annotations

import streamlit as st

from components.admin_dashboard import render_admin_dashboard
from components.sidebar import render_sidebar_auth
from state.session import require_roles

st.set_page_config(page_title="Admin Controls - Local Banking", page_icon="🛠️", layout="wide")

# Route guard: requires ADMIN or AUDITOR role
require_roles("ADMIN", "AUDITOR")

# Render auth profile and controls in sidebar
render_sidebar_auth()

st.title("🛠️ Administration & System Controls")
st.markdown("User management, role assignment, platform transactions, masked chat auditing, and system limits.")

render_admin_dashboard()
