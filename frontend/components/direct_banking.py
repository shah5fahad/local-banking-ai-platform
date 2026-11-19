"""Direct banking component for managing bank accounts, beneficiaries, and transaction history (T6.6)."""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

import streamlit as st

from clients.banking_client import BankingAPIError, BankingClient
from components.admin_dashboard import format_currency_inr
from components.history_view import format_iso_timestamp
from state.session import get_access_token, get_banking_client


def render_accounts_tab(banking_client: BankingClient, access_token: str) -> None:
    """Render bank accounts management, balance checks, verification, and link form."""
    st.subheader("🏦 Linked Bank Accounts")
    st.markdown("View linked accounts, check real-time balances, verify accounts, or link a new bank account.")

    col_btn, _ = st.columns([1, 4])
    with col_btn:
        if st.button("🔄 Refresh Accounts", key="acc_refresh_btn", use_container_width=True):
            st.rerun()

    try:
        accounts = banking_client.list_accounts(access_token)
    except BankingAPIError as err:
        st.error(f"Failed to fetch accounts: {err.message}")
        accounts = []
    except Exception as exc:
        st.error(f"Error fetching accounts: {exc}")
        accounts = []

    # Display accounts cards
    if not accounts:
        st.info("No bank accounts linked yet. Use the form below to link your first account.")
    else:
        for acc in accounts:
            acc_id = acc.get("id", "")
            holder = acc.get("holder_name", "")
            masked_num = acc.get("account_number_masked", "XXXXXX0000")
            acc_type = acc.get("account_type", "SAVINGS")
            bank = acc.get("bank_name", "Bank")
            branch = acc.get("branch_name") or "Main Branch"
            ifsc = acc.get("ifsc", "")
            bal_minor = acc.get("balance_minor", 0)
            status_val = acc.get("status", "ACTIVE")
            ver_val = acc.get("verification_status", "PENDING")

            status_badge = "🟢 ACTIVE" if status_val == "ACTIVE" else f"⚪ {status_val}"
            ver_badge = "🟢 VERIFIED" if ver_val == "VERIFIED" else f"⏳ {ver_val}"

            with st.container(border=True):
                col_info, col_bal, col_actions = st.columns([3, 2, 2])
                with col_info:
                    st.markdown(f"#### 💳 {bank} - `{masked_num}`")
                    st.caption(
                        f"**Holder:** {holder} &nbsp;|&nbsp; **Type:** `{acc_type}` &nbsp;|&nbsp; "
                        f"**IFSC:** `{ifsc}` &nbsp;|&nbsp; **Branch:** {branch}"
                    )
                    st.caption(f"**Status:** {status_badge} &nbsp;|&nbsp; **Verification:** {ver_badge}")

                with col_bal:
                    st.metric("Available Balance", format_currency_inr(bal_minor))
                    if st.button("⚡ Check Balance", key=f"btn_bal_{acc_id}", use_container_width=True):
                        try:
                            fresh_bal = banking_client.get_account_balance(acc_id, access_token)
                            st.success(f"Real-time balance: **{format_currency_inr(fresh_bal.get('available_minor'))}**")
                        except Exception as e:
                            st.error(str(e))

                with col_actions:
                    if ver_val != "VERIFIED":
                        if st.button("✅ Verify (Penny Drop)", key=f"btn_ver_{acc_id}", use_container_width=True):
                            try:
                                res = banking_client.verify_account(acc_id, access_token)
                                st.toast(res.get("message", "Account verified!"), icon="✅")
                                st.rerun()
                            except Exception as e:
                                st.error(str(e))

                    with st.popover("🗑️ Deactivate", use_container_width=True):
                        st.markdown(f"**Deactivate `{masked_num}`?**")
                        st.caption("Account cannot be deactivated if there are pending transactions.")
                        if st.button("Confirm Deactivate", key=f"conf_deact_{acc_id}", type="primary"):
                            try:
                                banking_client.deactivate_account(acc_id, access_token)
                                st.toast(f"Deactivated account {masked_num}", icon="🗑️")
                                st.rerun()
                            except Exception as e:
                                st.error(str(e))

    st.markdown("---")

    # Form to link a new bank account
    with st.expander("➕ Link a New Bank Account", expanded=not bool(accounts)):
        with st.form("add_account_form", clear_on_submit=False):
            st.markdown("##### Bank Account Information")
            c1, c2 = st.columns(2)
            with c1:
                holder_name = st.text_input("Account Holder Name *", placeholder="Full name as in bank records", key="new_acc_holder")
                account_number = st.text_input("Account Number *", placeholder="9 to 18 digits", type="password", key="new_acc_num")
                account_number_confirm = st.text_input("Confirm Account Number *", placeholder="Re-enter account number", key="new_acc_num_conf")
            with c2:
                ifsc_code = st.text_input("IFSC Code *", placeholder="e.g. HDFC0001234", key="new_acc_ifsc").upper().strip()
                bank_name = st.text_input("Bank Name *", placeholder="e.g. HDFC Bank, SBI, ICICI", key="new_acc_bank")
                branch_name = st.text_input("Branch Name", placeholder="e.g. Connaught Place, Mumbai Main", key="new_acc_branch")

            acc_type = st.selectbox("Account Type *", options=["SAVINGS", "CURRENT", "SALARY"], index=0, key="new_acc_type")

            submitted = st.form_submit_button("Link Bank Account", type="primary", use_container_width=True)

        if submitted:
            if not holder_name.strip():
                st.error("Holder name is required.")
                return
            if not account_number.isdigit() or len(account_number) < 9 or len(account_number) > 18:
                st.error("Account number must be 9 to 18 numeric digits.")
                return
            if account_number != account_number_confirm:
                st.error("Account numbers do not match.")
                return
            if not re.match(r"^[A-Z]{4}0[A-Z0-9]{6}$", ifsc_code):
                st.error("Invalid IFSC format. Must match standard 11-character format (e.g. HDFC0001234).")
                return
            if not bank_name.strip():
                st.error("Bank name is required.")
                return

            try:
                payload = {
                    "holder_name": holder_name.strip(),
                    "account_number": account_number.strip(),
                    "ifsc": ifsc_code,
                    "bank_name": bank_name.strip(),
                    "branch_name": branch_name.strip() or "Main Branch",
                    "account_type": acc_type,
                }
                res = banking_client.add_account(payload, access_token)
                st.success(f"✅ Successfully linked account **{res.get('account_number_masked')}** with {res.get('bank_name')}!")
                st.rerun()
            except BankingAPIError as e:
                st.error(f"Failed to link account: {e.message}")
            except Exception as ex:
                st.error(f"Unexpected error: {ex}")


