"""Approval gate node with LangGraph interrupt() for HITL workflows."""
from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from app.agents.state import GraphState
from app.db.engine import get_session_factory
from app.models.approval import ApprovalStatus, WorkflowType
from app.services.approval_service import ApprovalService

logger = logging.getLogger(__name__)


def approval_gate_node(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """Approval gate node: persists PendingApproval and calls interrupt().

    Executes in two possible interrupt stages:
    1. STAGE 'CONFIRM': Pauses for user confirmation (CONFIRM / REJECT).
    2. STAGE 'AUTH_REQUIRED': If the action is financial/sensitive, pauses for PIN/OTP
       authorization directly at Banking API, resumed with authorization_id.
    """
    pending_action = state.get("pending_action")
    if not pending_action:
        return {}

    cfg = config.get("configurable", {}) if config else {}
    thread_id = cfg.get("thread_id") or state.get("conversation_id", "")
    conv_id = state.get("conversation_id", "")
    workflow = pending_action.get("workflow", WorkflowType.TRANSFER.value)
    summary_masked = pending_action.get("summary_masked", {})
    summary_hash = pending_action.get("summary_hash", "")
    banking_resource_id = pending_action.get("banking_resource_id")
    approval_id = state.get("approval_id")

    # 1. Ensure PendingApproval is saved in AI database
    session_factory = get_session_factory()
    with session_factory() as db:
        from app.db.base import Base
        Base.metadata.create_all(bind=db.get_bind())
        service = ApprovalService(db)
        if not approval_id:
            # Ensure conversation exists to satisfy FK constraint if invoked standalone
            from app.models.chat import ChatUserReference, Conversation

            if not conv_id:
                conv_id = thread_id or str(uuid.uuid4())

            conv = db.get(Conversation, conv_id)
            if not conv:
                uid = state.get("user_id") or "default-user"
                from sqlalchemy import select
                stmt = select(ChatUserReference).where(ChatUserReference.banking_user_id == uid)
                user_ref = db.execute(stmt).scalar_one_or_none()
                if not user_ref:
                    user_ref = ChatUserReference(
                        banking_user_id=uid,
                        role_snapshot="CUSTOMER",
                        display_name_masked=f"User {uid[-4:] if len(uid) >= 4 else uid}",
                    )
                    db.add(user_ref)
                    db.commit()
                    db.refresh(user_ref)
                conv = Conversation(id=conv_id, user_ref_id=user_ref.id, title="Workflow")
                db.add(conv)
                db.commit()

            raw_tok = cfg.get("access_token") if cfg else None
            approval = service.create_approval(
                conversation_id=conv_id,
                thread_id=thread_id,
                workflow_type=workflow,
                risk_level=pending_action.get("risk_level"),
                summary_masked=summary_masked,
                summary_hash=summary_hash,
                banking_resource_id=banking_resource_id,
                raw_token=raw_tok,
            )
            approval_id = approval.id
        else:
            approval = service.get_approval(approval_id)

        expires_at_iso = approval.expires_at.isoformat() if approval.expires_at else None

    # 2. Stage 1: Confirmation Interrupt
    current_approval_status = state.get("approval_status", ApprovalStatus.PENDING.value)
    if current_approval_status not in (
        ApprovalStatus.CONFIRMED.value,
        ApprovalStatus.AUTH_REQUIRED.value,
        ApprovalStatus.AUTHENTICATED.value,
        ApprovalStatus.EXECUTED.value,
    ):
        confirm_payload = {
            "approval_id": approval_id,
            "workflow": workflow,
            "stage": "CONFIRM",
            "summary": summary_masked,
            "summary_hash": summary_hash,
            "banking_resource_id": banking_resource_id,
            "expires_at": expires_at_iso,
        }

        # Interrupt execution and wait for human decision via /chat/approvals/{id}/decision
        decision_raw = interrupt(confirm_payload)

        decision = "CONFIRM"
        if isinstance(decision_raw, dict):
            decision = decision_raw.get("decision", "CONFIRM")
        elif isinstance(decision_raw, str):
            decision = decision_raw

        if str(decision).upper() == "REJECT":
            is_cancelled = False
            if isinstance(decision_raw, dict):
                is_cancelled = decision_raw.get("cancelled", False)

            cfg = config.get("configurable", {}) if config else {}
            access_token = cfg.get("access_token", "")
            if (
                not is_cancelled
                and banking_resource_id
                and access_token
                and workflow == WorkflowType.TRANSFER.value
            ):
                try:
                    from app.agents.workflows.transfer import BankingClient
                    from app.core.config import get_settings

                    client = BankingClient(settings=get_settings(), access_token=access_token)
                    client.cancel_transfer(banking_resource_id)
                except Exception as exc:
                    logger.warning("Failed to cancel banking draft on reject: %s", exc)

            rejection_msg = "No action was taken. The request has been cancelled."
            return {
                "approval_id": approval_id,
                "approval_status": ApprovalStatus.REJECTED.value,
                "response": rejection_msg,
                "messages": [AIMessage(content=rejection_msg)],
            }

    # 3. Stage 2: Authentication Interrupt (if workflow requires secondary PIN/OTP)
    requires_auth = workflow in (
        WorkflowType.TRANSFER.value,
        WorkflowType.CARD_PAYMENT.value,
        WorkflowType.BENEFICIARY.value,
    )
    current_auth_status = state.get("authentication_status", "NONE")

    if requires_auth and current_auth_status != "COMPLETED":
        auth_payload = {
            "approval_id": approval_id,
            "workflow": workflow,
            "stage": "AUTH_REQUIRED",
            "banking_resource_id": banking_resource_id,
            "summary_hash": summary_hash,
            "expires_at": expires_at_iso,
        }

        # Interrupt execution and wait for authorization_id via /chat/approvals/{id}/resume
        auth_raw = interrupt(auth_payload)

        auth_id = ""
        if isinstance(auth_raw, dict):
            auth_id = auth_raw.get("authorization_id", "")
        elif isinstance(auth_raw, str):
            auth_id = str(auth_raw)

        return {
            "approval_id": approval_id,
            "approval_status": ApprovalStatus.CONFIRMED.value,
            "authentication_status": "COMPLETED",
            "authorization_id": auth_id,
        }

    return {
        "approval_id": approval_id,
        "approval_status": ApprovalStatus.CONFIRMED.value,
        "authentication_status": "NONE" if not requires_auth else current_auth_status,
    }
