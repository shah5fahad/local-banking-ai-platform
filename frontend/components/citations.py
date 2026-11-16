"""Citations component for displaying RAG sources and regulatory references."""
from __future__ import annotations

from typing import Any

import streamlit as st


def render_citations(citations: list[dict[str, Any]]) -> None:
    """Render verified regulatory citations from RAG retrieval."""
    if not citations:
        return

    with st.expander(f"📚 Verified Sources & Regulatory Citations ({len(citations)})", expanded=False):
        for idx, cit in enumerate(citations, 1):
            title = cit.get("title") or cit.get("document_name") or f"Document #{idx}"
            section = cit.get("section") or cit.get("page") or ""
            score = cit.get("score")
            excerpt = cit.get("excerpt") or cit.get("snippet") or cit.get("content") or ""

            score_badge = f" *(Relevance: {score:.2f})*" if isinstance(score, (int, float)) else ""
            section_badge = f" — Section: `{section}`" if section else ""

            st.markdown(f"**[{idx}] {title}**{section_badge}{score_badge}")
            if excerpt:
                st.caption(f"> {excerpt.strip()}")
            if idx < len(citations):
                st.markdown("---")
