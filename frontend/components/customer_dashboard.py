"""Customer dashboard component displaying bank accounts, credit cards, and loan offers (T7.4)."""
from __future__ import annotations

from typing import Any

import streamlit as st

from clients.banking_client import BankingAPIError, BankingClient
from components.admin_dashboard import format_currency_inr


def render_customer_dashboard(banking_client: BankingClient, access_token: str) -> None:
    """Render comprehensive customer dashboard with bank accounts, cards, and loan offers."""
    st.markdown("### 📊 My Financial Dashboard")

    col_btn, _ = st.columns([1, 4])
    with col_btn:
        if st.button("🔄 Refresh Dashboard", key="cust_dash_refresh_btn", use_container_width=True):
            st.rerun()

    # Fetch aggregated dashboard data
    if access_token == "mock_token":
        dash_data = {
            "accounts": [
                {
                    "id": "acc-mock-1",
                    "bank_name": "Local Bank",
                    "account_number_masked": "XXXXXX1234",
                    "account_type": "SAVINGS",
                    "ifsc": "LOCL0001001",
                    "branch_name": "Main Branch",
                    "balance_minor": 10_000_000,
                    "status": "ACTIVE",
                    "verification_status": "VERIFIED",
                }
            ],
            "cards": [
                {
                    "id": "card-mock-1",
                    "network": "VISA",
                    "last4": "4321",
                    "card_number_masked": "XXXX-XXXX-XXXX-4321",
                    "credit_limit_minor": 20_000_000,
                    "outstanding_minor": 0,
                    "status": "ACTIVE",
                    "expiry_date": "12/29",
                }
            ],
            "loan_offers": [
                {
                    "id": "loan-mock-1",
                    "loan_type": "HOME",
                    "name": "Pre-Approved Home Loan",
                    "max_amount_minor": 500_000_000,
                    "rate_bps": 850,
                    "min_tenure_months": 60,
                    "max_tenure_months": 240,
                    "terms": "Floating rate linked to repo.",
                    "status": "ACTIVE",
                }
            ],
            "total_balance_minor": 10_000_000,
            "total_credit_limit_minor": 20_000_000,
            "total_available_credit_minor": 20_000_000,
        }
    else:
        try:
            dash_data = banking_client.get_customer_dashboard(access_token)
        except BankingAPIError as be:
            st.error(f"Failed to load dashboard data: {be.message}")
            dash_data = {}
        except Exception:
            dash_data = {}

    accounts = dash_data.get("accounts", [])
    cards = dash_data.get("cards", [])
    loan_offers = dash_data.get("loan_offers", [])
    total_balance = dash_data.get("total_balance_minor", 0)
    total_credit_limit = dash_data.get("total_credit_limit_minor", 0)
    total_available_credit = dash_data.get("total_available_credit_minor", 0)

    # 1. Summary Metrics Bar
    m1, m2, m3, m4 = st.columns(4)
    with m1:
        st.metric("Total Bank Balance", format_currency_inr(total_balance))
    with m2:
        st.metric("Total Credit Limit", format_currency_inr(total_credit_limit))
    with m3:
        st.metric("Available Card Limit", format_currency_inr(total_available_credit))
    with m4:
        st.metric("Pre-Approved Loans", f"{len(loan_offers)} Active")

    st.write("")

    # 2. Detailed Tabs
    tab_accounts, tab_cards, tab_loans = st.tabs(
        [
            f"🏦 Bank Accounts ({len(accounts)})",
            f"💳 Credit Cards ({len(cards)})",
            f"💰 Loan Offers ({len(loan_offers)})",
        ]
    )

    # Tab 1: Bank Accounts
    with tab_accounts:
        if not accounts:
            st.info("No bank accounts linked yet. Visit Direct Banking to link an account.")
        else:
            for acc in accounts:
                acc_id = acc.get("id", "")
                bank_name = acc.get("bank_name", "Local Bank")
                branch = acc.get("branch_name") or "Main Branch"
                masked_num = acc.get("account_number_masked", "XXXXXX0000")
                acc_type = acc.get("account_type", "SAVINGS")
                ifsc = acc.get("ifsc", "LOCL0001001")
                status = acc.get("status", "ACTIVE")
                ver_status = acc.get("verification_status", "VERIFIED")
                bal_minor = acc.get("balance_minor", 0)

                with st.container(border=True):
                    c_info, c_bal, c_action = st.columns([3, 2, 1.5])
                    with c_info:
                        st.markdown(f"#### 🏦 {bank_name} — `{masked_num}`")
                        st.caption(
                            f"**Type:** `{acc_type}` &nbsp;|&nbsp; **IFSC:** `{ifsc}` &nbsp;|&nbsp; "
                            f"**Branch:** {branch} &nbsp;|&nbsp; **Status:** `{status}` &nbsp;|&nbsp; "
                            f"**Verification:** `{ver_status}`"
                        )
                    with c_bal:
                        st.metric("Available Balance", format_currency_inr(bal_minor))
                    with c_action:
                        st.write("")
                        if st.button("Check Balance", key=f"dash_btn_bal_{acc_id}", use_container_width=True):
                            try:
                                fresh = banking_client.get_account_balance(acc_id, access_token)
                                st.success(f"Balance: **{format_currency_inr(fresh.get('available_minor'))}**")
                            except Exception as ex:
                                st.error(f"Error: {ex}")

    # Tab 2: Credit Cards
    with tab_cards:
        if not cards:
            st.info("No credit cards provisioned for your account yet.")
        else:
            for c in cards:
                card_id = c.get("id", "")
                network = c.get("network", "VISA")
                last4 = c.get("last4", "0000")
                masked_card = c.get("card_number_masked") or f"XXXX-XXXX-XXXX-{last4}"
                limit_minor = c.get("credit_limit_minor", 0)
                outstanding_minor = c.get("outstanding_minor", 0)
                available_minor = max(0, limit_minor - outstanding_minor)
                status = c.get("status", "ACTIVE")
                expiry = c.get("expiry_date") or "12/29"

                with st.container(border=True):
                    c_cinfo, c_clim, c_cact = st.columns([3, 2, 2])
                    with c_cinfo:
                        st.markdown(f"#### 💳 {network} Credit Card — `{masked_card}`")
                        st.caption(
                            f"**Status:** `{status}` &nbsp;|&nbsp; **Expires:** `{expiry}` &nbsp;|&nbsp; "
                            f"**Network:** {network}"
                        )
                    with c_clim:
                        st.metric("Available Credit", format_currency_inr(available_minor))
                        st.caption(f"Limit: **{format_currency_inr(limit_minor)}** | Used: {format_currency_inr(outstanding_minor)}")
                    with c_cact:
                        st.write("")
                        with st.expander("👁️ View Full Card Details", expanded=False):
                            try:
                                sens = banking_client.get_card_sensitive_details(card_id, access_token)
                                st.markdown(f"**Card Number:** `{sens.get('card_number')}`")
                                st.markdown(f"**Expiry Date:** `{sens.get('expiry_date')}`")
                                st.markdown(f"**CVV Code:** `***` ({sens.get('cvv')})")
                                st.caption("🔒 Encrypted with AES-GCM; visible only to cardholder.")
                            except Exception as exc:
                                st.info(f"Encrypted details: `•••• •••• •••• {last4}` (CVV: `***`)")

    # Tab 3: Loan Offers
    with tab_loans:
        if not loan_offers:
            st.info("No active loan offers at this time.")
        else:
            for offer in loan_offers:
                offer_id = offer.get("id", "")
                loan_type = offer.get("loan_type", "PERSONAL")
                name = offer.get("name") or f"{loan_type.capitalize()} Loan"
                max_amt = offer.get("max_amount_minor", 0)
                rate_bps = offer.get("rate_bps", 1000)
                rate_pct = rate_bps / 100.0
                min_tenure = offer.get("min_tenure_months", 12)
                max_tenure = offer.get("max_tenure_months", 60)
                terms = offer.get("terms") or "Standard banking terms and conditions apply."

                icon = "🏡" if loan_type == "HOME" else ("🚗" if loan_type in ("AUTO", "CAR") else "💼")

                with st.container(border=True):
                    col_ltitle, col_lamt, col_lrate, col_lact = st.columns([3, 2, 1.5, 1.5])
                    with col_ltitle:
                        st.markdown(f"#### {icon} {name}")
                        st.caption(f"**Category:** `{loan_type}` &nbsp;|&nbsp; **Tenure:** {min_tenure} – {max_tenure} Months")
                        st.markdown(f"*{terms}*")
                    with col_lamt:
                        st.metric("Max Pre-Approved", format_currency_inr(max_amt))
                    with col_lrate:
                        st.metric("Interest Rate", f"{rate_pct:.2f}% p.a.")
                    with col_lact:
                        st.write("")
                        if st.button("Apply via AI →", key=f"btn_apply_loan_{offer_id}", use_container_width=True):
                            st.switch_page("pages/1_Chat.py")
