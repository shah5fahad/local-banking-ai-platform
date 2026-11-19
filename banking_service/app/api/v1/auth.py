"""Auth API router - register, login, refresh, logout, and sessions."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, Request, status
from fastapi.security import HTTPAuthorizationCredentials

from app.core.config import BankingSettings
from app.core.deps import AppSettings, CurrentUser, DbSession, security_bearer
from app.core.security import decode_token
from app.repositories.session_repository import SessionRepository
from app.schemas.account import AccountResponse
from app.schemas.credit_card import CreditCardResponse
from app.schemas.loan import LoanOfferResponse
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    RegisterResponse,
    SessionResponse,
    TokenResponse,
)
from app.services.auth_service import AuthService
from app.services.token_service import TokenService

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=RegisterResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Register a new customer account",
)
def register(
    req: RegisterRequest,
    db: DbSession,
    settings: AppSettings,
) -> RegisterResponse:
    """Register a new customer account, assign CUSTOMER role, and auto-create primary bank account."""
    auth_service = AuthService()
    user = auth_service.register(
        email=req.email,
        phone=req.phone,
        full_name=req.full_name,
        password=req.password,
        db=db,
        settings=settings,
        pin=req.pin,
    )
    db.commit()
    db.refresh(user)

    primary_acc = user.accounts[0] if user.accounts else None
    account_resp = AccountResponse.model_validate(primary_acc) if primary_acc else None

    primary_card = user.credit_cards[0] if user.credit_cards else None
    card_resp = CreditCardResponse.model_validate(primary_card) if primary_card else None

    loan_offers_resp = [
        LoanOfferResponse.model_validate(o) for o in (user.loan_offers or [])
    ] if hasattr(user, "loan_offers") and user.loan_offers else None

    return RegisterResponse(
        id=user.id,
        email=user.email,
        full_name=user.full_name,
        transaction_pin_set=bool(user.transaction_pin_hash),
        account_id=primary_acc.id if primary_acc else None,
        account_number_masked=primary_acc.account_number_masked if primary_acc else None,
        account=account_resp,
        card_id=primary_card.id if primary_card else None,
        card_last4=primary_card.last4 if primary_card else None,
        card=card_resp,
        loan_offers=loan_offers_resp,
    )


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Authenticate and issue JWT tokens",
)
def login(
    req: LoginRequest,
    request: Request,
    db: DbSession,
    settings: AppSettings,
) -> TokenResponse:
    """Authenticate user with email and password, returning access and refresh tokens."""
    user_agent = request.headers.get("user-agent")
    client_ip = request.client.host if request.client else None

    auth_service = AuthService()
    user, access_token, refresh_token = auth_service.login(
        email=req.email,
        password=req.password,
        user_agent=user_agent,
        ip=client_ip,
        db=db,
        settings=settings,
    )
    db.commit()

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        token_type="bearer",
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Rotate refresh token and issue new token pair",
)
def refresh(
    req: RefreshRequest,
    request: Request,
    db: DbSession,
    settings: AppSettings,
) -> TokenResponse:
    """Rotate refresh token; old session is revoked and new tokens are issued."""
    user_agent = request.headers.get("user-agent")
    client_ip = request.client.host if request.client else None

    token_service = TokenService()
    access_token, new_refresh_token, _ = token_service.refresh(
        refresh_token=req.refresh_token,
        settings=settings,
        db=db,
        user_agent=user_agent,
        ip=client_ip,
    )
    db.commit()

    return TokenResponse(
        access_token=access_token,
        refresh_token=new_refresh_token,
        token_type="bearer",
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.post(
    "/logout",
    status_code=status.HTTP_200_OK,
    summary="Revoke session and logout",
)
def logout(
    user: CurrentUser,
    request: Request,
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security_bearer)],
    all_sessions: bool = False,
) -> dict[str, str]:
    """Revoke current active session or all sessions for this user."""
    session_repo = SessionRepository(db)
    if all_sessions:
        session_repo.revoke_all_for_user(user.id)
    elif credentials:
        payload = decode_token(credentials.credentials)
        sid = payload.get("sid")
        jti = payload.get("jti")
        if sid:
            session_repo.revoke(sid)
        elif jti:
            sess = session_repo.get_by_jti(jti)
            if sess:
                session_repo.revoke(sess.id)
    db.commit()
    return {"message": "Logged out successfully"}


@router.get(
    "/sessions",
    response_model=list[SessionResponse],
    summary="List active sessions for current user",
)
def get_sessions(
    user: CurrentUser,
    db: DbSession,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security_bearer)],
) -> list[SessionResponse]:
    """List non-revoked active sessions for current user."""
    session_repo = SessionRepository(db)
    active_sessions = session_repo.list_active_for_user(user.id)

    current_sid = None
    if credentials:
        try:
            payload = decode_token(credentials.credentials)
            current_sid = payload.get("sid")
        except Exception:
            pass

    return [
        SessionResponse(
            id=s.id,
            user_agent=s.user_agent,
            ip=s.ip,
            created_at=s.created_at,
            expires_at=s.expires_at,
            is_current=(s.id == current_sid),
        )
        for s in active_sessions
    ]
