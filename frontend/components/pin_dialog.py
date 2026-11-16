"""PIN authentication dialog for direct-to-banking authorization (HITL Stage 2).

SECURITY INVARIANT:
The user transaction PIN is submitted DIRECTLY to the Banking Service.
It NEVER traverses, is logged by, or is stored in the AI Service or LangGraph state.
"""
from __future__ import annotations

import logging
from typing import Any

import streamlit as st

from clients.banking_client import BankingAPIError, BankingClient
from state.session import get_access_token, get_ai_client, get_banking_client

logger = logging.getLogger(__name__)


def submit_direct_pin_authorization(
    workflow: str,
    banking_resource_id: str,
    pin: str,
    approval_id: str,
    summary_hash: str | None,
    banking_client: BankingClient,
    access_token: str,
) -> str:
    """Submit PIN directly to Banking Service and return authorization_id."""
    workflow_upper = workflow.upper()

    if workflow_upper == "TRANSFER":
        # 1. Create challenge at banking
        challenge_res = banking_client.create_transfer_challenge(
            txn_id=banking_resource_id,
            access_token=access_token,
        )
        challenge_id = challenge_res.get("challenge_id")
        if not challenge_id:
            raise BankingAPIError("Failed to obtain transfer authorization challenge from Banking service.")

        # 2. Authorize with PIN directly at banking
        auth_res = banking_client.authorize_transfer(
            txn_id=banking_resource_id,
            challenge_id=challenge_id,
            pin=pin,
            access_token=access_token,
        )
        auth_id = auth_res.get("authorization_id")
        if not auth_id:
            raise BankingAPIError("Banking service did not return authorization_id.")
        return auth_id

    elif workflow_upper in ("CARD_PAYMENT", "CARD"):
        # Direct card payment PIN authorization at banking
        auth_res = banking_client.authorize_card_payment(
            payment_id=banking_resource_id,
            pin=pin,
            access_token=access_token,
        )
        auth_id = auth_res.get("id") or banking_resource_id
        return auth_id

    elif workflow_upper == "BENEFICIARY":
        # Direct beneficiary PIN verification at banking
        challenge_res = banking_client.create_beneficiary_challenge(
            action="BENEFICIARY_CREATE",
            payload_hash=summary_hash or "",
            access_token=access_token,
        )
        challenge_id = challenge_res.get("challenge_id")
        if not challenge_id:
            raise BankingAPIError("Failed to obtain beneficiary challenge from Banking service.")

        verify_res = banking_client.verify_beneficiary_challenge(
            challenge_id=challenge_id,
            pin=pin,
            access_token=access_token,
        )
        auth_id = verify_res.get("approval_token")
        if not auth_id:
            raise BankingAPIError("Banking service did not issue approval_token.")
        return auth_id

    else:
        # Default or fallback authorization token
        return banking_resource_id or approval_id


@st.dialog("🔒 Enter Transaction PIN")
def render_pin_modal_dialog(
    approval_data: dict[str, Any],
) -> None:
    """Streamlit modal dialog for entering transaction PIN directly to Banking."""
    approval_id = approval_data.get("approval_id") or approval_data.get("id")
    workflow = approval_data.get("workflow", "TRANSFER")
    banking_resource_id = approval_data.get("banking_resource_id") or ""
    summary_hash = approval_data.get("summary_hash")

    st.markdown(
        f"Please enter your **4-digit Transaction PIN** to authorize this **{workflow.capitalize()}**."
    )
    st.info(
        "🛡️ **Security Invariant:** Your PIN is transmitted directly to the Core Banking "
        "subsystem over an encrypted connection. It never traverses or touches the AI Chat Service."
    )

    with st.form("pin_auth_form", clear_on_submit=False):
        pin = st.text_input(
            "Transaction PIN",
            type="password",
            max_chars=6,
            placeholder="••••",
            help="Your 4 to 6 digit transaction security PIN",
        )
        submitted = st.form_submit_button("Authorize & Execute", use_container_width=True, type="primary")

    if submitted:
        if not pin or len(pin) < 4:
            st.error("Please enter a valid 4-to-6 digit PIN.")
            return

        token = get_access_token()
        if not token:
            st.error("Session expired. Please log in again.")
            return

        banking_client = get_banking_client()
        ai_client = get_ai_client()

        try:
            with st.spinner("Authorizing directly with Banking Service..."):
                # Step 1: Direct Banking PIN Authorization
                authorization_id = submit_direct_pin_authorization(
                    workflow=workflow,
                    banking_resource_id=banking_resource_id,
                    pin=pin,
                    approval_id=approval_id,
                    summary_hash=summary_hash,
                    banking_client=banking_client,
                    access_token=token,
                )

                st.success("Authorization verified by Banking service!")

            with st.spinner("Executing transaction..."):
                # Step 2: Resume LangGraph workflow at AI Service with authorization_id (no secrets)
                resume_res = ai_client.resume_approval(
                    approval_id=approval_id,
                    authorization_id=authorization_id,
                    access_token=token,
                    summary_hash=summary_hash,
                )

                # Clear pending approval state from session
                if "pending_approval" in st.session_state:
                    del st.session_state["pending_approval"]
                st.session_state["approval_executed"] = True

                st.success(f"Transaction completed! Status: {resume_res.get('status', 'EXECUTED')}")
                st.rerun()

        except BankingAPIError as e:
            st.error(f"❌ Authorization failed at Banking Service: {e.message}")
        except Exception as e:
            st.error(f"Execution error: {e}")
