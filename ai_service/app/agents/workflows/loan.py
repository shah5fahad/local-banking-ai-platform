"""Loan workflow: check offers, collect fields, evaluate eligibility, draft confirmation."""
from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import uuid
from typing import Any

from langchain_core.messages import AIMessage, AnyMessage
from langchain_core.runnables import RunnableConfig

from app.agents.state import GraphState, PendingAction
from app.agents.workflows.transfer import format_inr
from app.core.config import get_settings
from app.integrations.banking_client import BankingClient, BankingClientError
from app.models.approval import ApprovalStatus, WorkflowType

logger = logging.getLogger(__name__)

DEFAULT_RATE_BPS: dict[str, int] = {
    "PERSONAL": 1200,  # 12.00%
    "HOME": 850,       # 8.50%
    "AUTO": 950,       # 9.50%
}

TENURE_RANGES: dict[str, tuple[int, int]] = {
    "PERSONAL": (6, 60),
    "HOME": (12, 360),
    "AUTO": (12, 84),
}

MAX_AMOUNTS: dict[str, int] = {
    "PERSONAL": 50_000_000,    # Rs 5,00,000
    "HOME": 500_000_000,       # Rs 50,00,000
    "AUTO": 100_000_000,       # Rs 10,00,000
}


def calculate_emi_minor(principal_minor: int, rate_bps: int, tenure_months: int) -> int:
    """Calculate monthly EMI in minor units using reducing balance formula."""
    if tenure_months <= 0:
        return principal_minor
    annual_rate = rate_bps / 10000.0
    r = annual_rate / 12.0
    if r == 0:
        return int(math.ceil(principal_minor / tenure_months))

    factor = math.pow(1 + r, tenure_months)
    emi = principal_minor * r * factor / (factor - 1)
    return int(math.ceil(emi))


def parse_loan_type(text: str) -> str:
    """Determine loan type from user text."""
    lower = text.lower()
    if any(k in lower for k in ["home", "housing", "mortgage", "property"]):
        return "HOME"
    if any(k in lower for k in ["auto", "car", "vehicle", "bike", "two-wheeler"]):
        return "AUTO"
    return "PERSONAL"


