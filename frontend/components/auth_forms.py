"""Authentication forms (Login and Registration) with client-side validation."""
from __future__ import annotations

import time

import streamlit as st

from clients.banking_client import BankingAPIError, BankingClient
from state.session import get_banking_client, login_user


def render_login_form() -> None:
    """Render the login form."""
    client = get_banking_client()

    st.subheader("Welcome Back")
    st.write("Log in to your banking account to continue.")

    with st.form("login_form", clear_on_submit=False):
        email = st.text_input("Email Address", placeholder="name@example.com").strip()
        password = st.text_input("Password", type="password", placeholder="Enter your password")
        submitted = st.form_submit_button("Sign In", use_container_width=True, type="primary")

    if submitted:
        if not email or not password:
            st.error("Please enter both email and password.")
            return

        try:
            with st.spinner("Authenticating..."):
                tokens = client.login(email=email, password=password)
                login_user(tokens)
                st.success("Authentication successful! Welcome back.")
                time.sleep(0.3)
                st.rerun()
        except BankingAPIError as e:
            if e.error_code == "ACCOUNT_LOCKED" or e.status_code == 423:
                st.error(f"🔒 **Account Locked:** {e.message}")
            else:
                st.error(f"Authentication failed: {e.message}")
        except Exception as e:
            st.error(f"Connection error: Could not reach Banking service ({e})")


def render_signup_form() -> None:
    """Render the registration / sign-up form with password strength guidance."""
    client = get_banking_client()

    st.subheader("Create a New Account")
    st.write("Join Local Banking with secure multi-factor protection.")

    with st.form("register_form", clear_on_submit=False):
        full_name = st.text_input("Full Name", placeholder="e.g. John Doe").strip()
        email = st.text_input("Email Address", placeholder="e.g. john@example.com").strip()
        phone = st.text_input("Mobile Phone Number", placeholder="+919876543210").strip()

        st.caption("Phone number must be in E.164 format (10-15 digits with country code, e.g. +919876543210).")

        password = st.text_input("Password", type="password", placeholder="Choose a strong password")
        confirm_password = st.text_input("Confirm Password", type="password", placeholder="Re-enter your password")

        # Password requirement indicators
        with st.expander("Password Requirements", expanded=False):
            st.markdown(
                "- Minimum **12 characters**\n"
                "- At least one **uppercase letter** (A-Z)\n"
                "- At least one **lowercase letter** (a-z)\n"
                "- At least one **number** (0-9)\n"
                "- At least one **special character** (!@#$%^&*...)"
            )

        st.markdown("---")
        st.markdown("##### 🔐 Transaction PIN *(Required)*")
        st.caption("A 4 to 6 digit numeric PIN required to authorize funds transfers and high-security transactions.")
        pin = st.text_input(
            "Transaction PIN (4-6 digits) *",
            type="password",
            placeholder="e.g. 1234 (required)",
            max_chars=6,
            key="signup_pin",
        )
        confirm_pin = st.text_input(
            "Confirm Transaction PIN *",
            type="password",
            placeholder="Re-enter 4-6 digit PIN",
            max_chars=6,
            key="signup_confirm_pin",
        )

        submitted = st.form_submit_button("Create Account", use_container_width=True, type="primary")

    if submitted:
        # Client-side validations
        if not full_name or not email or not phone or not password or not pin or not confirm_pin:
            st.error("Please fill in all required fields, including your transaction PIN.")
            return

        if not client.validate_phone(phone):
            st.error("Invalid phone format. Please enter 10 to 15 digits, e.g. `+919876543210`.")
            return

        pwd_errors = client.validate_password_complexity(password)
        if pwd_errors:
            st.error("Password does not meet complexity requirements:\n" + "\n".join(f"- {e}" for e in pwd_errors))
            return

        if password != confirm_password:
            st.error("Passwords do not match. Please verify your entry.")
            return

        # Validate required transaction PIN
        cleaned_pin = pin.strip() if pin else ""
        cleaned_confirm_pin = confirm_pin.strip() if confirm_pin else ""
        if not cleaned_pin or not cleaned_confirm_pin:
            st.error("Transaction PIN and confirmation PIN are required.")
            return

        if not cleaned_pin.isdigit() or len(cleaned_pin) < 4 or len(cleaned_pin) > 6:
            st.error("Transaction PIN must be 4 to 6 numeric digits (e.g. 1234 or 123456).")
            return

        if cleaned_pin != cleaned_confirm_pin:
            st.error("Transaction PIN and confirmation PIN do not match. Please verify your entry.")
            return

        try:
            with st.spinner("Registering your account..."):
                client.register(
                    email=email,
                    phone=phone,
                    full_name=full_name,
                    password=password,
                    pin=cleaned_pin,
                )
                st.success("Account created successfully! Logging you in...")

                # Auto-login after registration
                tokens = client.login(email=email, password=password)
                login_user(tokens)
                time.sleep(0.3)
                st.rerun()

        except BankingAPIError as e:
            st.error(f"Registration failed: {e.message}")
        except Exception as e:
            st.error(f"Connection error: Could not reach Banking service ({e})")
