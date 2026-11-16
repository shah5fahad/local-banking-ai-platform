"""Fee calculation strategy for banking channels."""
from __future__ import annotations


def compute_fee(amount_minor: int, channel: str | None = None) -> int:
    """Compute transfer fee in minor units (paise).

    IMPS: Rs 5 (500 paise) for amount < 10,000 INR (1,000,000 paise), else Rs 10 (1000 paise).
    NEFT: flat Rs 2.50 (250 paise).
    RTGS: flat Rs 20 (2000 paise).
    Default/Other: 500 paise.
    """
    if not channel:
        return 500

    channel_upper = channel.upper()
    if channel_upper == "IMPS":
        if amount_minor < 1_000_000:
            return 500
        return 1000
    elif channel_upper == "NEFT":
        return 250
    elif channel_upper == "RTGS":
        return 2000
    elif channel_upper == "CARD_PAYMENT":
        return 0
    else:
        return 500
