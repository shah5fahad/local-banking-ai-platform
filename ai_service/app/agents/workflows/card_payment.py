"""Credit card payment workflow: select card, choose due amount, validate balance, prepare payment."""
from __future__ import annotations

import hashlib
import json
import logging
import re
import uuid
from typing import Any

from langchain_core.messages import AIMessage, AnyMessage
from langchain_core.runnables import RunnableConfig

from app.agents.state import GraphState, PendingAction
from app.agents.workflows.transfer import format_inr, parse_amount_to_minor
from app.core.config import get_settings
from app.integrations.banking_client import BankingClient, BankingClientError
from app.models.approval import ApprovalStatus, WorkflowType

logger = logging.getLogger(__name__)


def extract_card_payment_fields(
    text: str, messages: list[AnyMessage] | None = None
) -> dict[str, Any]:
    """Extract card selector and amount/option choice from text and history."""
    combined_texts: list[str] = []
    if messages:
        for m in messages:
            msg_type = getattr(m, "type", "")
            is_user = msg_type == "human" or getattr(m, "role", "") == "user"
            if is_user:
                content = getattr(m, "content", "")
                if isinstance(content, str) and content.strip():
                    combined_texts.append(content)
    combined_texts.append(text)
    full_text = " \n ".join(combined_texts)
    lower = full_text.lower()
    curr_lower = text.lower()

    # 1. Option detection: Total Due vs Minimum Due
    option: str | None = None
    if any(k in curr_lower for k in ["total due", "total bill", "pay total", "full amount", "pay full", "pay all"]):
        option = "TOTAL"
    elif any(k in curr_lower for k in ["minimum due", "min due", "minimum amount", "pay min", "pay minimum"]):
        option = "MINIMUM"
    elif any(k in lower for k in ["total due", "total bill", "full amount", "pay full"]):
        option = "TOTAL"
    elif any(k in lower for k in ["minimum due", "min due", "minimum amount", "pay min"]):
        option = "MINIMUM"

    # 2. Specific amount parsing (if option is not selected or custom amount provided)
    amount_minor = parse_amount_to_minor(text)
    if amount_minor is None and option is None and len(combined_texts) > 1:
        amount_minor = parse_amount_to_minor(full_text)

    # 3. Card identifier (last4 digits or network name)
    card_identifier: str | None = None
    m_last4 = re.search(r"\b(?:card|ending\s+in|ending|last\s*4)?[:\s]*([0-9]{4})\b", text, re.IGNORECASE)
    if m_last4:
        card_identifier = m_last4.group(1)
    else:
        for net in ["visa", "mastercard", "rupay", "amex"]:
            if net in curr_lower:
                card_identifier = net
                break

    if not card_identifier and len(combined_texts) > 1:
        m_last4_hist = re.search(r"\b(?:card|ending\s+in|ending|last\s*4)?[:\s]*([0-9]{4})\b", full_text, re.IGNORECASE)
        if m_last4_hist:
            card_identifier = m_last4_hist.group(1)

    return {
        "option": option,
        "amount_minor": amount_minor,
        "card_identifier": card_identifier,
    }


