"""Fund transfer workflow: parse amount/beneficiary, validate balance & limits, draft transfer."""
from __future__ import annotations

import logging
import re
import uuid
from typing import Any

from langchain_core.messages import AIMessage, AnyMessage
from langchain_core.runnables import RunnableConfig

from app.agents.state import GraphState, PendingAction
from app.core.config import get_settings
from app.integrations.banking_client import BankingClient, BankingClientError
from app.models.approval import ApprovalStatus, WorkflowType

logger = logging.getLogger(__name__)


INVALID_BENE_TOKENS = {
    "transfer", "send", "pay", "money", "funds", "someone", "somebody",
    "account", "someone else", "my account", "another account",
    "savings", "checking", "current", "here", "there", "yes", "no",
    "please", "proceed", "cancel", "confirm", "some", "the", "a", "an",
    "friend", "relative", "family", "anyone", "me", "myself", "self",
}


def is_valid_bene_candidate(cand: str) -> bool:
    """Validate whether candidate string looks like a legitimate beneficiary name."""
    if not cand or len(cand) < 2:
        return False
    lower_cand = cand.strip().lower()
    if lower_cand in INVALID_BENE_TOKENS:
        return False
    words = lower_cand.split()
    if any(w in {"transfer", "send", "pay", "money", "funds"} for w in words):
        return False
    if lower_cand.startswith("account") or lower_cand.startswith("my "):
        return False
    return True


def format_inr(minor_units: int) -> str:
    """Format paise into Indian Rupee display string with Indian grouping (e.g. ₹1,00,000.00)."""
    amount_rupees = minor_units / 100.0
    parts = f"{amount_rupees:.2f}".split(".")
    integer_part = parts[0]
    decimal_part = parts[1]
    sign = ""
    if integer_part.startswith("-"):
        sign = "-"
        integer_part = integer_part[1:]
    if len(integer_part) > 3:
        last_three = integer_part[-3:]
        remaining = integer_part[:-3]
        grouped = []
        while len(remaining) > 2:
            grouped.append(remaining[-2:])
            remaining = remaining[:-2]
        if remaining:
            grouped.append(remaining)
        grouped.reverse()
        formatted_int = ",".join(grouped) + "," + last_three
    else:
        formatted_int = integer_part
    return f"{sign}₹{formatted_int}.{decimal_part}"


def parse_amount_to_minor(text: str) -> int | None:
    """Parse amount from text and convert to minor units (paise)."""
    # 1. Look for explicit currency indicators: ₹, Rs, INR, rupees
    curr_pattern = re.compile(
        r"(?:(?:rs\.?|inr|₹)\s*)([0-9,]+(?:\.[0-9]{1,2})?)|([0-9,]+(?:\.[0-9]{1,2})?)\s*(?:rs\.?|inr|₹|rupees)",
        re.IGNORECASE,
    )
    for match in curr_pattern.finditer(text):
        val_str = (match.group(1) or match.group(2)).replace(",", "")
        try:
            val_float = float(val_str)
            if val_float > 0:
                return round(val_float * 100)
        except ValueError:
            continue

    # 2. Look for standalone numbers with comma formatting or plain numbers
    plain_pattern = re.compile(
        r"\b([0-9]{1,3}(?:,[0-9]{2,3})+(?:\.[0-9]{1,2})?|[0-9]+(?:\.[0-9]{1,2})?)\b"
    )
    for match in plain_pattern.finditer(text):
        val_str = match.group(1).replace(",", "")
        try:
            val_float = float(val_str)
            if val_float > 0:
                return round(val_float * 100)
        except ValueError:
            continue
    return None


