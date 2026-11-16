"""Beneficiary workflow: collect fields, validate, check duplicates, create draft approval."""
from __future__ import annotations

import hashlib
import logging
import re
import uuid
from typing import Any

from langchain_core.messages import AIMessage, AnyMessage
from langchain_core.runnables import RunnableConfig

from app.agents.state import GraphState, PendingAction
from app.core.config import get_settings
from app.integrations.banking_client import BankingClient
from app.models.approval import ApprovalStatus, WorkflowType

logger = logging.getLogger(__name__)

# Common bank names inferred from 4-character IFSC prefixes
KNOWN_IFSC_BANKS: dict[str, str] = {
    "HDFC": "HDFC Bank",
    "ICIC": "ICICI Bank",
    "SBIN": "State Bank of India",
    "UTIB": "Axis Bank",
    "PUNB": "Punjab National Bank",
    "KKBK": "Kotak Mahindra Bank",
    "BARB": "Bank of Baroda",
    "CNRB": "Canara Bank",
    "UBIN": "Union Bank of India",
    "IDIB": "Indian Bank",
    "YESB": "Yes Bank",
    "INDB": "IndusInd Bank",
}


def extract_beneficiary_fields(
    text: str, messages: list[AnyMessage] | None = None
) -> dict[str, str | None]:
    """Extract beneficiary details from user input and recent conversation history."""
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

    result: dict[str, str | None] = {
        "name": None,
        "account_number": None,
        "ifsc": None,
        "bank_name": None,
        "nickname": None,
    }

    # 1. Extract IFSC
    ifsc_match = re.search(
        r"\bifsc(?:\s+is|[:\s=])+\s*([A-Za-z0-9]+)\b", full_text, re.IGNORECASE
    )
    if ifsc_match and ifsc_match.group(1).upper() != "IS":
        result["ifsc"] = ifsc_match.group(1).upper()
    else:
        code_match = re.search(r"\b([A-Za-z]{4}0[A-Za-z0-9]{6})\b", full_text)
        if code_match:
            result["ifsc"] = code_match.group(1).upper()

    # 2. Extract Account Number
    acc_match = re.search(
        r"(?:account(?:\s*number|\s*no|\s*num)?|acct|acc|a/c)(?:\s+is|[:\s=#])+\s*([A-Za-z0-9]+)\b",
        full_text,
        re.IGNORECASE,
    )
    if acc_match:
        val = acc_match.group(1)
        if val.lower() not in ("is", "number", "no", "num", "a", "the"):
            result["account_number"] = val
    if not result["account_number"]:
        # Fallback to standalone 9-18 digit sequence
        num_match = re.search(r"\b(\d{9,18})\b", full_text)
        if num_match:
            result["account_number"] = num_match.group(1)

    # 3. Extract Nickname
    nick_match = re.search(
        r"\bnickname[:\s]+([A-Za-z0-9_\-]+)\b", full_text, re.IGNORECASE
    )
    if nick_match:
        result["nickname"] = nick_match.group(1).strip()

    # 4. Extract Bank Name
    bank_match = re.search(
        r"(?:bank[:\s]+)?([A-Za-z0-9\s]+?)\s+Bank\b", full_text, re.IGNORECASE
    )
    if bank_match:
        b_name = bank_match.group(1).strip()
        b_name = re.sub(r"^(?:bank|the|my)\s+", "", b_name, flags=re.IGNORECASE).strip()
        result["bank_name"] = f"{b_name} Bank"
    elif result["ifsc"]:
        prefix = result["ifsc"][:4]
        if prefix in KNOWN_IFSC_BANKS:
            result["bank_name"] = KNOWN_IFSC_BANKS[prefix]

    # 5. Extract Beneficiary Name
    # Patterns like: "add beneficiary Rahul Sharma, ...", "name: Rahul Sharma", "to Rahul Sharma"
    name_patterns = [
        r"(?:add|new)?\s*beneficiary\s*(?:named?|for|to)?\s+([A-Za-z\s]+?)(?:,|\.|\baccount\b|\bifsc\b|\bbank\b|\bnickname\b|$)",
        r"\bname[:\s]+([A-Za-z\s]+?)(?:,|\.|\baccount\b|\bifsc\b|\bbank\b|\bnickname\b|$)",
        r"\bto\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)\b",
    ]
    for pat in name_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            candidate = m.group(1).strip()
            # Clean noise words
            candidate = re.sub(
                r"^(?:a|the|new|please|my)\s+", "", candidate, flags=re.IGNORECASE
            ).strip()
            if candidate and len(candidate) >= 2 and not candidate.lower().startswith("bank"):
                result["name"] = candidate
                break

    if not result["name"] and messages:
        # Check in previous user messages
        for msg in reversed(messages):
            msg_content = getattr(msg, "content", "")
            if isinstance(msg_content, str):
                for pat in name_patterns:
                    m = re.search(pat, msg_content, re.IGNORECASE)
                    if m:
                        candidate = m.group(1).strip()
                        candidate = re.sub(
                            r"^(?:a|the|new|please|my)\s+", "", candidate, flags=re.IGNORECASE
                        ).strip()
                        is_valid_candidate = (
                            bool(candidate)
                            and len(candidate) >= 2
                            and not candidate.lower().startswith("bank")
                        )
                        if is_valid_candidate:
                            result["name"] = candidate
                            break
                if result["name"]:
                    break

    return result


