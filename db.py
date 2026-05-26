"""SQLite persistence for tracking already-notified Copart lots."""

from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, String, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

import config


class Base(DeclarativeBase):
    pass


class SeenLot(Base):
    __tablename__ = "seen_lots"

    lot_number = Column(String, primary_key=True)
    notified_at = Column(DateTime, nullable=False)


engine = create_engine(f"sqlite:///{config.DATABASE_PATH}", echo=False)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def init_db() -> None:
    """Create tables if they do not exist."""
    Base.metadata.create_all(bind=engine)


def is_lot_seen(lot_number: str) -> bool:
    """Return True if this lot has already been notified."""
    with SessionLocal() as session:
        return session.get(SeenLot, lot_number) is not None


def mark_lot_seen(lot_number: str) -> None:
    """Record that a lot notification was sent."""
    with SessionLocal() as session:
        session.merge(
            SeenLot(
                lot_number=lot_number,
                notified_at=datetime.now(timezone.utc),
            )
        )
        session.commit()


def get_seen_count() -> int:
    """Return total number of lots in the seen database."""
    with SessionLocal() as session:
        return session.query(SeenLot).count()
