from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker


# Project root directory
BASE_DIR = Path(__file__).resolve().parent.parent

# Data directory
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)

# SQLite database
DATABASE_URL = f"sqlite:///{DATA_DIR / 'bus.db'}"


# SQLite engine
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)


# Database session factory
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
)


# Base class for SQLAlchemy models
Base = declarative_base()


def get_db():
    """
    Provides a database session to FastAPI endpoints.

    The session is automatically closed after
    the request is completed.
    """
    db = SessionLocal()

    try:
        yield db
    finally:
        db.close()