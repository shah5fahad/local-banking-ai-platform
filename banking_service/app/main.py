"""Banking service application factory.

Responsibilities:
- Create and configure the FastAPI application instance.
- Mount CORS middleware.
- Mount request-ID middleware.
- Register exception handlers.
- Expose /health endpoint.
- Mount API routers.
"""
from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from app.api.v1 import router as api_v1_router
from app.core.config import get_settings
from app.core.errors import (
    BankingError,
    banking_error_handler,
    unhandled_exception_handler,
    validation_error_handler,
)
from app.core.middleware import request_id_middleware
from banking_common.logging import configure_logging

logger = logging.getLogger(__name__)

openapi_tags = [
    {"name": "system", "description": "Health and system endpoints"},
    {"name": "auth", "description": "Authentication - register, login, token refresh, sessions"},
    {"name": "users", "description": "User profile management"},
    {"name": "accounts", "description": "Bank account CRUD, verification, balance"},
    {"name": "beneficiaries", "description": "Saved beneficiaries with approval workflow"},
    {"name": "approvals", "description": "Challenge-response approval tokens"},
    {"name": "transfers", "description": "Fund transfers with PIN/OTP authorization"},
    {"name": "transactions", "description": "Transaction history and lookup"},
    {"name": "loans", "description": "Loan offers, eligibility, applications"},
    {"name": "credit-cards", "description": "Credit card management and payments"},
    {"name": "admin", "description": "Admin operations (ADMIN role required)"},
    {"name": "audit-logs", "description": "Audit log viewer (ADMIN/AUDITOR role required)"},
]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: configure logging on startup."""
    settings = get_settings()
    configure_logging(
        service="banking",
        level=settings.log_level,
        fmt=settings.log_format,
    )
    logger.info(
        "Banking service starting",
        extra={"env": settings.app_env, "service": "banking"},
    )
    yield
    logger.info("Banking service shutting down", extra={"service": "banking"})


def create_app() -> FastAPI:
    """Application factory – returns a configured FastAPI instance."""
    settings = get_settings()

    app = FastAPI(
        title="Banking Service API",
        description=(
            "Core banking operations REST API. "
            "Owns all financial data, business rules, and JWT issuance."
        ),
        version="0.1.0",
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
        openapi_tags=openapi_tags,
        lifespan=lifespan,
    )

    # ------------------------------------------------------------------
    # Middleware (order matters: outermost first)
    # ------------------------------------------------------------------

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Request-ID middleware (Starlette BaseHTTPMiddleware wrapper)
    app.add_middleware(BaseHTTPMiddleware, dispatch=request_id_middleware)

    # ------------------------------------------------------------------
    # Exception handlers
    # ------------------------------------------------------------------

    app.add_exception_handler(BankingError, banking_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)

    # ------------------------------------------------------------------
    # System endpoints
    # ------------------------------------------------------------------

    @app.get("/health", tags=["system"], summary="Health check")
    async def health() -> dict[str, str]:
        """Returns 200 OK when the service is ready to accept traffic."""
        return {"status": "ok", "service": "banking"}

    # ------------------------------------------------------------------
    # API routers
    # ------------------------------------------------------------------

    app.include_router(api_v1_router)

    return app


# ASGI entry point (used by uvicorn and docker-compose command)
app = create_app()