def workflow_card_payment_node(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """Credit card payment workflow node.

    1. Finds active credit cards for user.
    2. Retrieves current statement bill (total due, minimum due, due date).
    3. Handles payment amount selection (Total Due, Minimum Due, or custom amount).
    4. Selects active bank account with sufficient balance.
    5. Calls banking service POST /credit-cards/{id}/payments to draft payment.
    6. Returns PendingAction with masked review details for approval_gate.
    """
    user_msg = state.get("user_message", "")
    messages = state.get("messages", [])
    extracted = extract_card_payment_fields(user_msg, messages)

    cfg = config.get("configurable", {}) if config else {}
    access_token = cfg.get("access_token", "")
    settings = get_settings()

    if not access_token:
        err = "Authentication session is missing. Please log in again."
        return {
            "response": err,
            "messages": [AIMessage(content=err)],
            "error_code": "UNAUTHENTICATED",
        }

    client = BankingClient(settings=settings, access_token=access_token)

    # 1. Fetch user's credit cards
    try:
        cards = client.list_cards()
    except Exception as exc:
        logger.error("Failed to fetch credit cards: %s", exc)
        cards = []

    active_cards = [c for c in cards if c.get("status") == "ACTIVE"]
    if not active_cards:
        msg = "You do not have any active credit cards."
        return {
            "response": msg,
            "messages": [AIMessage(content=msg)],
            "approval_status": "NONE",
            "authentication_status": "NONE",
        }

    # 2. Match target card
    card_id_query = extracted.get("card_identifier")
    target_card: dict[str, Any] | None = None
    if card_id_query:
        for c in active_cards:
            if c.get("last4") == card_id_query or card_id_query.lower() in c.get("network", "").lower():
                target_card = c
                break

    if not target_card and len(active_cards) > 1:
        options = []
        for i, c in enumerate(active_cards, 1):
            net = c.get("network", "Card")
            l4 = c.get("last4", "XXXX")
            outstanding = format_inr(c.get("outstanding_minor", 0))
            options.append(f"{i}. **{net}** ending in **{l4}** (Outstanding: {outstanding})")
        options_text = "\n".join(options)
        msg = (
            f"You have multiple active credit cards:\n{options_text}\n\n"
            "Please specify which card you'd like to pay (e.g. 'Pay card ending in 1234')."
        )
        return {
            "response": msg,
            "messages": [AIMessage(content=msg)],
            "approval_status": "NONE",
            "authentication_status": "NONE",
        }

    if not target_card:
        target_card = active_cards[0]

    card_id = target_card["id"]
    last4 = target_card.get("last4", "XXXX")
    network = target_card.get("network", "Credit Card")

    # 3. Fetch latest bill statement & outstanding
    statement_id: str | None = None
    total_due_minor = target_card.get("outstanding_minor", 0)
    min_due_minor = max(50000, int(total_due_minor * 0.05)) if total_due_minor > 0 else 0
    due_date_str = "Promptly"

    try:
        bill = client.get_current_bill(card_id)
        if bill:
            statement_id = bill.get("id")
            total_due_minor = bill.get("total_due_minor", total_due_minor)
            min_due_minor = bill.get("min_due_minor", min_due_minor)
            raw_due = bill.get("due_date")
            if raw_due:
                # Format ISO date string
                due_date_str = str(raw_due).split("T")[0]
    except Exception as exc:
        logger.debug("Could not fetch current bill for card %s: %s", card_id, exc)

    # 4. Resolve payment amount & option
    option = extracted.get("option")
    amount_minor = extracted.get("amount_minor")

    if option == "TOTAL":
        payment_amount_minor = total_due_minor
        option_label = "Total Due"
    elif option == "MINIMUM":
        payment_amount_minor = min_due_minor
        option_label = "Minimum Due"
    elif amount_minor and amount_minor > 0:
        payment_amount_minor = amount_minor
        option_label = "Custom Amount"
    else:
        # Prompt user to choose payment option
        total_str = format_inr(total_due_minor)
        min_str = format_inr(min_due_minor)
        prompt = (
            f"Here are the bill details for your **{network}** card ending in **{last4}**:\n"
            f"- **Total Due**: {total_str}\n"
            f"- **Minimum Due**: {min_str}\n"
            f"- **Due Date**: {due_date_str}\n\n"
            "How much would you like to pay? You can reply with:\n"
            "- 'Pay total due'\n"
            "- 'Pay minimum due'\n"
            "- Or specify a custom amount (e.g. 'Pay ₹5,000')"
        )
        return {
            "response": prompt,
            "messages": [AIMessage(content=prompt)],
            "approval_status": "NONE",
            "authentication_status": "NONE",
        }

    if payment_amount_minor <= 0:
        msg = f"Your **{network}** card ending in **{last4}** has no outstanding balance due."
        return {
            "response": msg,
            "messages": [AIMessage(content=msg)],
            "approval_status": "NONE",
            "authentication_status": "NONE",
        }

    # 5. Source Bank Account Selection & Balance Check
    try:
        accounts = client.list_accounts()
    except Exception as exc:
        logger.error("Failed to list accounts for card payment: %s", exc)
        accounts = []

    active_accounts = [a for a in accounts if a.get("status") == "ACTIVE"]
    if not active_accounts:
        msg = "You do not have any active bank accounts available to pay your credit card bill."
        return {
            "response": msg,
            "messages": [AIMessage(content=msg)],
            "approval_status": "NONE",
            "authentication_status": "NONE",
        }

    source_acc = next(
        (a for a in active_accounts if a.get("balance_minor", 0) >= payment_amount_minor),
        None,
    )
    if not source_acc:
        primary_acc = active_accounts[0]
        curr_bal_str = format_inr(primary_acc.get("balance_minor", 0))
        req_amt_str = format_inr(payment_amount_minor)
        msg = (
            f"Insufficient balance in your primary account. Available balance is "
            f"**{curr_bal_str}**, but paying this bill requires **{req_amt_str}**."
        )
        return {
            "response": msg,
            "messages": [AIMessage(content=msg)],
            "approval_status": "NONE",
            "authentication_status": "NONE",
        }

    # 6. Prepare Card Payment Draft at Banking API
    idempotency_key = str(uuid.uuid4())
    draft_payload = {
        "statement_id": statement_id,
        "source_account_id": source_acc["id"],
        "amount_minor": payment_amount_minor,
    }

    try:
        draft = client.prepare_card_payment(card_id, draft_payload, idempotency_key=idempotency_key)
    except BankingClientError as exc:
        logger.error("BankingClient error preparing card payment: %s", exc.message)
        err_msg = f"Unable to prepare card payment: {exc.message}"
        return {
            "response": err_msg,
            "messages": [AIMessage(content=err_msg)],
            "error_code": exc.error_code,
        }
    except Exception as exc:
        logger.exception("Unexpected error preparing card payment: %s", exc)
        err_msg = f"Unable to prepare card payment: {exc}"
        return {
            "response": err_msg,
            "messages": [AIMessage(content=err_msg)],
            "error_code": "PREPARE_PAYMENT_FAILED",
        }

    payment_id = draft.get("id")
    ref = draft.get("reference", payment_id)
    source_masked = source_acc.get("account_number_masked") or f"XXXXXX{source_acc.get('last4', 'XXXX')}"

    # 7. Assemble PendingAction for approval gate
    summary_masked = {
        "card": f"{network} ending in {last4}",
        "card_last4": last4,
        "amount": format_inr(payment_amount_minor),
        "payment_option": option_label,
        "source_account": source_masked,
        "reference": ref,
    }

    summary_bytes = json.dumps(summary_masked, sort_keys=True).encode("utf-8")
    summary_hash = hashlib.sha256(summary_bytes).hexdigest()

    pending_action: PendingAction = {
        "workflow": WorkflowType.CARD_PAYMENT.value,
        "banking_resource_id": payment_id,
        "summary_masked": summary_masked,
        "summary_hash": summary_hash,
        "stage": "CONFIRM",
        "action_data": {
            "card_id": card_id,
            "payment_id": payment_id,
            "statement_id": statement_id,
            "source_account_id": source_acc["id"],
            "amount_minor": payment_amount_minor,
            "summary_hash": summary_hash,
            "idempotency_key": idempotency_key,
        },
    }

    review_msg = (
        f"Please review the credit card payment details:\n"
        f"- **Credit Card**: {network} ending in {last4}\n"
        f"- **Amount to Pay**: {format_inr(payment_amount_minor)} ({option_label})\n"
        f"- **Debited From**: Account {source_masked}\n"
        f"- **Payment Reference**: {ref}\n\n"
        "Please confirm or reject to proceed."
    )

    return {
        "pending_action": pending_action,
        "approval_status": ApprovalStatus.PENDING.value,
        "authentication_status": "NONE",
        "response": review_msg,
        "messages": [AIMessage(content=review_msg)],
    }
