"""Document management component for Regulatory Knowledge Base (T6.4)."""
from __future__ import annotations

import datetime
from typing import Any

import streamlit as st

from clients.ai_client import AIAPIError, AIClient
from components.history_view import format_iso_timestamp
from state.session import get_access_token, get_ai_client, has_role


def format_bytes(size: int | None) -> str:
    """Format file size in bytes to human-readable string (KB, MB, GB)."""
    if size is None or size == 0:
        return "0 B"
    num = float(size)
    for unit in ["B", "KB", "MB", "GB"]:
        if abs(num) < 1024.0:
            return f"{num:3.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} TB"


def render_document_uploader(ai_client: AIClient, access_token: str, is_admin: bool) -> None:
    """Render upload form for submitting new policy or regulatory documents."""
    st.subheader("⬆️ Upload Regulatory / Policy Document")
    st.markdown(
        "Upload regulatory circulars, compliance guidelines, or internal policy documents. "
        "Upon upload, documents are parsed, chunked, and embedded into the ChromaDB vector store "
        "for contextual retrieval by the Banking AI assistant."
    )

    if not is_admin:
        st.warning(
            "🔒 **Read-Only Mode**: Uploading new documents is restricted to administrators. "
            "Auditors may view documents, inspect chunks, and trace versions in the library."
        )
        return

    with st.form("doc_upload_form", clear_on_submit=False):
        uploaded_file = st.file_uploader(
            "Select Document File",
            type=["pdf", "docx", "txt"],
            help="Supported file types: PDF, Word (DOCX), plain text (TXT). Maximum size: 25 MB.",
            key="doc_file_uploader",
        )

        col_name, col_cat = st.columns([2, 1])
        with col_name:
            default_name = uploaded_file.name if uploaded_file else ""
            doc_name = st.text_input(
                "Document Title / Name *",
                value=default_name,
                placeholder="e.g., Master Circular - Customer Service in Banks",
                key="doc_name_input",
            )
        with col_cat:
            category = st.selectbox(
                "Category *",
                options=["REGULATORY", "CIRCULAR", "POLICY", "INTERNAL"],
                index=0,
                key="doc_category_input",
            )

        col_ver, col_group = st.columns([1, 2])
        with col_ver:
            version = st.text_input(
                "Version *",
                value="1.0",
                placeholder="1.0, 2.0, 2026-Q1...",
                key="doc_version_input",
            )
        with col_group:
            doc_group_id = st.text_input(
                "Document Group ID (optional)",
                placeholder="Leave blank for new document group, or paste existing group ID",
                help="Group ID groups related revisions. When a new version is activated, older versions in the group are superseded.",
                key="doc_group_id_input",
            )

        submitted = st.form_submit_button("Upload & Ingest Document", type="primary", use_container_width=True)

    if submitted:
        if not uploaded_file:
            st.error("Please select a document file (.pdf, .docx, .txt) to upload.")
            return
        if not doc_name.strip():
            st.error("Document title / name is required.")
            return
        if not version.strip():
            st.error("Document version string is required.")
            return

        try:
            with st.spinner("Uploading and queueing document ingestion pipeline..."):
                file_bytes = uploaded_file.getvalue()
                res = ai_client.upload_document(
                    file_bytes=file_bytes,
                    filename=uploaded_file.name,
                    name=doc_name.strip(),
                    category=category,
                    version=version.strip(),
                    access_token=access_token,
                    doc_group_id=doc_group_id.strip() if doc_group_id and doc_group_id.strip() else None,
                )
            st.success(
                f"✅ Document **{res.get('name')}** (v{res.get('version')}) uploaded successfully! "
                f"Status: `{res.get('status')}`. Ingestion pipeline has been scheduled."
            )
            st.info("Tip: Switch to the **Document Library** tab to monitor processing status and chunk indexing.")
        except AIAPIError as err:
            st.error(f"Upload failed: {err.message} (HTTP {err.status_code})")
        except Exception as exc:
            st.error(f"Unexpected error during upload: {exc}")


