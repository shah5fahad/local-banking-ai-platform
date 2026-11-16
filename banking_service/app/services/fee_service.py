"""Fee calculation strategy for banking channels."""
from __future__ import annotations


class FeeStrategy:
    """Calculates fee minor units based on payment channel and amount."""

    @staticmethod
    def calculate_fee(channel: str, amount_minor: int) -> int:
        channel_upper = channel.upper()
        if channel_upper == "IMPS":
            # Flat fee of Rs 5.00 (500 paise) for IMPS
            return 500
        elif channel_upper == "NEFT":
            # Free for normal NEFT
            return 0
        elif channel_upper == "RTGS":
            # Rs 25.00 for RTGS
            return 2500
        elif channel_upper == "CARD_PAYMENT":
            return 0
        return 0
