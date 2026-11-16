"""API v1 router for the AI service."""
from __future__ import annotations

from fastapi import APIRouter

from app.api.v1.admin import router as admin_router
from app.api.v1.chat import router as chat_router
from app.api.v1.conversations import router as conversations_router
from app.api.v1.documents import router as documents_router

router = APIRouter(prefix="/api/v1")

router.include_router(chat_router)
router.include_router(conversations_router)
router.include_router(documents_router)
router.include_router(admin_router)

__all__ = ["router"]