def render_beneficiaries_tab(banking_client: BankingClient, access_token: str) -> None:
    """Render beneficiaries management, search, verification, and add workflow with PIN authentication."""
    st.subheader("👥 Transfer Beneficiaries")
    st.markdown("Manage verified transfer recipients. Adding a new beneficiary requires customer PIN verification.")

    col_search, col_ref = st.columns([4, 1])
    with col_search:
        search_q = st.text_input("🔍 Search Beneficiaries", placeholder="Search by name, nickname, or bank...", key="bene_search_q").strip()
    with col_ref:
        st.write("")
        st.write("")
        if st.button("🔄 Refresh", key="bene_refresh_btn", use_container_width=True):
            st.rerun()

    try:
        beneficiaries = banking_client.list_beneficiaries(access_token, query=search_q or None)
    except Exception as exc:
        st.error(f"Failed to load beneficiaries: {exc}")
        beneficiaries = []

    if not beneficiaries:
        st.info("No beneficiaries found matching search criteria.")
    else:
        for b in beneficiaries:
            b_id = b.get("id", "")
            name = b.get("name", "N/A")
            nick = b.get("nickname")
            masked_acc = b.get("account_number_masked", "XXXXXX0000")
            ifsc = b.get("ifsc", "")
            bank = b.get("bank_name", "")
            ver_status = b.get("verification_status", "PENDING")
            ver_badge = "🟢 VERIFIED" if ver_status == "VERIFIED" else f"⏳ {ver_status}"

            with st.container(border=True):
                c_info, c_acts = st.columns([4, 2])
                with c_info:
                    st.markdown(f"#### 👤 {name} {f'({nick})' if nick else ''}")
                    st.caption(f"**Bank:** {bank} &nbsp;|&nbsp; **Account:** `{masked_acc}` &nbsp;|&nbsp; **IFSC:** `{ifsc}`")
                    st.caption(f"**Verification:** {ver_badge} &nbsp;|&nbsp; **Eligible Channels:** IMPS, NEFT, RTGS")
                with c_acts:
                    if ver_status != "VERIFIED":
                        if st.button("✅ Verify (Penny Drop)", key=f"btn_ver_bene_{b_id}", use_container_width=True):
                            try:
                                banking_client.verify_beneficiary(b_id, access_token)
                                st.toast(f"Verified {name} successfully!", icon="✅")
                                st.rerun()
                            except Exception as e:
                                st.error(str(e))

                    with st.popover("🗑️ Remove", use_container_width=True):
                        st.markdown(f"**Deactivate `{name}`?**")
                        if st.button("Confirm Remove", key=f"conf_del_bene_{b_id}", type="primary"):
                            try:
                                banking_client.deactivate_beneficiary(b_id, access_token)
                                st.toast(f"Removed beneficiary {name}", icon="🗑️")
                                st.rerun()
                            except Exception as e:
                                st.error(str(e))

    st.markdown("---")

    # Add New Beneficiary Flow
    with st.expander("➕ Add New Beneficiary (Requires PIN Authentication)"):
        with st.form("add_beneficiary_form", clear_on_submit=False):
            st.markdown("##### Beneficiary Account Details")
            col_b1, col_b2 = st.columns(2)
            with col_b1:
                b_name = st.text_input("Beneficiary Full Name *", placeholder="e.g. Rahul Sharma", key="new_bene_name")
                b_acc = st.text_input("Account Number *", placeholder="9 to 18 digits", type="password", key="new_bene_acc")
                b_acc_conf = st.text_input("Confirm Account Number *", placeholder="Re-enter account number", key="new_bene_acc_conf")
                b_nick = st.text_input("Nickname (Optional)", placeholder="e.g. Rahul Landlord", key="new_bene_nick")
            with col_b2:
                b_ifsc = st.text_input("IFSC Code *", placeholder="e.g. HDFC0001234", key="new_bene_ifsc").upper().strip()
                b_bank = st.text_input("Bank Name *", placeholder="e.g. HDFC Bank, SBI", key="new_bene_bank")
                b_email = st.text_input("Email (Optional)", placeholder="recipient@example.com", key="new_bene_email")
                b_phone = st.text_input("Phone (Optional)", placeholder="+919876543210", key="new_bene_phone")

            st.markdown("##### 🔒 Authentication")
            b_pin = st.text_input(
                "Transaction PIN *",
                type="password",
                max_chars=6,
                placeholder="Enter 4-digit PIN to authorize addition",
                help="Submitted directly to Core Banking API to issue single-use X-Approval-Token.",
                key="new_bene_pin",
            )

            btn_submit_bene = st.form_submit_button("Authenticate & Add Beneficiary", type="primary", use_container_width=True)

        if btn_submit_bene:
            if not b_name.strip():
                st.error("Beneficiary name is required.")
                return
            if not b_acc.isdigit() or len(b_acc) < 9 or len(b_acc) > 18:
                st.error("Account number must be 9 to 18 numeric digits.")
                return
            if b_acc != b_acc_conf:
                st.error("Account numbers do not match.")
                return
            if not re.match(r"^[A-Z]{4}0[A-Z0-9]{6}$", b_ifsc):
                st.error("Invalid IFSC format. Must match standard 11-character format (e.g. HDFC0001234).")
                return
            if not b_bank.strip():
                st.error("Bank name is required.")
                return
            if not b_pin or len(b_pin) < 4:
                st.error("Valid 4-digit transaction PIN is required to authorize adding a beneficiary.")
                return

            try:
                # 1. Compute summary hash of beneficiary payload
                bene_data: dict[str, Any] = {
                    "name": b_name.strip(),
                    "account_number": b_acc.strip(),
                    "ifsc": b_ifsc,
                    "bank_name": b_bank.strip(),
                }
                if b_nick.strip():
                    bene_data["nickname"] = b_nick.strip()
                if b_email.strip():
                    bene_data["email"] = b_email.strip()
                if b_phone.strip():
                    bene_data["phone"] = b_phone.strip()

                payload_str = json.dumps(bene_data, sort_keys=True)
                payload_hash = hashlib.sha256(payload_str.encode("utf-8")).hexdigest()

                # 2. Direct-to-banking: Create challenge
                with st.spinner("Authorizing beneficiary challenge directly with Core Banking..."):
                    challenge = banking_client.create_beneficiary_challenge(
                        action="BENEFICIARY_CREATE",
                        payload_hash=payload_hash,
                        access_token=access_token,
                    )
                    challenge_id = challenge.get("challenge_id") or challenge.get("id")
                    if not challenge_id:
                        st.error("Failed to obtain beneficiary challenge from Banking service.")
                        return

                    # 3. Direct-to-banking: Verify PIN directly to obtain approval token
                    verify_res = banking_client.verify_beneficiary_challenge(
                        challenge_id=challenge_id,
                        pin=b_pin,
                        access_token=access_token,
                    )
                    approval_token = verify_res.get("approval_token")
                    if not approval_token:
                        st.error("Failed to obtain approval token from verification.")
                        return

                    # 4. Create beneficiary with X-Approval-Token
                    created = banking_client.create_beneficiary(
                        data=bene_data,
                        approval_token=approval_token,
                        access_token=access_token,
                    )

                st.success(f"✅ Beneficiary **{created.get('name')}** linked successfully! Verification Status: `{created.get('verification_status')}`")
                st.rerun()
            except BankingAPIError as be:
                st.error(f"Failed to add beneficiary: {be.message}")
            except Exception as ex:
                st.error(f"Authentication or creation error: {ex}")


