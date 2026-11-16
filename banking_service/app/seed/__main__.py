"""Run seed: python -m app.seed"""
import sys
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.engine import get_engine
from app.seed.seed import run_seed

if __name__ == "__main__":
    settings = get_settings()
    engine = get_engine()
    with Session(engine) as db:
        run_seed(db, settings)
