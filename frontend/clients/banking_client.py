"""Banking API client for Streamlit frontend authentication and account operations."""
from __future__ import annotations

import os
import re
from typing import Any

import httpx

DEFAULT_BANKING_API_URL = os.environ.get("BANKING_API_URL", "http://localhost:8001/api/v1")


class BankingAPIError(Exception):
    """Exception raised for API errors from the Banking service."""

    def __init__(self, message: str, status_code: int = 400, error_code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_code = error_code


class BankingClient:
    """Client for Banking Service API v1 endpoints."""

    def __init__(self, base_url: str | None = None, timeout: float = 10.0) -> None:
        self.base_url = (base_url or DEFAULT_BANKING_API_URL).rstrip("/")
        self.timeout = timeout

    @staticmethod
    def validate_password_complexity(password: str) -> list[str]:
        """Validate password strength rules. Return list of unmet requirement messages."""
        errors: list[str] = []
        if len(password) < 12:
            errors.append("At least 12 characters")
        if not re.search(r"[A-Z]", password):
            errors.append("At least one uppercase letter (A-Z)")
        if not re.search(r"[a-z]", password):
            errors.append("At least one lowercase letter (a-z)")
        if not re.search(r"[0-9]", password):
            errors.append("At least one number (0-9)")
        if not re.search(r"[^A-Za-z0-9]", password):
            errors.append("At least one special character (!@#$%^&*...)")
        return errors

    @staticmethod
    def validate_phone(phone: str) -> bool:
        """Validate E.164 phone number format (10-15 digits, optional leading +)."""
        cleaned = phone.strip()
        return bool(re.match(r"^\+?[0-9]{10,15}$", cleaned))

    def _handle_response(self, response: httpx.Response) -> dict[str, Any]:
        """Parse JSON response or raise BankingAPIError."""
        try:
            data = response.json()
        except Exception:
            data = {"message": response.text or f"HTTP {response.status_code}"}

        if response.is_success:
            return data

        # Extract error message
        err_msg = data.get("message")
        err_code = data.get("error_code")
        if not err_msg and "details" in data:
            # Pydantic validation error details list
            details = data.get("details", [])
            if isinstance(details, list) and details:
                err_msg = "; ".join(
                    d.get("message", str(d)) for d in details if isinstance(d, dict)
                )
            else:
                err_msg = str(details)
        if not err_msg:
            err_msg = data.get("detail", f"Request failed with status {response.status_code}")

        raise BankingAPIError(str(err_msg), status_code=response.status_code, error_code=err_code)

    def register(
        self,
        email: str,
        phone: str,
        full_name: str,
        password: str,
        pin: Optional[str] = None,
    ) -> dict[str, Any]:
        """Register a new customer account."""
        url = f"{self.base_url}/auth/register"
        payload: dict[str, Any] = {
            "email": email.strip(),
            "phone": phone.strip(),
            "full_name": full_name.strip(),
            "password": password,
        }
        if pin is not None and pin.strip():
            payload["pin"] = pin.strip()
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(url, json=payload)
            return self._handle_response(resp)

    def login(self, email: str, password: str) -> dict[str, Any]:
        """Authenticate user and obtain access & refresh tokens."""
        url = f"{self.base_url}/auth/login"
        payload = {
            "email": email.strip(),
            "password": password,
        }
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(url, json=payload)
            return self._handle_response(resp)

    def refresh(self, refresh_token: str) -> dict[str, Any]:
        """Rotate refresh token and get a new token pair."""
        url = f"{self.base_url}/auth/refresh"
        payload = {"refresh_token": refresh_token}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(url, json=payload)
            return self._handle_response(resp)

    def logout(self, access_token: str, all_sessions: bool = False) -> dict[str, Any]:
        """Revoke current active session or all sessions."""
        url = f"{self.base_url}/auth/logout"
        headers = {"Authorization": f"Bearer {access_token}"}
        params = {"all_sessions": str(all_sessions).lower()}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(url, headers=headers, params=params)
            return self._handle_response(resp)

    def get_me(self, access_token: str) -> dict[str, Any]:
        """Fetch current user profile and assigned roles."""
        url = f"{self.base_url}/users/me"
        headers = {"Authorization": f"Bearer {access_token}"}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(url, headers=headers)
            return self._handle_response(resp)

    def set_transaction_pin(
        self,
        *args: Any,
        **kwargs: Any,
    ) -> dict[str, Any]:
        """Reset or configure transaction PIN by verifying account password.

        Supports flexible call signatures:
          set_transaction_pin(access_token, current_password, new_pin, confirm_pin=None)
          set_transaction_pin(current_password, new_pin, access_token, confirm_pin=None)
          set_transaction_pin(token=..., password=..., pin=...)
        """
        token = kwargs.get("access_token") or kwargs.get("token")
        password = kwargs.get("current_password") or kwargs.get("password")
        pin = kwargs.get("new_pin") or kwargs.get("pin")
        confirm_pin = kwargs.get("confirm_pin")

        if args:
            if len(args) == 3:
                a, b, c = args
                if isinstance(a, str) and a.count(".") == 2:
                    token, password, pin = a, b, c
                elif isinstance(c, str) and c.count(".") == 2:
                    password, pin, token = a, b, c
                elif len(str(c)) > len(str(a)) and len(str(c)) > 20:
                    password, pin, token = a, b, c
                else:
                    token, password, pin = a, b, c
            elif len(args) >= 4:
                a, b, c, d = args[:4]
                if isinstance(a, str) and a.count(".") == 2:
                    token, password, pin, confirm_pin = a, b, c, d
                else:
                    password, pin, token, confirm_pin = a, b, c, d

        if not token or not password or not pin:
            raise ValueError("access_token, password, and pin are required to set transaction PIN.")

        url = f"{self.base_url}/users/pin"
        headers = {"Authorization": f"Bearer {token}"}
        payload: dict[str, Any] = {
            "current_password": password,
            "new_pin": str(pin).strip(),
        }
        if confirm_pin is not None and str(confirm_pin).strip():
            payload["confirm_pin"] = str(confirm_pin).strip()

        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(url, json=payload, headers=headers)
            return self._handle_response(resp)
    def get_sessions(self, access_token: str) -> list[dict[str, Any]]:
        """List active sessions for current user."""
        url = f"{self.base_url}/auth/sessions"
        headers = {"Authorization": f"Bearer {access_token}"}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(url, headers=headers)
            data = self._handle_response(resp)
            return data if isinstance(data, list) else []

    def create_transfer_challenge(self, txn_id: str, access_token: str) -> dict[str, Any]:
        """Request a PIN authorization challenge for a transfer directly from Banking."""
        url = f"{self.base_url}/transfers/{txn_id}/authorize/challenge"
        headers = {"Authorization": f"Bearer {access_token}"}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(url, headers=headers)
            return self._handle_response(resp)

    def authorize_transfer(
        self, txn_id: str, challenge_id: str, pin: str, access_token: str
    ) -> dict[str, Any]:
        """Submit transaction PIN directly to Banking to authorize transfer (never traverses AI)."""
        url = f"{self.base_url}/transfers/{txn_id}/authorize"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "X-Caller-Type": "USER",
        }
        payload = {"challenge_id": challenge_id, "pin": pin}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(url, json=payload, headers=headers)
            return self._handle_response(resp)

    def authorize_card_payment(
        self, payment_id: str, pin: str, access_token: str
    ) -> dict[str, Any]:
        """Submit transaction PIN directly to Banking to authorize card payment."""
        url = f"{self.base_url}/credit-cards/payments/{payment_id}/authorize"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "X-Caller-Type": "USER",
        }
        payload = {"pin": pin}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(url, json=payload, headers=headers)
            return self._handle_response(resp)

    def create_beneficiary_challenge(
        self, action: str, payload_hash: str, access_token: str
    ) -> dict[str, Any]:
        """Request approval challenge for beneficiary creation directly from Banking."""
        url = f"{self.base_url}/approvals/challenges"
        headers = {"Authorization": f"Bearer {access_token}"}
        payload = {"action": action, "payload_hash": payload_hash}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(url, json=payload, headers=headers)
            return self._handle_response(resp)

    def verify_beneficiary_challenge(
        self, challenge_id: str, pin: str, access_token: str
    ) -> dict[str, Any]:
        """Verify beneficiary challenge with PIN directly at Banking to obtain approval token."""
        url = f"{self.base_url}/approvals/challenges/{challenge_id}/verify"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "X-Caller-Type": "USER",
        }
        payload = {"pin": pin}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(url, json=payload, headers=headers)
            return self._handle_response(resp)

    # ------------------------------------------------------------------
    # Direct Banking APIs (Accounts, Beneficiaries, Transactions)
    # ------------------------------------------------------------------
    def list_accounts(
        self, access_token: str, status: str | None = None
    ) -> list[dict[str, Any]]:
        """List linked bank accounts for current user."""
        url = f"{self.base_url}/accounts"
        headers = {"Authorization": f"Bearer {access_token}"}
        params = {"status": status} if status else {}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(url, headers=headers, params=params)
            data = self._handle_response(resp)
            return data if isinstance(data, list) else []

    def add_account(
        self, data: dict[str, Any], access_token: str
    ) -> dict[str, Any]:
        """Link a new bank account with client-side/server-side validation."""
        url = f"{self.base_url}/accounts"
        headers = {"Authorization": f"Bearer {access_token}"}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(url, json=data, headers=headers)
            return self._handle_response(resp)

    def get_account(self, account_id: str, access_token: str) -> dict[str, Any]:
        """Get details for a specific linked bank account."""
        url = f"{self.base_url}/accounts/{account_id}"
        headers = {"Authorization": f"Bearer {access_token}"}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(url, headers=headers)
            return self._handle_response(resp)
    def get_account_balance(
        self, account_id: str, access_token: str
    ) -> dict[str, Any]:
        """Fetch real-time available balance for an account."""
        url = f"{self.base_url}/accounts/{account_id}/balance"
        headers = {"Authorization": f"Bearer {access_token}"}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(url, headers=headers)
            return self._handle_response(resp)
    def verify_account(
        self, account_id: str, access_token: str
    ) -> dict[str, Any]:
        """Trigger mock penny-drop verification for an account."""
        url = f"{self.base_url}/accounts/{account_id}/verify"
        headers = {"Authorization": f"Bearer {access_token}"}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(url, headers=headers)
            return self._handle_response(resp)

    def deactivate_account(
        self, account_id: str, access_token: str
    ) -> bool:
        """Deactivate a linked bank account."""
        url = f"{self.base_url}/accounts/{account_id}"
        headers = {"Authorization": f"Bearer {access_token}"}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.delete(url, headers=headers)
            if resp.status_code in (200, 204):
                return True
            self._handle_response(resp)
            return True

    def list_beneficiaries(
        self, access_token: str, query: str | None = None
    ) -> list[dict[str, Any]]:
        """List active transfer beneficiaries for current user."""
        url = f"{self.base_url}/beneficiaries"
        headers = {"Authorization": f"Bearer {access_token}"}
        params = {"q": query} if query else {}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(url, headers=headers, params=params)
            data = self._handle_response(resp)
            return data if isinstance(data, list) else []

    def create_beneficiary(
        self, data: dict[str, Any], approval_token: str, access_token: str
    ) -> dict[str, Any]:
        """Create a new beneficiary with X-Approval-Token from verified PIN challenge."""
        url = f"{self.base_url}/beneficiaries"
        headers = {
            "Authorization": f"Bearer {access_token}",
            "X-Approval-Token": approval_token,
        }
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(url, json=data, headers=headers)
            return self._handle_response(resp)

    def verify_beneficiary(
        self, bene_id: str, access_token: str
    ) -> dict[str, Any]:
        """Trigger mock penny-drop verification for a beneficiary."""
        url = f"{self.base_url}/beneficiaries/{bene_id}/verify"
        headers = {"Authorization": f"Bearer {access_token}"}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(url, headers=headers)
            return self._handle_response(resp)

    def deactivate_beneficiary(
        self, bene_id: str, access_token: str
    ) -> bool:
        """Deactivate a beneficiary."""
        url = f"{self.base_url}/beneficiaries/{bene_id}"
        headers = {"Authorization": f"Bearer {access_token}"}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.delete(url, headers=headers)
            if resp.status_code in (200, 204):
                return True
            self._handle_response(resp)
            return True

    def list_transactions(
        self,
        access_token: str,
        type: str | None = None,
        status: str | None = None,
        min_amount_minor: int | None = None,
        max_amount_minor: int | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        """List personal transactions with filtering and pagination."""
        url = f"{self.base_url}/transactions"
        headers = {"Authorization": f"Bearer {access_token}"}
        params: dict[str, Any] = {"page": page, "page_size": page_size}
        if type:
            params["type"] = type
        if status:
            params["status"] = status
        if min_amount_minor is not None:
            params["min_amount_minor"] = min_amount_minor
        if max_amount_minor is not None:
            params["max_amount_minor"] = max_amount_minor

        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(url, headers=headers, params=params)
            return self._handle_response(resp)

    def get_transaction(self, txn_id: str, access_token: str) -> dict[str, Any]:
        """Get details for a specific transaction."""
        url = f"{self.base_url}/transactions/{txn_id}"
        headers = {"Authorization": f"Bearer {access_token}"}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(url, headers=headers)
            return self._handle_response(resp)
    def get_transaction_by_reference(
        self, reference: str, access_token: str
    ) -> dict[str, Any]:
        """Lookup transaction by its unique reference string."""
        url = f"{self.base_url}/transactions/by-reference/{reference}"
        headers = {"Authorization": f"Bearer {access_token}"}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(url, headers=headers)
            return self._handle_response(resp)

    # ------------------------------------------------------------------
    # Customer Dashboard, Cards & Loans APIs (T7.4)
    # ------------------------------------------------------------------
    def get_customer_dashboard(self, access_token: str) -> dict[str, Any]:
        """Fetch aggregated customer dashboard with accounts, cards, and loan offers."""
        url = f"{self.base_url}/dashboard"
        headers = {"Authorization": f"Bearer {access_token}"}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(url, headers=headers)
            return self._handle_response(resp)

    def list_credit_cards(self, access_token: str) -> list[dict[str, Any]]:
        """List all credit cards owned by authenticated user."""
        url = f"{self.base_url}/credit-cards"
        headers = {"Authorization": f"Bearer {access_token}"}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(url, headers=headers)
            data = self._handle_response(resp)
            return data if isinstance(data, list) else []

    def get_card_sensitive_details(
        self, card_id: str, access_token: str
    ) -> dict[str, Any]:
        """Fetch decrypted sensitive card details (number, expiry, CVV) for cardholder."""
        url = f"{self.base_url}/credit-cards/{card_id}/details"
        headers = {"Authorization": f"Bearer {access_token}"}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(url, headers=headers)
            return self._handle_response(resp)

    def list_loan_offers(self, access_token: str) -> list[dict[str, Any]]:
        """List pre-approved and generic loan offers for authenticated user."""
        url = f"{self.base_url}/loans/offers"
        headers = {"Authorization": f"Bearer {access_token}"}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(url, headers=headers)
            data = self._handle_response(resp)
            return data if isinstance(data, list) else []

    # ------------------------------------------------------------------
    # Admin & Audit Management APIs
    # ------------------------------------------------------------------
    def get_admin_stats(self, access_token: str) -> dict[str, Any]:
        """Retrieve aggregated platform metrics."""
        url = f"{self.base_url}/admin/stats"
        headers = {"Authorization": f"Bearer {access_token}"}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(url, headers=headers)
            return self._handle_response(resp)
    def list_admin_users(
        self, access_token: str, page: int = 1, page_size: int = 50
    ) -> list[dict[str, Any]]:
        """List registered users with assigned roles and security lock status."""
        url = f"{self.base_url}/admin/users"
        headers = {"Authorization": f"Bearer {access_token}"}
        params = {"page": page, "page_size": page_size}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(url, headers=headers, params=params)
            data = self._handle_response(resp)
            return data if isinstance(data, list) else data.get("items", [])

    def update_user_status(
        self, user_id: str, is_active: bool, access_token: str
    ) -> dict[str, Any]:
        """Activate or deactivate a user account."""
        url = f"{self.base_url}/admin/users/{user_id}/status"
        headers = {"Authorization": f"Bearer {access_token}"}
        payload = {"is_active": is_active}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.patch(url, json=payload, headers=headers)
            return self._handle_response(resp)

    def update_user_roles(
        self, user_id: str, roles: list[str], access_token: str
    ) -> dict[str, Any]:
        """Update role assignments for a user."""
        url = f"{self.base_url}/admin/users/{user_id}/roles"
        headers = {"Authorization": f"Bearer {access_token}"}
        payload = {"roles": roles}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.put(url, json=payload, headers=headers)
            return self._handle_response(resp)

    def list_admin_transactions(
        self, access_token: str, page: int = 1, page_size: int = 50
    ) -> list[dict[str, Any]]:
        """List system-wide transactions with masked source accounts."""
        url = f"{self.base_url}/admin/transactions"
        headers = {"Authorization": f"Bearer {access_token}"}
        params = {"page": page, "page_size": page_size}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(url, headers=headers, params=params)
            data = self._handle_response(resp)
            return data if isinstance(data, list) else data.get("items", [])

    def list_admin_loans(
        self, access_token: str, page: int = 1, page_size: int = 50
    ) -> list[dict[str, Any]]:
        """List submitted loan applications across all customers."""
        url = f"{self.base_url}/admin/loan-applications"
        headers = {"Authorization": f"Bearer {access_token}"}
        params = {"page": page, "page_size": page_size}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(url, headers=headers, params=params)
            data = self._handle_response(resp)
            return data if isinstance(data, list) else data.get("items", [])

    def get_admin_config(self, access_token: str) -> dict[str, Any]:
        """Retrieve active runtime transaction limits and approval parameters."""
        url = f"{self.base_url}/admin/config"
        headers = {"Authorization": f"Bearer {access_token}"}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(url, headers=headers)
            return self._handle_response(resp)
    def update_admin_config(
        self, payload: dict[str, Any], access_token: str
    ) -> dict[str, Any]:
        """Update runtime transaction limits, approval expiry, and duplicate detection."""
        url = f"{self.base_url}/admin/config"
        headers = {"Authorization": f"Bearer {access_token}"}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.patch(url, json=payload, headers=headers)
            return self._handle_response(resp)

    def list_audit_logs(
        self,
        access_token: str,
        actor: str | None = None,
        action: str | None = None,
        resource_type: str | None = None,
        outcome: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> list[dict[str, Any]]:
        """Search and filter the immutable audit log trail."""
        url = f"{self.base_url}/audit-logs"
        headers = {"Authorization": f"Bearer {access_token}"}
        params: dict[str, Any] = {"page": page, "page_size": page_size}
        if actor:
            params["actor"] = actor
        if action:
            params["action"] = action
        if resource_type:
            params["resource_type"] = resource_type
        if outcome:
            params["outcome"] = outcome

        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(url, headers=headers, params=params)
            data = self._handle_response(resp)
            return data if isinstance(data, list) else data.get("items", [])

    def get_audit_log(self, log_id: str, access_token: str) -> dict[str, Any]:
        """Retrieve a specific audit log record."""
        url = f"{self.base_url}/audit-logs/{log_id}"
        headers = {"Authorization": f"Bearer {access_token}"}
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.get(url, headers=headers)
            return self._handle_response(resp)