def extract_transfer_fields(
    text: str, messages: list[AnyMessage] | None = None
) -> dict[str, Any]:
    """Extract transfer amount, beneficiary name, channel, and remark from conversation."""
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

    result: dict[str, Any] = {
        "amount_minor": None,
        "beneficiary_name": None,
        "channel": "IMPS",
        "remark": None,
    }

    # 1. Amount
    result["amount_minor"] = parse_amount_to_minor(text)
    if result["amount_minor"] is None and len(combined_texts) > 1:
        result["amount_minor"] = parse_amount_to_minor(full_text)

    # 2. Beneficiary name
    bene_patterns = [
        r"(?:transfer|send|pay)\s+(?:rs\.?|inr|₹)?\s*[0-9,.]+\s*(?:rs\.?|inr|₹|rupees)?\s+to\s+([A-Za-z\s]+?)(?:\s+from|\s+for|\s+via|\s+with|\s+using|\.|$)",
        r"(?:transfer|send|pay)\s+to\s+([A-Za-z\s]+?)(?:\s+(?:rs\.?|inr|₹)|[0-9]|\s+from|\s+for|\s+via|\.|$)",
        r"(?:send|transfer)\s+money\s+to\s+([A-Za-z\s]+?)(?:\s+from|\s+for|\s+via|\.|$)",
        r"\bbeneficiary[:\s]+([A-Za-z\s]+?)(?:\s+from|\s+for|\.|$)",
        r"\bto\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b",
    ]
    for pat in bene_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            candidate = m.group(1).strip()
            candidate = re.sub(r"^(?:my|the)\s+", "", candidate, flags=re.IGNORECASE).strip()
            if is_valid_bene_candidate(candidate):
                result["beneficiary_name"] = candidate
                break

    if not result["beneficiary_name"] and messages:
        for msg in reversed(messages):
            msg_content = getattr(msg, "content", "")
            if isinstance(msg_content, str):
                for pat in bene_patterns:
                    m = re.search(pat, msg_content, re.IGNORECASE)
                    if m:
                        candidate = m.group(1).strip()
                        candidate = re.sub(
                            r"^(?:my|the)\s+", "", candidate, flags=re.IGNORECASE
                        ).strip()
                        if is_valid_bene_candidate(candidate):
                            result["beneficiary_name"] = candidate
                            break
                if result["beneficiary_name"]:
                    break

    # 3. Channel
    if re.search(r"\bneft\b", full_text, re.IGNORECASE):
        result["channel"] = "NEFT"
    elif re.search(r"\brtgs\b", full_text, re.IGNORECASE):
        result["channel"] = "RTGS"

    # 4. Remark
    rem_match = re.search(
        r"(?:for|remark[:\s]+|memo[:\s]+|reason[:\s]+)\s+([A-Za-z0-9\s]+?)(?:\.|$)",
        full_text,
        re.IGNORECASE,
    )
    if rem_match:
        result["remark"] = rem_match.group(1).strip()

    return result


