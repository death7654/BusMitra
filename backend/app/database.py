from pathlib import Path

from sqlalchemy import create_engine, text
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


# ---------------------------------------------------------
# Lightweight schema migration
# ---------------------------------------------------------

# Columns added after the first release. Base.metadata.create_all only
# creates *missing tables* - it will never add a column to a table that
# already exists, so an existing data/bus.db would keep working right
# up until the first query that touches the new column and then fail
# with "no such column". Rather than pulling in Alembic for a handful
# of additive columns, we check PRAGMA table_info and ALTER as needed.
#
# Keep this list append-only, and keep every entry nullable (or with a
# default) so it can be applied to a table that already has rows.
# Each entry is (table, column, SQL type, backfill SQL or None). The
# backfill runs once, immediately after the column is added, while
# every row is still NULL.
ADDED_COLUMNS: list[tuple[str, str, str, str | None]] = [
    (
        "checkins",
        "checked_out_at",
        "DATETIME",
        # Check-ins written before this column existed were momentary
        # events that aged out of a 5-minute window. Under the new
        # session semantics a NULL checked_out_at means "still on
        # board", so leaving these NULL would retroactively put every
        # historical rider back on their bus and inflate the live
        # crowd numbers. Close them at the moment they were recorded.
        "UPDATE checkins SET checked_out_at = timestamp "
        "WHERE checked_out_at IS NULL",
    ),
    (
        "crowd_reports",
        "scored",
        "INTEGER DEFAULT 0",
        # Reports that predate trust scoring can't be scored: the
        # observation rows needed as ground truth either don't exist
        # for that period or have aged out. Marking them done keeps the
        # scorer from walking the entire historical table on every
        # pass looking for truth it will never find.
        "UPDATE crowd_reports SET scored = 1 WHERE scored IS NULL",
    ),
]


def ensure_schema() -> list[str]:
    """
    Apply additive column migrations to an existing SQLite database.

    Safe to call on every startup: each ALTER runs only when the column
    is genuinely missing. Returns the list of migrations applied, so
    startup can log what changed.
    """

    applied: list[str] = []

    with engine.begin() as conn:
        for table, column, sql_type, backfill in ADDED_COLUMNS:
            rows = conn.execute(
                text(f"PRAGMA table_info({table})")
            ).fetchall()

            # Empty result means the table doesn't exist yet. In that
            # case create_all will build it with the column already in
            # place, so there is nothing to migrate.
            if not rows:
                continue

            existing = {row[1] for row in rows}

            if column in existing:
                continue

            conn.execute(
                text(
                    f"ALTER TABLE {table} "
                    f"ADD COLUMN {column} {sql_type}"
                )
            )

            if backfill:
                conn.execute(text(backfill))

            applied.append(f"{table}.{column}")

    return applied