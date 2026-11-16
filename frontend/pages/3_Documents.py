"""Regulatory Documents & Knowledge Base page (Admin / Auditor only)."""
from __future__ import annotations

import streamlit as st

from components.document_manager import render_document_manager
from components.sidebar import render_sidebar_auth
from state.session import require_roles

st.set_page_config(page_title="Documents - Local Banking", page_icon="📚", layout="wide")

# Route guard: requires ADMIN or AUDITOR role
require_roles("ADMIN", "AUDITOR")

# Render auth profile and controls in sidebar
render_sidebar_auth()

st.title("📚 Regulatory Documents & Knowledge Base")
st.markdown("Upload regulatory circulars and manage documents indexed into the ChromaDB Vector Store.")

render_document_manager()
