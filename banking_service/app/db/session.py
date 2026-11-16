"""FastAPI database session dependency for the Banking service."""
from __future__ import annotations

from collections.abc import Generator

from sqlalchemy.orm import Session

from app.db.engine import get_session_factory


def get_db() -> Generator[Session, None, None]:
    """Yield a database session and ensure it is closed after use.

    Use as a FastAPI dependency::

        @router.get("/items")
        def list_items(db: Session = Depends(get_db)) -> list[Item]:
            ...
    """
    SessionLocal = get_session_factory()
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