def workflow_transfer_node(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """Transfer workflow node.
    
    1. Collects missing fields (beneficiary, amount) conversationally.
    2. Searches beneficiaries; handles 0 or multiple matches.
    3. Checks source account balance & transfer limits before drafting.
    4. Calls banking service POST /transfers to create PENDING_APPROVAL draft.
    5. Sets pending_action with masked summary to trigger approval_gate.
    """
    user_msg = state.get("user_message", "")
    messages = state.get("messages", [])
    extracted = extract_transfer_fields(user_msg, messages)

    amount_minor = extracted.get("amount_minor")
    bene_name = extracted.get("beneficiary_name")
    channel = extracted.get("channel", "IMPS")
    remark = extracted.get("remark") or "Fund Transfer"

    # 1. Missing fields check
    if not amount_minor and not bene_name:
        prompt = (
            "To transfer funds, please specify the recipient and the amount "
            "(for example: 'Transfer ₹5,000 to Rahul')."
        )
        return {
            "response": prompt,
            "messages": [AIMessage(content=prompt)],
            "approval_status": "NONE",
            "authentication_status": "NONE",
        }

    if not bene_name:
        amt_str = format_inr(amount_minor) if amount_minor else "the funds"
        prompt = f"Who would you like to transfer {amt_str} to?"
        return {
            "response": prompt,
            "messages": [AIMessage(content=prompt)],
            "approval_status": "NONE",
            "authentication_status": "NONE",
        }

    if not amount_minor:
        prompt = f"How much would you like to transfer to **{bene_name}**?"
        return {
            "response": prompt,
            "messages": [AIMessage(content=prompt)],
            "approval_status": "NONE",
            "authentication_status": "NONE",
        }

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

    # 2. Beneficiary Lookup
    try:
        benes = client.list_beneficiaries(q=bene_name)
    except Exception as exc:
        logger.error("Failed to fetch beneficiaries: %s", exc)
        benes = []

    if not benes:
        msg = (
            f"I couldn't find any beneficiary matching '**{bene_name}**'. "
            "Please check the name or add them as a new beneficiary first."
        )
        return {
            "response": msg,
            "messages": [AIMessage(content=msg)],
            "approval_status": "NONE",
            "authentication_status": "NONE",
        }

    # Filter for exact / closest match if multiple returned
    bene_lower = bene_name.strip().lower()
    exact_matches = [
        b for b in benes
        if b.get("name", "").strip().lower() == bene_lower
        or (b.get("nickname") and b.get("nickname", "").strip().lower() == bene_lower)
    ]
    target_bene = exact_matches[0] if exact_matches else None

    if not target_bene and len(benes) > 1:
        options = []
        for i, b in enumerate(benes[:5], 1):
            acc_m = b.get("account_number_masked") or f"XXXXXX{b.get('last4', 'XXXX')}"
            options.append(f"{i}. **{b.get('name')}** ({acc_m}, {b.get('bank_name', 'Bank')})")
        options_text = "\n".join(options)
        msg = (
            f"I found multiple beneficiaries matching '**{bene_name}**':\n{options_text}\n\n"
            "Please specify the full name of the recipient you'd like to pay."
        )
        return {
            "response": msg,
            "messages": [AIMessage(content=msg)],
            "approval_status": "NONE",
            "authentication_status": "NONE",
        }

    if not target_bene:
        target_bene = benes[0]

    # 3. Source Account Selection & Balance Check
    try:
        accounts = client.list_accounts()
    except Exception as exc:
        logger.error("Failed to list accounts: %s", exc)
        accounts = []

    active_accounts = [a for a in accounts if a.get("status") == "ACTIVE"]
    if not active_accounts:
        msg = "You do not have any active accounts available to initiate a transfer."
        return {
            "response": msg,
            "messages": [AIMessage(content=msg)],
            "approval_status": "NONE",
            "authentication_status": "NONE",
        }

    # Pick source account with sufficient balance
    source_acc = next(
        (a for a in active_accounts if a.get("balance_minor", 0) >= amount_minor),
        None,
    )
    if not source_acc:
        primary_acc = active_accounts[0]
        curr_bal_str = format_inr(primary_acc.get("balance_minor", 0))
        req_amt_str = format_inr(amount_minor)
        msg = (
            f"Insufficient balance. Your account has an available balance of "
            f"**{curr_bal_str}**, but this transfer requires **{req_amt_str}**."
        )
        return {
            "response": msg,
            "messages": [AIMessage(content=msg)],
            "approval_status": "NONE",
            "authentication_status": "NONE",
        }

    # 4. Limits Check
    try:
        limits = client.get_transfer_limits()
        per_txn_max = limits.get("per_transaction_limit_minor")
        daily_rem = limits.get("daily_remaining_minor")

        if per_txn_max and amount_minor > per_txn_max:
            limit_str = format_inr(per_txn_max)
            msg = (
                f"Transfer amount exceeds your per-transaction transfer limit of **{limit_str}**."
            )
            return {
                "response": msg,
                "messages": [AIMessage(content=msg)],
                "approval_status": "NONE",
                "authentication_status": "NONE",
            }

        if daily_rem is not None and amount_minor > daily_rem:
            rem_str = format_inr(daily_rem)
            msg = (
                f"Transfer amount exceeds your remaining daily transfer limit of **{rem_str}**."
            )
            return {
                "response": msg,
                "messages": [AIMessage(content=msg)],
                "approval_status": "NONE",
                "authentication_status": "NONE",
            }
    except Exception as exc:
        logger.warning("Could not verify transfer limits: %s", exc)

    # 5. Prepare Transfer Draft at Banking API
    idempotency_key = str(uuid.uuid4())
    draft_payload = {
        "source_account_id": source_acc["id"],
        "beneficiary_id": target_bene["id"],
        "amount_minor": amount_minor,
        "currency": "INR",
        "remark": remark,
        "channel": channel,
    }

    try:
        draft = client.prepare_transfer(draft_payload, idempotency_key=idempotency_key)
    except BankingClientError as exc:
        logger.error("BankingClient error preparing transfer: %s", exc.message)
        err_msg = f"Unable to prepare transfer: {exc.message}"
        return {
            "response": err_msg,
            "messages": [AIMessage(content=err_msg)],
            "error_code": exc.error_code,
        }
    except Exception as exc:
        logger.exception("Unexpected error preparing transfer: %s", exc)
        err_msg = f"Unable to prepare transfer: {exc}"
        return {
            "response": err_msg,
            "messages": [AIMessage(content=err_msg)],
            "error_code": "PREPARE_FAILED",
        }

    txn_id = draft.get("id")
    summary_hash = draft.get("summary_hash", "")
    fee_minor = draft.get("fee_minor", 0)
    total_debit_minor = draft.get("total_debit_minor", amount_minor + fee_minor)
    ref = draft.get("reference", "")
    bene_masked_acc = (
        target_bene.get("account_number_masked")
        or f"XXXXXX{target_bene.get('last4', 'XXXX')}"
    )

    # 6. Assemble PendingAction for approval gate
    summary_masked = {
        "beneficiary": target_bene["name"],
        "account_masked": bene_masked_acc,
        "amount": format_inr(amount_minor),
        "charges": format_inr(fee_minor),
        "total_debit": format_inr(total_debit_minor),
        "reference": ref,
    }

    pending_action: PendingAction = {
        "workflow": WorkflowType.TRANSFER.value,
        "banking_resource_id": txn_id,
        "summary_masked": summary_masked,
        "summary_hash": summary_hash,
        "stage": "CONFIRM",
        "action_data": {
            "txn_id": txn_id,
            "summary_hash": summary_hash,
            "idempotency_key": idempotency_key,
        },
    }

    review_msg = (
        f"Please review the transfer details:\n"
        f"- **Recipient**: {target_bene['name']} ({bene_masked_acc})\n"
        f"- **Amount**: {format_inr(amount_minor)}\n"
        f"- **Charges**: {format_inr(fee_minor)}\n"
        f"- **Total Debit**: {format_inr(total_debit_minor)}\n\n"
        "Please confirm or reject to proceed."
    )

    return {
        "pending_action": pending_action,
        "approval_status": ApprovalStatus.PENDING.value,
        "authentication_status": "NONE",
        "response": review_msg,
        "messages": [AIMessage(content=review_msg)],
    }
