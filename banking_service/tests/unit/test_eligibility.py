"""Unit tests for loan eligibility rules and reducing balance EMI formula (T2.10)."""
from app.services.eligibility_rules import calculate_emi_minor, check_eligibility


class TestLoanEligibility:
    def test_emi_calculation(self) -> None:
        # Principal: Rs 100,000 (10,000,000 minor)
        # Rate: 12.00% (1200 bps)
        # Tenure: 12 months
        emi = calculate_emi_minor(10_000_000, 1200, 12)
        # Monthly r = 0.01
        # EMI = 100000 * 0.01 * (1.01^12) / (1.01^12 - 1) approx 8884.87 -> 888,488 paise
        assert 888_000 <= emi <= 889_000

    def test_eligibility_success(self) -> None:
        # Income: Rs 100,000/mo (10,000,000 minor)
        # Personal loan Rs 200,000 (20,000,000 minor), 24 months, 0 active loans
        eligible, max_amount, reasons = check_eligibility(
            loan_type="PERSONAL",
            amount_minor=20_000_000,
            tenure_months=24,
            monthly_income_minor=10_000_000,
            existing_loans=0,
            rate_bps=1200,
        )
        assert eligible is True
        assert len(reasons) == 0

    def test_eligibility_fails_on_active_loans(self) -> None:
        eligible, _, reasons = check_eligibility(
            loan_type="PERSONAL",
            amount_minor=10_000_000,
            tenure_months=24,
            monthly_income_minor=10_000_000,
            existing_loans=3,
        )
        assert eligible is False
        assert any("already has 3 or more active loans" in r for r in reasons)

    def test_eligibility_fails_on_excessive_emi(self) -> None:
        # Income: Rs 20,000 (2,000,000 minor)
        # Loan: Rs 400,000 (40,000,000 minor), 12 months -> EMI approx Rs 35,000 > 40% of 20,000
        eligible, _, reasons = check_eligibility(
            loan_type="PERSONAL",
            amount_minor=40_000_000,
            tenure_months=12,
            monthly_income_minor=2_000_000,
            existing_loans=0,
        )
        assert eligible is False
        assert any("exceeds 40% of monthly income" in r for r in reasons)
