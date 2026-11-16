"""Execution node: calls banking API after human confirmation and authentication."""
from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage
from langchain_core.runnables import RunnableConfig

from app.agents.state import GraphState
from app.agents.workflows.transfer import format_inr
from app.core.config import get_settings
from app.integrations.banking_client import BankingClient, BankingClientError
from app.models.approval import ApprovalStatus, WorkflowType

logger = logging.getLogger(__name__)


def execute_node(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """Execute node: calls backend Banking API using single-use authorization token.
    
    This node is reached ONLY after approval_gate passes confirmation and secondary
    authentication. The authorization credentials (authorization_id) never traversed
    the LLM.
    """
    pending_action = state.get("pending_action")
    if not pending_action:
        return {}

    approval_status = state.get("approval_status")
    if approval_status not in (
        ApprovalStatus.CONFIRMED.value,
        ApprovalStatus.AUTHENTICATED.value,
    ):
        logger.warning(
            "Execute node called with invalid approval status '%s'; aborting execution.",
            approval_status,
        )
        return {}

    workflow = pending_action.get("workflow")
    requires_auth = workflow in (
        WorkflowType.TRANSFER.value,
        WorkflowType.CARD_PAYMENT.value,
        WorkflowType.BENEFICIARY.value,
    )
    auth_token = state.get("authorization_id") or ""
    if requires_auth and not auth_token:
        logger.warning(
            "Execute node called for workflow '%s' without authorization token; aborting.",
            workflow,
        )
        return {}

    cfg = config.get("configurable", {}) if config else {}
    access_token = cfg.get("access_token", "")
    settings = get_settings()

    if workflow == WorkflowType.BENEFICIARY.value:
        action_data = pending_action.get("action_data") or {}
        name = action_data.get("name", "Beneficiary")
        acc_num = action_data.get("account_number", "")
        last4 = acc_num[-4:] if len(acc_num) >= 4 else "XXXX"

        try:
            client = BankingClient(settings=settings, access_token=access_token)
            res = client.create_beneficiary(action_data, approval_token=auth_token)
            bene_id = res.get("id")
            success_msg = (
                f"Beneficiary **{name}** (account ending in {last4}) "
                "has been successfully added and verified."
            )
            logger.info("Successfully created beneficiary %s (id=%s)", name, bene_id)
            return {
                "transaction_reference": bene_id,
                "response": success_msg,
                "messages": [AIMessage(content=success_msg)],
                "pending_action": None,
                "approval_status": ApprovalStatus.EXECUTED.value,
            }
        except BankingClientError as exc:
            logger.error("BankingClient error executing beneficiary creation: %s", exc.message)
            err_msg = f"Failed to add beneficiary: {exc.message}"
            return {
                "response": err_msg,
                "messages": [AIMessage(content=err_msg)],
                "error_code": exc.error_code,
            }
        except Exception as exc:
            logger.exception("Unexpected error executing beneficiary creation: %s", exc)
            err_msg = f"Failed to add beneficiary: {exc}"
            return {
                "response": err_msg,
                "messages": [AIMessage(content=err_msg)],
                "error_code": "EXECUTION_FAILED",
            }

    if workflow == WorkflowType.TRANSFER.value:
        action_data = pending_action.get("action_data") or {}
        txn_id = pending_action.get("banking_resource_id") or action_data.get("txn_id")
        summary_hash = pending_action.get("summary_hash") or action_data.get("summary_hash", "")
        summary = pending_action.get("summary_masked") or {}
        amt_str = summary.get("amount", "")
        bene_name = summary.get("beneficiary", "beneficiary")
        acc_masked = summary.get("account_masked", "")

        try:
            client = BankingClient(settings=settings, access_token=access_token)
            exec_res = client.execute_transfer(
                txn_id=txn_id,
                authorization_id=auth_token,
                summary_hash=summary_hash,
                idempotency_key=f"exec-{txn_id}",
            )
            # Query final status from banking
            status_res = client.get_transfer_status(txn_id)
            ref = status_res.get("reference") or exec_res.get("reference", txn_id)
            txn_status = status_res.get("status") or exec_res.get("status", "COMPLETED")

            success_msg = (
                f"Transfer of **{amt_str}** to **{bene_name}** ({acc_masked}) "
                f"has been completed successfully.\n"
                f"- **Reference**: {ref}\n"
                f"- **Status**: {txn_status}"
            )
            logger.info("Successfully executed transfer %s (ref=%s)", txn_id, ref)
            return {
                "transaction_reference": ref,
                "response": success_msg,
                "messages": [AIMessage(content=success_msg)],
                "pending_action": None,
                "approval_status": ApprovalStatus.EXECUTED.value,
            }
        except BankingClientError as exc:
            logger.error("BankingClient error executing transfer: %s", exc.message)
            err_msg = f"Failed to execute transfer: {exc.message}"
            return {
                "response": err_msg,
                "messages": [AIMessage(content=err_msg)],
                "error_code": exc.error_code,
            }
        except Exception as exc:
            logger.exception("Unexpected error executing transfer: %s", exc)
            err_msg = f"Failed to execute transfer: {exc}"
            return {
                "response": err_msg,
                "messages": [AIMessage(content=err_msg)],
                "error_code": "EXECUTION_FAILED",
            }

    if workflow == WorkflowType.LOAN.value:
        action_data = pending_action.get("action_data") or {}
        idempotency_key = (
            action_data.get("idempotency_key")
            or f"loan-app-{pending_action.get('banking_resource_id') or 'draft'}"
        )
        app_payload = {
            "offer_id": action_data.get("offer_id"),
            "loan_type": action_data.get("loan_type", "PERSONAL"),
            "amount_minor": action_data.get("amount_minor"),
            "tenure_months": action_data.get("tenure_months"),
            "employment_type": action_data.get("employment_type", "SALARIED"),
            "employer": action_data.get("employer", "Private Limited"),
            "monthly_income_minor": action_data.get("monthly_income_minor"),
        }

        try:
            client = BankingClient(settings=settings, access_token=access_token)
            res = client.submit_loan_application(app_payload, idempotency_key=idempotency_key)
            app_id = res.get("id")
            ref = res.get("reference", app_id)
            loan_status = res.get("status", "SUBMITTED")
            loan_type = res.get("loan_type", app_payload["loan_type"])
            summary = pending_action.get("summary_masked") or {}
            amt_str = summary.get("amount") or format_inr(app_payload["amount_minor"])
            emi_str = summary.get("estimated_emi", "")

            if loan_status == "APPROVED":
                emi_line = f"\n- **Monthly EMI**: {emi_str}" if emi_str else ""
                success_msg = (
                    f"Congratulations! Your application for a **{loan_type.capitalize()} Loan** of "
                    f"**{amt_str}** has been approved.\n"
                    f"- **Application Reference**: {ref}\n"
                    f"- **Status**: {loan_status}"
                    f"{emi_line}"
                )
            else:
                reason = res.get("decision_reason") or "Application submitted for processing"
                success_msg = (
                    f"Your application for a **{loan_type.capitalize()} Loan** of **{amt_str}** "
                    f"has been submitted.\n"
                    f"- **Application Reference**: {ref}\n"
                    f"- **Status**: {loan_status}\n"
                    f"- **Details**: {reason}"
                )

            logger.info("Successfully submitted loan application %s (ref=%s)", app_id, ref)
            return {
                "transaction_reference": ref,
                "response": success_msg,
                "messages": [AIMessage(content=success_msg)],
                "pending_action": None,
                "approval_status": ApprovalStatus.EXECUTED.value,
            }
        except BankingClientError as exc:
            logger.error("BankingClient error submitting loan application: %s", exc.message)
            err_msg = f"Failed to submit loan application: {exc.message}"
            return {
                "response": err_msg,
                "messages": [AIMessage(content=err_msg)],
                "error_code": exc.error_code,
            }
        except Exception as exc:
            logger.exception("Unexpected error submitting loan application: %s", exc)
            err_msg = f"Failed to submit loan application: {exc}"
            return {
                "response": err_msg,
                "messages": [AIMessage(content=err_msg)],
                "error_code": "EXECUTION_FAILED",
            }

    if workflow == WorkflowType.CARD_PAYMENT.value:
        action_data = pending_action.get("action_data") or {}
        payment_id = pending_action.get("banking_resource_id") or action_data.get("payment_id")
        summary = pending_action.get("summary_masked") or {}
        amt_str = summary.get("amount") or format_inr(action_data.get("amount_minor", 0))
        card_info = summary.get("card", "Credit Card")

        try:
            client = BankingClient(settings=settings, access_token=access_token)
            exec_res = client.execute_card_payment(
                payment_id=payment_id,
                authorization_id=auth_token,
                idempotency_key=f"exec-{payment_id}",
            )
            try:
                status_res = client.get_card_payment_status(payment_id)
                ref = status_res.get("reference") or exec_res.get("reference", payment_id)
                payment_status = status_res.get("status") or exec_res.get("status", "COMPLETED")
            except Exception:
                ref = exec_res.get("reference", payment_id)
                payment_status = exec_res.get("status", "COMPLETED")

            success_msg = (
                f"Credit card payment of **{amt_str}** for **{card_info}** "
                f"has been completed successfully.\n"
                f"- **Reference**: {ref}\n"
                f"- **Status**: {payment_status}"
            )
            logger.info("Successfully executed credit card payment %s (ref=%s)", payment_id, ref)
            return {
                "transaction_reference": ref,
                "response": success_msg,
                "messages": [AIMessage(content=success_msg)],
                "pending_action": None,
                "approval_status": ApprovalStatus.EXECUTED.value,
            }
        except BankingClientError as exc:
            logger.error("BankingClient error executing card payment: %s", exc.message)
            err_msg = f"Failed to execute credit card payment: {exc.message}"
            return {
                "response": err_msg,
                "messages": [AIMessage(content=err_msg)],
                "error_code": exc.error_code,
            }
        except Exception as exc:
            logger.exception("Unexpected error executing card payment: %s", exc)
            err_msg = f"Failed to execute credit card payment: {exc}"
            return {
                "response": err_msg,
                "messages": [AIMessage(content=err_msg)],
                "error_code": "EXECUTION_FAILED",
            }

    return {}