def render_document_library(ai_client: AIClient, access_token: str, is_admin: bool) -> None:
    """Render documents table, filtering, status badges, and action controls."""
    st.subheader("📚 Ingested Documents & Knowledge Base")

    # Filter controls
    col_cat, col_status, col_btn = st.columns([2, 2, 1])
    with col_cat:
        cat_filter = st.selectbox(
            "Filter by Category",
            options=["All Categories", "REGULATORY", "CIRCULAR", "POLICY", "INTERNAL"],
            key="lib_cat_filter",
        )
    with col_status:
        status_filter = st.selectbox(
            "Filter by Active Status",
            options=["All Statuses", "Active Only (In RAG)", "Inactive Only"],
            key="lib_status_filter",
        )
    with col_btn:
        st.write("")
        st.write("")
        if st.button("🔄 Refresh", key="lib_refresh_btn", use_container_width=True):
            st.rerun()

    # Determine query params
    api_cat = None if cat_filter == "All Categories" else cat_filter
    api_active = None
    if status_filter == "Active Only (In RAG)":
        api_active = True
    elif status_filter == "Inactive Only":
        api_active = False

    # Fetch documents
    try:
        data = ai_client.list_documents(
            access_token=access_token,
            category=api_cat,
            active=api_active,
            page=1,
            page_size=100,
        )
        items: list[dict[str, Any]] = data.get("items", []) if isinstance(data, dict) else []
        total: int = data.get("total", len(items)) if isinstance(data, dict) else len(items)
    except AIAPIError as err:
        st.error(f"Failed to fetch documents: {err.message} (HTTP {err.status_code})")
        return
    except Exception as exc:
        st.error(f"Unexpected error retrieving documents: {exc}")
        return

    # Metrics summary
    active_count = sum(1 for it in items if it.get("active"))
    col_m1, col_m2, col_m3 = st.columns(3)
    col_m1.metric("Total Documents", total)
    col_m2.metric("Active in RAG", active_count)
    col_m3.metric("Inactive / Superseded", total - active_count)

    st.markdown("---")

    if not items:
        st.info("No documents found matching the selected filters.")
        return

    for doc in items:
        doc_id = doc.get("id", "")
        doc_name = doc.get("name", "Untitled Document")
        doc_cat = doc.get("category", "REGULATORY")
        doc_ver = doc.get("version", "1.0")
        doc_status = doc.get("status", "UNKNOWN")
        is_active = bool(doc.get("active", False))
        size_str = format_bytes(doc.get("size_bytes"))
        uploaded_ts = format_iso_timestamp(doc.get("uploaded_at"))
        group_id = doc.get("doc_group_id", "")

        # Status badge
        if doc_status == "INDEXED":
            status_badge = "🟢 INDEXED"
        elif doc_status == "PROCESSING":
            status_badge = "🔄 PROCESSING"
        elif doc_status == "UPLOADED":
            status_badge = "⏳ UPLOADED"
        elif doc_status == "FAILED":
            status_badge = "🔴 FAILED"
        else:
            status_badge = f"⚪ {doc_status}"

        active_badge = "🟢 Active (In RAG)" if is_active else "⚪ Inactive (Excluded)"

        with st.container(border=True):
            col_info, col_badges = st.columns([3, 2])
            with col_info:
                st.markdown(f"#### 📄 {doc_name}")
                st.caption(
                    f"**Category:** `{doc_cat}` &nbsp;|&nbsp; "
                    f"**Version:** `{doc_ver}` &nbsp;|&nbsp; "
                    f"**Size:** {size_str} &nbsp;|&nbsp; "
                    f"**Uploaded:** {uploaded_ts}"
                )
                st.caption(f"**Doc ID:** `{doc_id}` &nbsp;|&nbsp; **Group ID:** `{group_id}`")
            with col_badges:
                st.markdown(f"**Status:** {status_badge}")
                st.markdown(f"**Retrieval:** {active_badge}")

            # Actions Row
            col_act, col_reproc, col_vers, col_detail, col_del = st.columns(5)

            # 1. Activate / Deactivate Toggle
            with col_act:
                if is_active:
                    if st.button("⚪ Deactivate", key=f"btn_deact_{doc_id}", disabled=not is_admin, use_container_width=True, help="Exclude document from RAG search"):
                        try:
                            ai_client.deactivate_document(doc_id, access_token)
                            st.toast(f"Deactivated {doc_name}", icon="⚪")
                            st.rerun()
                        except AIAPIError as e:
                            st.error(e.message)
                else:
                    if st.button("🟢 Activate", key=f"btn_act_{doc_id}", disabled=not is_admin, use_container_width=True, help="Make active and supersede older versions in group"):
                        try:
                            ai_client.activate_document(doc_id, access_token)
                            st.toast(f"Activated {doc_name} (older versions superseded)", icon="🟢")
                            st.rerun()
                        except AIAPIError as e:
                            st.error(e.message)

            # 2. Reprocess Action
            with col_reproc:
                if st.button("🔄 Reprocess", key=f"btn_reproc_{doc_id}", disabled=not is_admin, use_container_width=True, help="Re-chunk and rebuild vector embeddings"):
                    try:
                        ai_client.reprocess_document(doc_id, access_token)
                        st.toast(f"Reprocessing started for {doc_name}", icon="🔄")
                        st.rerun()
                    except AIAPIError as e:
                        st.error(e.message)

            # 3. Versions Inspector Toggle
            with col_vers:
                show_vers = st.toggle("📜 Versions", key=f"toggle_vers_{doc_id}")

            # 4. Details / Chunks Toggle
            with col_detail:
                show_chunks = st.toggle("🔍 Chunks", key=f"toggle_chunks_{doc_id}")

            # 5. Delete Action
            with col_del:
                with st.popover("🗑️ Delete", disabled=not is_admin, use_container_width=True):
                    st.markdown(f"**Delete `{doc_name}`?**")
                    st.caption("This will permanently remove the document, disk file, and all vector embeddings from ChromaDB.")
                    if st.button("Confirm Delete", key=f"btn_del_conf_{doc_id}", type="primary"):
                        try:
                            ai_client.delete_document(doc_id, access_token)
                            st.toast(f"Deleted {doc_name}", icon="🗑️")
                            st.rerun()
                        except AIAPIError as e:
                            st.error(e.message)

            # Versions Drawer
            if show_vers:
                st.markdown("##### 📜 Version History in Group")
                try:
                    versions = ai_client.get_document_versions(doc_id, access_token)
                    if versions:
                        v_rows = []
                        for v in versions:
                            v_rows.append({
                                "Version": v.get("version"),
                                "Name": v.get("name"),
                                "Status": v.get("status"),
                                "Active (In RAG)": "🟢 Active" if v.get("active") else "⚪ Inactive",
                                "Size": format_bytes(v.get("size_bytes")),
                                "Uploaded": format_iso_timestamp(v.get("uploaded_at")),
                                "Doc ID": v.get("id"),
                            })
                        st.dataframe(v_rows, use_container_width=True)
                    else:
                        st.info("No other versions found in this group.")
                except Exception as ex:
                    st.error(f"Failed to load versions: {ex}")

            # Chunks & Details Drawer
            if show_chunks:
                st.markdown("##### 🔍 Document Details & Indexed Chunks")
                try:
                    detail = ai_client.get_document(doc_id, access_token)
                    chunks = detail.get("chunks", [])
                    st.markdown(
                        f"- **MIME Type:** `{detail.get('mime')}` &nbsp;|&nbsp; "
                        f"- **SHA-256 Hash:** `{detail.get('sha256')}` &nbsp;|&nbsp; "
                        f"- **Indexed Chunks:** `{len(chunks)}`"
                    )
                    if detail.get("error"):
                        st.error(f"Pipeline Error: {detail.get('error')}")

                    if chunks:
                        c_rows = []
                        for c in chunks:
                            c_rows.append({
                                "Chunk Index": c.get("chunk_index"),
                                "Page": c.get("page") if c.get("page") is not None else "-",
                                "Section": c.get("section") or "-",
                                "Token Count": c.get("token_count") or "-",
                                "Vector ID": c.get("vector_id") or "-",
                            })
                        st.dataframe(c_rows, use_container_width=True)
                    else:
                        st.info("No indexed chunks available (document may be pending or failed ingestion).")
                except Exception as ex:
                    st.error(f"Failed to load chunk details: {ex}")


def render_document_manager() -> None:
    """Main entry point for Knowledge Base & Document administration page."""
    token = get_access_token()
    if not token:
        st.warning("Please sign in with administrator or auditor credentials to manage documents.")
        return

    ai_client = get_ai_client()
    is_admin = has_role("ADMIN")

    if not is_admin:
        st.info(
            "ℹ️ **Auditor Mode Enabled**: You have read-only inspection access. "
            "You can examine document metadata, trace version lineage, and audit indexed chunks. "
            "Modifications (upload, activate, deactivate, reprocess, delete) require Administrator privileges."
        )

    tab_library, tab_upload = st.tabs(["📚 Document Library", "⬆️ Upload Document"])

    with tab_library:
        render_document_library(ai_client=ai_client, access_token=token, is_admin=is_admin)

    with tab_upload:
        render_document_uploader(ai_client=ai_client, access_token=token, is_admin=is_admin)
