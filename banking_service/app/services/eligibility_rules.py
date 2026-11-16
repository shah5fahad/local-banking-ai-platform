"""Eligibility rules engine for loan applications."""
from __future__ import annotations

import math

TENURE_RANGES: dict[str, tuple[int, int]] = {
    "PERSONAL": (6, 60),
    "HOME": (12, 360),
    "AUTO": (12, 84),
    "CAR": (12, 84),
}

MAX_AMOUNTS: dict[str, int] = {
    "PERSONAL": 50_000_000,    # Rs 500,000
    "HOME": 500_000_000,       # Rs 5,000,000
    "AUTO": 150_000_000,       # Rs 1,500,000
    "CAR": 150_000_000,        # Rs 1,500,000
}

DEFAULT_RATE_BPS: dict[str, int] = {
    "PERSONAL": 1200,   # 12.00%
    "HOME": 850,        # 8.50%
    "AUTO": 950,        # 9.50%
    "CAR": 950,         # 9.50%
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


def check_eligibility(
    loan_type: str,
    amount_minor: int,
    tenure_months: int,
    monthly_income_minor: int,
    existing_loans: int,
    rate_bps: int | None = None,
) -> tuple[bool, int, list[str]]:
    """Evaluate loan eligibility against domain rules.

    Returns:
        (eligible: bool, max_amount_minor: int, reasons: list[str])
    """
    reasons: list[str] = []
    l_type = loan_type.upper()
    max_type_amount = MAX_AMOUNTS.get(l_type, 50_000_000)

    # Rule 3: Existing active loans < 3
    if existing_loans >= 3:
        reasons.append("Applicant already has 3 or more active loans.")

    # Rule 4: Amount within type-specific maximum
    if amount_minor > max_type_amount:
        reasons.append(
            f"Requested amount ({amount_minor} minor) exceeds the maximum allowed for {l_type} "
            f"loans ({max_type_amount} minor)."
        )

    # Rule 2: Tenure within allowed range per loan type
    min_tenure, max_tenure = TENURE_RANGES.get(l_type, (6, 60))
    if tenure_months < min_tenure or tenure_months > max_tenure:
        reasons.append(
            f"Tenure of {tenure_months} months is outside allowed range "
            f"[{min_tenure}, {max_tenure}] for {l_type} loans."
        )

    # Rule 1: Monthly EMI <= 40% of monthly income
    bps = rate_bps or DEFAULT_RATE_BPS.get(l_type, 1200)
    emi = calculate_emi_minor(amount_minor, bps, tenure_months)
    max_allowed_emi = int(monthly_income_minor * 0.40)
    if emi > max_allowed_emi:
        reasons.append(
            f"Estimated EMI of {emi} minor units exceeds 40% of monthly income ({max_allowed_emi} minor units)."
        )

    eligible = len(reasons) == 0
    return eligible, max_type_amount, reasons