def parse_tenure_months(text: str) -> int | None:
    """Extract tenure in months from text."""
    # e.g., 24 months, 24 mths, 24 mo
    m = re.search(r"\b(\d+)\s*(?:months?|mths?|mo)\b", text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    # e.g., 2 years, 3 yrs
    m = re.search(r"\b(\d+)\s*(?:years?|yrs?|yr)\b", text, re.IGNORECASE)
    if m:
        return int(m.group(1)) * 12
    # e.g., tenure: 24, tenure 24
    m = re.search(r"\btenure[:\s]+(\d+)\b", text, re.IGNORECASE)
    if m:
        return int(m.group(1))
    return None


def parse_number_to_minor(val_str: str) -> int | None:
    """Parse string number into minor units (paise), supporting lakh/lac."""
    val_str = val_str.strip().lower()
    m_lakh = re.match(r"^([0-9.]+)\s*(?:lakhs?|lac|lacs?)$", val_str)
    if m_lakh:
        try:
            return round(float(m_lakh.group(1)) * 100_000 * 100)
        except ValueError:
            return None
    cleaned = val_str.replace(",", "")
    try:
        val = float(cleaned)
        if val > 0:
            return round(val * 100)
    except ValueError:
        return None
    return None


def parse_income_to_minor(text: str) -> int | None:
    """Extract monthly income from text."""
    patterns = [
        r"(?:income|salary|earning|monthly\s+income)(?:\s+(?:is|of))?[:\s]+(?:rs\.?|inr|₹)?\s*([0-9,.]+\s*(?:lakhs?|lac|lacs?)|[0-9,]+(?:\.[0-9]{1,2})?)",
        r"(?:rs\.?|inr|₹)?\s*([0-9,.]+\s*(?:lakhs?|lac|lacs?)|[0-9,]+(?:\.[0-9]{1,2})?)\s*(?:per\s+month|monthly|\/month|\/mo)",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            val = parse_number_to_minor(m.group(1))
            if val:
                return val
    return None


def parse_loan_amount_to_minor(text: str, monthly_income_minor: int | None = None) -> int | None:
    """Extract requested loan amount from text."""
    patterns = [
        r"(?:loan\s+of|apply\s+for|borrow|amount[:\s]+)\s*(?:rs\.?|inr|₹)?\s*([0-9,.]+\s*(?:lakhs?|lac|lacs?)|[0-9,]+(?:\.[0-9]{1,2})?)",
        r"(?:rs\.?|inr|₹)\s*([0-9,.]+\s*(?:lakhs?|lac|lacs?)|[0-9,]+(?:\.[0-9]{1,2})?)\s*(?:personal|home|auto)?\s*loan",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            val = parse_number_to_minor(m.group(1))
            if val and val != monthly_income_minor:
                return val

    # Fallback to currency pattern
    curr_pattern = re.compile(
        r"(?:(?:rs\.?|inr|₹)\s*)([0-9,.]+\s*(?:lakhs?|lac|lacs?)|[0-9,]+(?:\.[0-9]{1,2})?)|([0-9,.]+\s*(?:lakhs?|lac|lacs?)|[0-9,]+(?:\.[0-9]{1,2})?)\s*(?:rs\.?|inr|₹|rupees)",
        re.IGNORECASE,
    )
    for match in curr_pattern.finditer(text):
        val_str = match.group(1) or match.group(2)
        val = parse_number_to_minor(val_str)
        if val and val != monthly_income_minor:
            return val

    # Standalone number (>= 1,000 to avoid confusing with tenure)
    plain_pattern = re.compile(
        r"\b([0-9]{1,3}(?:,[0-9]{2,3})+(?:\.[0-9]{1,2})?|[0-9]+(?:\.[0-9]{1,2})?)\b"
    )
    for match in plain_pattern.finditer(text):
        val_str = match.group(1).replace(",", "")
        try:
            val_float = float(val_str)
            minor = round(val_float * 100)
            if minor > 0 and minor != monthly_income_minor and val_float >= 1000:
                return minor
        except ValueError:
            continue

    return None


def extract_employment_and_employer(text: str) -> tuple[str, str]:
    """Extract employment type and employer name from text."""
    lower = text.lower()
    emp_type = "SALARIED"
    if "self-employed" in lower or "self employed" in lower or "freelancer" in lower:
        emp_type = "SELF_EMPLOYED"
    elif "business" in lower or "entrepreneur" in lower:
        emp_type = "BUSINESS"

    employer = "Private Limited"
    emp_patterns = [
        r"(?:at|employer[:\s]+|company[:\s]+|working\s+at)\s+([A-Za-z0-9\s&.,'-]+?)(?:\s+for|\s+with|\s+salary|\s+income|\.|$)",
    ]
    for pat in emp_patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            cand = m.group(1).strip()
            # Clean common trailing punctuation or words
            cand = re.sub(r"^(?:my|the)\s+", "", cand, flags=re.IGNORECASE).strip()
            if len(cand) >= 2 and cand.lower() not in {"months", "years", "rs", "inr", "loan", "salary", "income"}:
                employer = cand
                break

    if emp_type == "SELF_EMPLOYED" and employer == "Private Limited":
        employer = "Self-Employed"

    return emp_type, employer


def extract_loan_fields(
    text: str, messages: list[AnyMessage] | None = None
) -> dict[str, Any]:
    """Extract loan parameters across current message and conversational history."""
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

    loan_type = parse_loan_type(full_text)
    monthly_income = parse_income_to_minor(text) or parse_income_to_minor(full_text)
    amount_minor = parse_loan_amount_to_minor(text, monthly_income) or parse_loan_amount_to_minor(
        full_text, monthly_income
    )
    tenure_months = parse_tenure_months(text) or parse_tenure_months(full_text)
    emp_type, employer = extract_employment_and_employer(full_text)

    return {
        "loan_type": loan_type,
        "amount_minor": amount_minor,
        "tenure_months": tenure_months,
        "monthly_income_minor": monthly_income,
        "employment_type": emp_type,
        "employer": employer,
    }


def workflow_loan_node(state: GraphState, config: RunnableConfig) -> dict[str, Any]:
    """Loan application workflow node.

    1. Displays pre-approved offers if available when parameters are missing.
    2. Collects missing fields (amount, tenure, income, employment) conversationally.
    3. Evaluates eligibility through BankingClient (POST /loans/eligibility).
    4. Prepares confirmation PendingAction with estimated reducing-balance EMI and summary_hash.
    """
    user_msg = state.get("user_message", "")
    messages = state.get("messages", [])
    extracted = extract_loan_fields(user_msg, messages)

    loan_type = extracted["loan_type"]
    amount_minor = extracted["amount_minor"]
    tenure_months = extracted["tenure_months"]
    monthly_income_minor = extracted["monthly_income_minor"]
    employment_type = extracted["employment_type"]
    employer = extracted["employer"]

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

    # 1. Fetch available pre-approved offers
    offers: list[dict] = []
    try:
        offers = client.list_loan_offers()
    except Exception as exc:
        logger.warning("Could not list loan offers: %s", exc)

    active_offers = [o for o in offers if o.get("status") == "ACTIVE"]

    # 2. Check for missing fields
    missing_all = amount_minor is None and tenure_months is None and monthly_income_minor is None
    if missing_all:
        if active_offers:
            offers_list = []
            for o in active_offers:
                max_amt = format_inr(o.get("max_amount_minor", 0))
                rate_pct = o.get("rate_bps", 1200) / 100.0
                min_t = o.get("min_tenure_months", 6)
                max_t = o.get("max_tenure_months", 60)
                ltype_label = o.get("loan_type", "PERSONAL").capitalize()
                offers_list.append(
                    f"- **{ltype_label} Loan Offer**: Up to **{max_amt}** at **{rate_pct:.2f}% p.a.** "
                    f"(tenure {min_t}–{max_t} months)"
                )
            offers_text = "\n".join(offers_list)
            prompt = (
                f"You have the following pre-approved loan offers available:\n{offers_text}\n\n"
                "To apply, please provide the desired loan amount, tenure in months, and your "
                "monthly income (for example: 'Apply for ₹2,00,000 for 24 months, monthly income ₹50,000')."
            )
        else:
            prompt = (
                "To apply for a loan, please specify the loan type (Personal, Home, Auto), "
                "amount, tenure in months, and your monthly income (for example: "
                "'Apply for a ₹2,00,000 personal loan for 24 months with monthly income ₹50,000')."
            )
        return {
            "response": prompt,
            "messages": [AIMessage(content=prompt)],
            "approval_status": "NONE",
            "authentication_status": "NONE",
        }

    if amount_minor is None:
        prompt = f"How much would you like to borrow for your **{loan_type.capitalize()} Loan**?"
        return {
            "response": prompt,
            "messages": [AIMessage(content=prompt)],
            "approval_status": "NONE",
            "authentication_status": "NONE",
        }

    if tenure_months is None:
        min_t, max_t = TENURE_RANGES.get(loan_type, (6, 60))
        prompt = (
            f"What tenure would you prefer for your {loan_type.capitalize()} Loan? "
            f"(Allowed tenure is between {min_t} and {max_t} months, e.g. 12, 24, 36, or 60 months)."
        )
        return {
            "response": prompt,
            "messages": [AIMessage(content=prompt)],
            "approval_status": "NONE",
            "authentication_status": "NONE",
        }

    if monthly_income_minor is None:
        prompt = (
            "What is your monthly income? (This is required to check EMI affordability and eligibility)."
        )
        return {
            "response": prompt,
            "messages": [AIMessage(content=prompt)],
            "approval_status": "NONE",
            "authentication_status": "NONE",
        }

    # 3. Check for matching pre-approved offer
    matching_offer = next(
        (o for o in active_offers if o.get("loan_type", "").upper() == loan_type),
        None,
    )
    offer_id = matching_offer.get("id") if matching_offer else None
    rate_bps = matching_offer.get("rate_bps") if matching_offer else DEFAULT_RATE_BPS.get(loan_type, 1200)

    # 4. Evaluate Eligibility via Banking API
    elig_payload = {
        "loan_type": loan_type,
        "amount_minor": amount_minor,
        "tenure_months": tenure_months,
        "monthly_income_minor": monthly_income_minor,
    }

    try:
        elig_res = client.check_loan_eligibility(elig_payload)
    except BankingClientError as exc:
        logger.error("BankingClient error checking loan eligibility: %s", exc.message)
        err_msg = f"Unable to check loan eligibility: {exc.message}"
        return {
            "response": err_msg,
            "messages": [AIMessage(content=err_msg)],
            "error_code": exc.error_code,
        }
    except Exception as exc:
        logger.exception("Unexpected error checking loan eligibility: %s", exc)
        err_msg = f"Unable to check loan eligibility: {exc}"
        return {
            "response": err_msg,
            "messages": [AIMessage(content=err_msg)],
            "error_code": "ELIGIBILITY_CHECK_FAILED",
        }

    if not elig_res.get("eligible", False):
        reasons = elig_res.get("reasons", [])
        reasons_text = "\n".join(f"- {r}" for r in reasons) if reasons else "- Does not satisfy credit affordability criteria."
        msg = (
            f"Based on our eligibility evaluation, we are unable to process this application for a "
            f"**{loan_type.capitalize()} Loan**:\n{reasons_text}\n\n"
            "You may consider applying for a lower loan amount or extending the tenure."
        )
        return {
            "response": msg,
            "messages": [AIMessage(content=msg)],
            "approval_status": "NONE",
            "authentication_status": "NONE",
        }

    # 5. Calculate EMI and prepare confirmation
    emi_minor = calculate_emi_minor(amount_minor, rate_bps, tenure_months)
    idempotency_key = str(uuid.uuid4())

    summary_masked = {
        "loan_type": f"{loan_type.capitalize()} Loan",
        "amount": format_inr(amount_minor),
        "tenure": f"{tenure_months} months",
        "interest_rate": f"{rate_bps / 100.0:.2f}% p.a.",
        "estimated_emi": format_inr(emi_minor),
        "monthly_income": format_inr(monthly_income_minor),
        "employment": f"{employment_type} ({employer})",
    }

    summary_bytes = json.dumps(summary_masked, sort_keys=True).encode("utf-8")
    summary_hash = hashlib.sha256(summary_bytes).hexdigest()

    pending_action: PendingAction = {
        "workflow": WorkflowType.LOAN.value,
        "banking_resource_id": offer_id or f"loan-{uuid.uuid4().hex[:8]}",
        "summary_masked": summary_masked,
        "summary_hash": summary_hash,
        "stage": "CONFIRM",
        "action_data": {
            "offer_id": offer_id,
            "loan_type": loan_type,
            "amount_minor": amount_minor,
            "tenure_months": tenure_months,
            "employment_type": employment_type,
            "employer": employer,
            "monthly_income_minor": monthly_income_minor,
            "rate_bps": rate_bps,
            "emi_minor": emi_minor,
            "summary_hash": summary_hash,
            "idempotency_key": idempotency_key,
        },
    }

    review_msg = (
        f"Please review your loan application details:\n"
        f"- **Loan Type**: {summary_masked['loan_type']}\n"
        f"- **Requested Amount**: {summary_masked['amount']}\n"
        f"- **Tenure**: {summary_masked['tenure']}\n"
        f"- **Interest Rate**: {summary_masked['interest_rate']}\n"
        f"- **Estimated Monthly EMI**: {summary_masked['estimated_emi']}\n"
        f"- **Monthly Income**: {summary_masked['monthly_income']}\n"
        f"- **Employment**: {summary_masked['employment']}\n\n"
        "Please confirm or reject to proceed with your application."
    )

    return {
        "pending_action": pending_action,
        "approval_status": ApprovalStatus.PENDING.value,
        "authentication_status": "NONE",
        "response": review_msg,
        "messages": [AIMessage(content=review_msg)],
    }
