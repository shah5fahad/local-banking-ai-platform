"""Authentication forms (Login and Registration) with client-side validation."""
from __future__ import annotations

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

        submitted = st.form_submit_button("Create Account", use_container_width=True, type="primary")

    if submitted:
        # Client-side validations
        if not full_name or not email or not phone or not password:
            st.error("Please fill in all required fields.")
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

        try:
            with st.spinner("Registering your account..."):
                client.register(
                    email=email,
                    phone=phone,
                    full_name=full_name,
                    password=password,
                )
                st.success("Account created successfully! Logging you in...")

                # Auto-login after registration
                tokens = client.login(email=email, password=password)
                login_user(tokens)
                st.rerun()

        except BankingAPIError as e:
            st.error(f"Registration failed: {e.message}")
        except Exception as e:
            st.error(f"Connection error: Could not reach Banking service ({e})")
