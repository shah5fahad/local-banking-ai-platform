"""SQLAlchemy declarative base for all Banking service models."""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base.

    All Banking ORM models inherit from this class so that Alembic's
    autogenerate can discover them through ``Base.metadata``.
    """