def workflow_beneficiary_node(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """Beneficiary workflow node.
    
    1. Collects missing fields conversationally.
    2. Validates format (account number 9-18 digits, IFSC pattern).
    3. Checks duplicate beneficiaries via BankingClient.
    4. Computes canonical payload hash and creates approval challenge.
    5. Sets pending_action with masked summary to trigger approval_gate.
    """
    user_msg = state.get("user_message", "")
    messages = state.get("messages", [])
    extracted = extract_beneficiary_fields(user_msg, messages)

    name = extracted.get("name")
    account_number = extracted.get("account_number")
    ifsc = extracted.get("ifsc")
    bank_name = extracted.get("bank_name")
    nickname = extracted.get("nickname") or name

    # 1. Check for missing mandatory fields
    missing_fields: list[str] = []
    if not name:
        missing_fields.append("beneficiary's full name")
    if not account_number:
        missing_fields.append("account number")
    if not ifsc:
        missing_fields.append("IFSC code")
    if not bank_name:
        missing_fields.append("bank name")

    if missing_fields:
        if len(missing_fields) == 4:
            prompt = (
                "To add a new beneficiary, please provide their full name, "
                "account number, IFSC code, and bank name."
            )
        else:
            fields_str = ", ".join(missing_fields)
            prompt = (
                f"To add beneficiary **{name or 'this contact'}**, please provide: {fields_str}."
            )
        return {
            "response": prompt,
            "messages": [AIMessage(content=prompt)],
            "approval_status": "NONE",
            "authentication_status": "NONE",
        }

    # 2. Format validation
    # Account number must be 9-18 numeric digits
    if not re.match(r"^\d{9,18}$", account_number or ""):
        err_msg = (
            "The account number must be between 9 and 18 numeric digits. "
            "Please check and provide a valid account number."
        )
        return {
            "response": err_msg,
            "messages": [AIMessage(content=err_msg)],
            "approval_status": "NONE",
            "authentication_status": "NONE",
        }

    # IFSC validation
    if not re.match(r"^[A-Z]{4}0[A-Z0-9]{6}$", ifsc or ""):
        err_msg = (
            f"The IFSC code '{ifsc}' is invalid. It must consist of 4 letters, '0', "
            "and 6 alphanumeric characters (for example, HDFC0001234)."
        )
        return {
            "response": err_msg,
            "messages": [AIMessage(content=err_msg)],
            "approval_status": "NONE",
            "authentication_status": "NONE",
        }

    cfg = config.get("configurable", {}) if config else {}
    access_token = cfg.get("access_token", "")
    settings = get_settings()

    # 3. Duplicate check via BankingClient
    if access_token:
        try:
            client = BankingClient(settings=settings, access_token=access_token)
            existing_benes = client.list_beneficiaries(q=name)
            last4 = account_number[-4:]
            for b in existing_benes:
                if (
                    b.get("last4") == last4
                    and b.get("ifsc", "").upper() == ifsc.upper()
                    and b.get("status") == "ACTIVE"
                ):
                    dup_msg = (
                        f"A beneficiary with name '{name}' and account ending in {last4} "
                        f"({ifsc}) is already registered."
                    )
                    return {
                        "response": dup_msg,
                        "messages": [AIMessage(content=dup_msg)],
                        "approval_status": "NONE",
                        "authentication_status": "NONE",
                    }
        except Exception as exc:
            logger.warning("Beneficiary duplicate check skipped or failed: %s", exc)

    # 4. Canonical payload hash
    # Bound to: {name, nickname, account_number, ifsc, bank_name}
    norm_payload = (
        f"{name.strip()}|{(nickname or '').strip()}|"
        f"{account_number.strip()}|{ifsc.strip().upper()}|{bank_name.strip()}"
    )
    payload_hash = hashlib.sha256(norm_payload.encode("utf-8")).hexdigest()

    # 5. Create approval challenge via Banking API
    challenge_id: str | None = None
    if access_token:
        try:
            client = BankingClient(settings=settings, access_token=access_token)
            ch_resp = client.create_approval_challenge("BENEFICIARY_CREATE", payload_hash)
            challenge_id = ch_resp.get("challenge_id")
        except Exception as exc:
            logger.warning("Could not create approval challenge at banking service: %s", exc)

    if not challenge_id:
        challenge_id = f"ch-{uuid.uuid4().hex[:12]}"

    # 6. Assemble PendingAction for approval gate
    last4 = account_number[-4:]
    masked_account = f"XXXXXX{last4}"
    summary_masked = {
        "beneficiary_name": name,
        "account_masked": masked_account,
        "ifsc": ifsc.upper(),
        "bank_name": bank_name,
        "nickname": nickname,
    }

    pending_action: PendingAction = {
        "workflow": WorkflowType.BENEFICIARY.value,
        "banking_resource_id": challenge_id,
        "summary_masked": summary_masked,
        "summary_hash": payload_hash,
        "stage": "CONFIRM",
        "action_data": {
            "name": name,
            "nickname": nickname,
            "account_number": account_number,
            "ifsc": ifsc.upper(),
            "bank_name": bank_name,
        },
    }

    review_msg = (
        f"Please review the beneficiary details:\n"
        f"- **Name**: {name}\n"
        f"- **Account**: {masked_account}\n"
        f"- **IFSC**: {ifsc.upper()}\n"
        f"- **Bank**: {bank_name}\n"
        f"- **Nickname**: {nickname}\n\n"
        "Please confirm to proceed with adding this beneficiary."
    )

    return {
        "pending_action": pending_action,
        "approval_status": ApprovalStatus.PENDING.value,
        "authentication_status": "NONE",
        "response": review_msg,
        "messages": [AIMessage(content=review_msg)],
    }
