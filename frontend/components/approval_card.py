"""Approval Card component for Human-in-the-Loop confirmation (Stage 1)."""
from __future__ import annotations

import datetime
from typing import Any

import streamlit as st

from components.pin_dialog import render_pin_modal_dialog
from state.session import get_access_token, get_ai_client


def render_approval_card(approval_data: dict[str, Any]) -> None:
    """Render a structured HITL Approval Card with confirmation and rejection actions."""
    if not approval_data:
        return

    approval_id = approval_data.get("approval_id") or approval_data.get("id")
    workflow = str(approval_data.get("workflow", "TRANSACTION")).upper()
    status = str(approval_data.get("status", "PENDING")).upper()
    summary = approval_data.get("summary") or approval_data.get("summary_masked") or {}
    expires_at_str = approval_data.get("expires_at")
    risk_level = approval_data.get("risk_level", "FINANCIAL")

    workflow_icons = {
        "TRANSFER": "💸 Fund Transfer Confirmation",
        "CARD_PAYMENT": "💳 Credit Card Bill Payment",
        "CARD": "💳 Card Operation",
        "BENEFICIARY": "👥 Add Beneficiary Confirmation",
        "LOAN": "💰 Loan Application Confirmation",
    }
    card_title = workflow_icons.get(workflow, f"⚠️ {workflow.capitalize()} Confirmation")

    with st.container(border=True):
        col_hdr1, col_hdr2 = st.columns([3, 1])
        with col_hdr1:
            st.subheader(card_title)
        with col_hdr2:
            st.markdown(f"**Risk:** `{risk_level}` | **Status:** `{status}`")

        # Expiry notice
        if expires_at_str:
            try:
                exp_dt = datetime.datetime.fromisoformat(expires_at_str.replace("Z", "+00:00"))
                now_dt = datetime.datetime.now(datetime.timezone.utc)
                remaining_sec = int((exp_dt - now_dt).total_seconds())
                if remaining_sec > 0:
                    mins = remaining_sec // 60
                    secs = remaining_sec % 60
                    st.caption(f"⏳ **Action Required:** Approval expires in ~{mins}m {secs}s")
                else:
                    st.error("⏳ **Approval Expired:** This approval request has timed out.")
            except Exception:
                pass

        st.markdown("Please carefully review the transaction parameters below before confirming:")

        # Summary details table / metrics
        if isinstance(summary, dict) and summary:
            # Display prominent metrics if available
            amount_val = summary.get("amount") or summary.get("amount_formatted")
            total_val = summary.get("total_debit")
            beneficiary_val = summary.get("beneficiary") or summary.get("name") or summary.get("payee")

            cols = st.columns(3)
            if amount_val:
                cols[0].metric("Amount", amount_val)
            if total_val and total_val != amount_val:
                cols[1].metric("Total Debit", total_val)
            if beneficiary_val:
                cols[2].metric("Beneficiary / Target", beneficiary_val)

            # Detail breakdown
            with st.expander("Transaction Breakdown & Verification", expanded=True):
                for k, v in summary.items():
                    label = k.replace("_", " ").title()
                    st.markdown(f"- **{label}:** `{v}`")
        else:
            st.write("No summary details available.")

        st.markdown("---")

        col_btn1, col_btn2 = st.columns([1, 1])

        with col_btn1:
            confirm_label = "✅ Confirm & Authenticate" if workflow in ("TRANSFER", "CARD_PAYMENT", "BENEFICIARY") else "✅ Confirm & Submit"
            if st.button(confirm_label, key=f"btn_confirm_{approval_id}", type="primary", use_container_width=True):
                token = get_access_token()
                if not token:
                    st.error("Authentication required.")
                    return

                ai_client = get_ai_client()
                try:
                    with st.spinner("Submitting confirmation..."):
                        dec_res = ai_client.decide_approval(approval_id, "CONFIRM", token)
                        st.session_state["last_decision"] = dec_res

                    # Stage 2: If secondary authentication (PIN) is required, open PIN dialog
                    if workflow in ("TRANSFER", "CARD_PAYMENT", "CARD", "BENEFICIARY"):
                        # Launch modal PIN dialog
                        render_pin_modal_dialog(approval_data)
                    else:
                        st.success("Approval confirmed and executed successfully!")
                        if "pending_approval" in st.session_state:
                            del st.session_state["pending_approval"]
                        st.rerun()

                except Exception as e:
                    st.error(f"Error submitting confirmation: {e}")

        with col_btn2:
            if st.button("❌ Reject & Cancel", key=f"btn_reject_{approval_id}", use_container_width=True):
                token = get_access_token()
                if not token:
                    st.error("Authentication required.")
                    return

                ai_client = get_ai_client()
                try:
                    with st.spinner("Rejecting transaction..."):
                        ai_client.decide_approval(approval_id, "REJECT", token)
                        if "pending_approval" in st.session_state:
                            del st.session_state["pending_approval"]
                        st.info("Transaction was rejected. Draft has been cancelled.")
                        st.rerun()
                except Exception as e:
                    st.error(f"Error rejecting transaction: {e}")
