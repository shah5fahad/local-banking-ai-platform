"""AI service application factory."""
from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import router as api_v1_router
from app.core.config import get_settings
from app.core.errors import (
    AIError,
    ai_error_handler,
    unhandled_exception_handler,
    validation_error_handler,
)
from app.core.middleware import request_id_middleware
from banking_common.logging import configure_logging

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    settings = get_settings()
    configure_logging(service="ai", level=settings.log_level, fmt=settings.log_format)
    logger.info("AI service starting", extra={"service": "ai"})

    sweeper_task = None
    stop_event = asyncio.Event()
    if settings.enable_expiry_sweeper:
        from app.db.engine import get_session_factory
        from app.services.expiry_sweeper import run_periodic_sweeper

        sweeper_task = asyncio.create_task(
            run_periodic_sweeper(
                session_factory=get_session_factory(),
                settings=settings,
                stop_event=stop_event,
            )
        )
        logger.info("Background expiry sweeper started")

    yield

    if sweeper_task:
        logger.info("Stopping background expiry sweeper")
        stop_event.set()
        sweeper_task.cancel()
        try:
            await sweeper_task
        except asyncio.CancelledError:
            pass

    logger.info("AI service shutting down", extra={"service": "ai"})


def create_app() -> FastAPI:
    settings = get_settings()

    openapi_tags = [
        {"name": "system", "description": "System health and info"},
        {"name": "chat", "description": "Conversational banking AI"},
        {"name": "approvals", "description": "Human-in-the-loop transaction approvals"},
        {"name": "documents", "description": "Policy and RAG document management"},
    ]

    app = FastAPI(
        title="AI Service API",
        description="LangGraph-based AI agent service for the banking platform.",
        version="0.1.0",
        openapi_tags=openapi_tags,
        lifespan=lifespan,
    )

    # 1. Request ID middleware (first to attach correlation ID)
    app.middleware("http")(request_id_middleware)

    # 2. CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 3. Exception handlers
    app.add_exception_handler(AIError, ai_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(RequestValidationError, validation_error_handler)  # type: ignore[arg-type]
    app.add_exception_handler(Exception, unhandled_exception_handler)

    # 4. Mount API routers
    app.include_router(api_v1_router)

    @app.get("/health", tags=["system"])
    async def health() -> dict[str, str]:
        return {"status": "ok", "service": "ai"}

    return app


app = create_app()
