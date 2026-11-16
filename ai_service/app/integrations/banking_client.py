"""Typed HTTP adapter for the Banking Service REST API.

Design:
- Uses httpx for sync HTTP (sync for LangChain tool compatibility)
- Injects user JWT as Bearer token + X-Service-Key for service identity
- Times out at 10s (reads) / 30s (writes)
- Maps HTTP errors to BankingClientError with typed codes
- Masks sensitive fields in logs using banking_common masking
- Never logs request bodies for auth/transfer endpoints
- Retries 2x with backoff on reads (5xx only)
"""
from __future__ import annotations

import logging
import time
from typing import Any

import httpx

from app.core.config import AISettings

logger = logging.getLogger(__name__)


class BankingClientError(Exception):
    """Raised when the banking service returns an error."""

    def __init__(self, error_code: str, message: str, http_status: int) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.message = message
        self.http_status = http_status

    @classmethod
    def from_response(cls, response: httpx.Response) -> BankingClientError:
        try:
            body = response.json()
            code = body.get("error_code", "BANKING_ERROR")
            msg = body.get("message", f"HTTP {response.status_code}")
        except Exception:
            code = "BANKING_ERROR"
            msg = f"HTTP {response.status_code}"
        return cls(code, msg, response.status_code)


class BankingClient:
    """Synchronous typed adapter for the Banking REST API.

    Usage:
        client = BankingClient(settings=settings, access_token=user_jwt)
        accounts = client.list_accounts()
    """

    READ_TIMEOUT = 10.0
    WRITE_TIMEOUT = 30.0
    MAX_RETRIES = 2

    def __init__(self, settings: AISettings, access_token: str) -> None:
        base_url = settings.banking_service_url.rstrip("/")
        if base_url.endswith("/api/v1"):
            base_url = base_url[:-7]
        self._base_url = base_url
        self._access_token = access_token
        self._service_key = settings.service_key
        headers = {
            "X-Service-Key": self._service_key,
            "Content-Type": "application/json",
        }
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        self._headers = headers

    def _get(self, path: str, params: dict | None = None) -> Any:  # noqa: ANN401
        """Make a GET request with retry on 5xx."""
        url = f"{self._base_url}{path}"
        last_exc: Exception | None = None
        for attempt in range(self.MAX_RETRIES + 1):
            if attempt > 0:
                time.sleep(0.5 * attempt)
            try:
                logger.debug("BankingClient GET %s (attempt %d)", path, attempt + 1)
                r = httpx.get(
                    url,
                    headers=self._headers,
                    params=params,
                    timeout=self.READ_TIMEOUT,
                )
                if r.status_code >= 500 and attempt < self.MAX_RETRIES:
                    logger.warning(
                        "BankingClient GET %s returned %d, retrying...",
                        path,
                        r.status_code,
                    )
                    continue
                if not r.is_success:
                    raise BankingClientError.from_response(r)
                return r.json()
            except httpx.TimeoutException as exc:
                last_exc = exc
                if attempt < self.MAX_RETRIES:
                    continue
                raise BankingClientError("TIMEOUT", f"Request to {path} timed out", 504) from exc
            except httpx.RequestError as exc:
                last_exc = exc
                if attempt < self.MAX_RETRIES:
                    continue
                raise BankingClientError(
                    "NETWORK_ERROR",
                    f"Failed to connect to banking service at {path}: {exc}",
                    502,
                ) from exc
        raise BankingClientError("TIMEOUT", f"Request to {path} timed out", 504) from last_exc

    def _post(
        self,
        path: str,
        body: dict | None = None,
        headers_extra: dict | None = None,
        log_body: bool = True,
    ) -> Any:  # noqa: ANN401
        """Make a POST request (no retry)."""
        url = f"{self._base_url}{path}"
        hdrs = {**self._headers, **(headers_extra or {})}
        if log_body:
            logger.debug("BankingClient POST %s", path)
        else:
            logger.debug("BankingClient POST %s (body omitted for security)", path)
        try:
            r = httpx.post(url, json=body, headers=hdrs, timeout=self.WRITE_TIMEOUT)
            if not r.is_success:
                raise BankingClientError.from_response(r)
            if r.status_code == 204:
                return None
            return r.json()
        except httpx.TimeoutException as exc:
            raise BankingClientError("TIMEOUT", f"POST {path} timed out", 504) from exc
        except httpx.RequestError as exc:
            raise BankingClientError(
                "NETWORK_ERROR",
                f"Failed to connect to banking service at {path}: {exc}",
                502,
            ) from exc

    # ----------------------------------------------------------------
    # Accounts
    # ----------------------------------------------------------------
    def list_accounts(self) -> list[dict]:
        return self._get("/api/v1/accounts") or []

    def get_account(self, account_id: str) -> dict:
        return self._get(f"/api/v1/accounts/{account_id}")

    def get_balance(self, account_id: str | None = None) -> dict:
        """Fetch balance for the given account ID, or top active account if omitted."""
        if account_id:
            return self._get(f"/api/v1/accounts/{account_id}/balance")
        # When account_id is omitted, fetch top active account balance directly
        try:
            return self._get("/api/v1/accounts/balance")
        except BankingClientError as exc:
            # Fallback if endpoint is not reachable directly
            if exc.http_status in (404, 405):
                accounts = self.list_accounts()
                active = [a for a in accounts if a.get("status") == "ACTIVE"]
                target = active[0] if active else (accounts[0] if accounts else None)
                if not target:
                    raise
                return self._get(f"/api/v1/accounts/{target['id']}/balance")
            raise

    # ----------------------------------------------------------------
    # Beneficiaries
    # ----------------------------------------------------------------
    def list_beneficiaries(self, q: str | None = None) -> list[dict]:
        params = {"q": q} if q else None
        return self._get("/api/v1/beneficiaries", params=params) or []

    def get_beneficiary(self, bene_id: str) -> dict:
        return self._get(f"/api/v1/beneficiaries/{bene_id}")

    def create_beneficiary(self, data: dict, approval_token: str) -> dict:
        return self._post(
            "/api/v1/beneficiaries",
            body=data,
            headers_extra={"X-Approval-Token": approval_token},
            log_body=False,
        )

    def create_approval_challenge(self, action: str, payload_hash: str) -> dict:
        return self._post(
            "/api/v1/approvals/challenges",
            body={"action": action, "payload_hash": payload_hash},
        )


    # ----------------------------------------------------------------
    # Transfers
    # ----------------------------------------------------------------
    def prepare_transfer(self, data: dict, idempotency_key: str) -> dict:
        return self._post(
            "/api/v1/transfers",
            body=data,
            headers_extra={"Idempotency-Key": idempotency_key},
            log_body=False,
        )

    def get_transfer(self, txn_id: str) -> dict:
        return self._get(f"/api/v1/transfers/{txn_id}")

    def get_transfer_status(self, txn_id: str) -> dict:
        return self._get(f"/api/v1/transfers/{txn_id}/status")


    def execute_transfer(
        self,
        txn_id: str,
        authorization_id: str,
        summary_hash: str,
        idempotency_key: str,
    ) -> dict:
        return self._post(
            f"/api/v1/transfers/{txn_id}/execute",
            body={"authorization_id": authorization_id, "summary_hash": summary_hash},
            headers_extra={"Idempotency-Key": idempotency_key},
            log_body=False,
        )

    def cancel_transfer(self, txn_id: str) -> None:
        self._post(f"/api/v1/transfers/{txn_id}/cancel")

    def get_transfer_limits(self) -> dict:
        return self._get("/api/v1/transfers/limits")

    # ----------------------------------------------------------------
    # Transactions
    # ----------------------------------------------------------------
    def list_transactions(self, **filters: Any) -> dict:  # noqa: ANN401
        return self._get(
            "/api/v1/transactions",
            params={k: v for k, v in filters.items() if v is not None},
        )

    # ----------------------------------------------------------------
    # Loans
    # ----------------------------------------------------------------
    def list_loan_offers(self) -> list[dict]:
        return self._get("/api/v1/loans/offers") or []

    def check_loan_eligibility(self, data: dict) -> dict:
        return self._post("/api/v1/loans/eligibility", body=data)

    def submit_loan_application(self, data: dict, idempotency_key: str) -> dict:
        return self._post(
            "/api/v1/loans/applications",
            body=data,
            headers_extra={"Idempotency-Key": idempotency_key},
        )

    def list_loan_applications(self) -> list[dict]:
        return self._get("/api/v1/loans/applications") or []

    def get_loan_repayment(self, loan_id: str) -> dict:
        return self._get(f"/api/v1/loans/{loan_id}/repayment")

    # ----------------------------------------------------------------
    # Credit cards
    # ----------------------------------------------------------------
    def list_cards(self) -> list[dict]:
        return self._get("/api/v1/credit-cards") or []

    def get_card_outstanding(self, card_id: str) -> dict:
        return self._get(f"/api/v1/credit-cards/{card_id}/outstanding")

    def get_current_bill(self, card_id: str) -> dict:
        return self._get(f"/api/v1/credit-cards/{card_id}/bills/current")

    def prepare_card_payment(
        self, card_id: str, data: dict, idempotency_key: str
    ) -> dict:
        return self._post(
            f"/api/v1/credit-cards/{card_id}/payments",
            body=data,
            headers_extra={"Idempotency-Key": idempotency_key},
            log_body=False,
        )

    def execute_card_payment(
        self, payment_id: str, authorization_id: str, idempotency_key: str
    ) -> dict:
        return self._post(
            f"/api/v1/credit-cards/payments/{payment_id}/execute",
            body={"authorization_id": authorization_id},
            headers_extra={"Idempotency-Key": idempotency_key},
            log_body=False,
        )

    def get_card_payment_status(self, payment_id: str) -> dict:
        return self._get(f"/api/v1/credit-cards/payments/{payment_id}/status")

    # ----------------------------------------------------------------
    # User
    # ----------------------------------------------------------------
    def get_user_profile(self) -> dict:
        return self._get("/api/v1/users/me")

    def get_user_summary(self) -> dict:
        return self._get("/api/v1/users/me/summary")