def render_history_tab(banking_client: BankingClient, access_token: str) -> None:
    """Render personal banking transaction history, filters, and reference search."""
    st.subheader("📜 Direct Banking Transaction History")
    st.markdown("Review your personal transfers, card payments, settlements, and debit records.")

    col_type, col_st, col_ref = st.columns([2, 2, 1])
    with col_type:
        type_filter = st.selectbox(
            "Transaction Type",
            options=["All Types", "TRANSFER", "CARD_PAYMENT", "DEPOSIT"],
            key="hist_type_filter",
        )
    with col_st:
        status_filter = st.selectbox(
            "Transaction Status",
            options=["All Statuses", "COMPLETED", "PENDING_APPROVAL", "FAILED"],
            key="hist_status_filter",
        )
    with col_ref:
        st.write("")
        st.write("")
        if st.button("🔄 Refresh", key="hist_refresh_btn", use_container_width=True):
            st.rerun()

    api_type = None if type_filter == "All Types" else type_filter
    api_status = None if status_filter == "All Statuses" else status_filter

    try:
        resp = banking_client.list_transactions(
            access_token=access_token,
            type=api_type,
            status=api_status,
            page=1,
            page_size=100,
        )
        txns: list[dict[str, Any]] = resp.get("items", [])
        total: int = resp.get("total", len(txns))
    except Exception as exc:
        st.error(f"Failed to fetch transaction history: {exc}")
        return

    # Metrics
    completed_txns = [t for t in txns if t.get("status") == "COMPLETED"]
    total_debit_minor = sum(t.get("total_debit_minor", 0) for t in completed_txns)

    c1, c2, c3 = st.columns(3)
    c1.metric("Total Transactions", total)
    c2.metric("Completed Transfers", len(completed_txns))
    c3.metric("Total Debited", format_currency_inr(total_debit_minor))

    st.markdown("---")

    if not txns:
        st.info("No transactions found matching the selected filters.")
    else:
        rows = []
        for t in txns:
            st_val = t.get("status", "UNKNOWN")
            st_badge = "🟢 COMPLETED" if st_val == "COMPLETED" else ("🔴 FAILED" if "FAIL" in st_val else f"⏳ {st_val}")
            rows.append({
                "Reference": t.get("reference"),
                "Type": t.get("type"),
                "Amount": format_currency_inr(t.get("amount_minor")),
                "Fee": format_currency_inr(t.get("fee_minor")),
                "Total Debit": format_currency_inr(t.get("total_debit_minor")),
                "Source Account": t.get("source_account_masked") or "N/A",
                "Channel": t.get("channel") or "-",
                "Status": st_badge,
                "Date": format_iso_timestamp(t.get("created_at")),
                "Failure Reason": t.get("failure_reason") or "-",
            })

        st.dataframe(rows, use_container_width=True)

    st.markdown("---")

    # Reference lookup
    with st.expander("🔍 Search Specific Transaction by Reference"):
        col_in, col_go = st.columns([3, 1])
        with col_in:
            ref_input = st.text_input("Enter Reference String (e.g. TXN202611...)", key="txn_ref_search").strip()
        with col_go:
            st.write("")
            st.write("")
            btn_lookup = st.button("Search Reference", key="btn_lookup_ref", use_container_width=True)

        if btn_lookup and ref_input:
            try:
                txn = banking_client.get_transaction_by_reference(ref_input, access_token)
                st.success(f"Transaction Found: **{txn.get('reference')}**")
                st.json(txn)
            except BankingAPIError as be:
                st.error(f"Transaction not found: {be.message}")
            except Exception as ex:
                st.error(f"Lookup error: {ex}")


