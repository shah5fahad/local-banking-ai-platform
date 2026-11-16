"""Direct Banking page: accounts, beneficiaries, and transaction history (T6.6)."""
from __future__ import annotations

import streamlit as st

from components.direct_banking import render_direct_banking
from components.sidebar import render_sidebar_auth
from state.session import require_auth

st.set_page_config(
    page_title="Direct Banking - Local Banking",
    page_icon="🏦",
    layout="wide",
)

# Route guard: requires authenticated session
require_auth()

# Render auth profile and controls in sidebar
render_sidebar_auth()

st.title("🏦 Direct Banking Services")
st.markdown("Manage your linked bank accounts, transfer beneficiaries, and personal transaction records.")

render_direct_banking()