def render_pin_management_section(banking_client: BankingClient, access_token: str) -> None:
    """Render transaction PIN setup and regeneration card."""
    with st.expander("🔐 Security Settings: Change / Reset Transaction PIN", expanded=False):
        st.markdown("#### Transaction PIN Management")
        st.caption(
            "Your transaction PIN authorizes high-value transfers, bill payments, and adding beneficiaries. "
            "You can update or regenerate your 4-6 digit numeric PIN anytime by verifying your account login password."
        )

        with st.form("reset_pin_form", clear_on_submit=False):
            curr_pass = st.text_input(
                "Current Account Password",
                type="password",
                placeholder="Enter your current password",
                key="direct_banking_current_password",
            )
            new_pin = st.text_input(
                "New Transaction PIN (4-6 digits)",
                type="password",
                placeholder="e.g. 1234 or 123456",
                max_chars=6,
                key="direct_banking_new_pin",
            )
            confirm_pin = st.text_input(
                "Confirm New PIN",
                type="password",
                placeholder="Re-enter new 4-6 digit PIN",
                max_chars=6,
                key="direct_banking_confirm_pin",
            )
            btn_update = st.form_submit_button("Update Transaction PIN", type="primary", use_container_width=True)

        if btn_update:
            if not curr_pass or not new_pin or not confirm_pin:
                st.error("Please fill in all fields (current password, new PIN, and confirmation).")
                return

            cleaned_pin = new_pin.strip()
            cleaned_confirm = confirm_pin.strip()

            if not cleaned_pin.isdigit() or len(cleaned_pin) < 4 or len(cleaned_pin) > 6:
                st.error("Transaction PIN must be 4 to 6 numeric digits (e.g. 1234 or 123456).")
                return

            if cleaned_pin != cleaned_confirm:
                st.error("New PIN and confirmation PIN do not match.")
                return

            try:
                with st.spinner("Updating your transaction PIN..."):
                    res = banking_client.set_transaction_pin(
                        access_token=access_token,
                        current_password=curr_pass,
                        new_pin=cleaned_pin,
                        confirm_pin=cleaned_confirm,
                    )
                    st.success("✅ " + res.get("message", "Transaction PIN updated successfully!"))
            except BankingAPIError as be:
                st.error(f"❌ Failed to update PIN: {be.message}")
            except Exception as ex:
                st.error(f"❌ An error occurred: {ex}")


def render_direct_banking() -> None:
    """Main direct banking interface rendering Accounts, Beneficiaries, and History tabs."""
    token = get_access_token()
    if not token:
        st.warning("Please sign in to access your direct banking services.")
        return

    banking_client = get_banking_client()

    tab_acc, tab_bene, tab_hist = st.tabs(
        ["🏦 Bank Accounts", "👥 Beneficiaries", "📜 Transaction History"]
    )

    with tab_acc:
        render_accounts_tab(banking_client, token)

    with tab_bene:
        render_beneficiaries_tab(banking_client, token)

    with tab_hist:
        render_history_tab(banking_client, token)

    st.markdown("---")
    render_pin_management_section(banking_client, token)
