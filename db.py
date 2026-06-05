"""SQLite persistence for users, preferences, and per-user seen lots."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Integer, String, Text, create_engine, func, select, text
from sqlalchemy.orm import DeclarativeBase, relationship, sessionmaker

import config
from user_prefs import UserPreferences, default_preferences


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    telegram_user_id = Column(Integer, primary_key=True)
    chat_id = Column(String, nullable=False)
    username = Column(String, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False)
    preferences = relationship(
        "UserPreferenceRow",
        back_populates="user",
        uselist=False,
        cascade="all, delete-orphan",
    )


class UserPreferenceRow(Base):
    __tablename__ = "user_preferences"

    user_id = Column(Integer, ForeignKey("users.telegram_user_id"), primary_key=True)
    prefs_json = Column(Text, nullable=False)
    updated_at = Column(DateTime, nullable=False)
    user = relationship("User", back_populates="preferences")


class SeenLot(Base):
    __tablename__ = "seen_lots"

    user_id = Column(Integer, ForeignKey("users.telegram_user_id"), primary_key=True)
    lot_number = Column(String, primary_key=True)
    notified_at = Column(DateTime, nullable=False)


engine = create_engine(f"sqlite:///{config.DATABASE_PATH}", echo=False)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


@dataclass
class UserRecord:
    telegram_user_id: int
    chat_id: str
    username: str | None
    prefs: UserPreferences


def init_db() -> None:
    """Create tables and migrate legacy schema if needed."""
    Base.metadata.create_all(bind=engine)
    _migrate_legacy_seen_lots()


def _migrate_legacy_seen_lots() -> None:
    """Migrate old global seen_lots (lot_number only) to per-user schema."""
    with engine.connect() as conn:
        rows = conn.execute(text("SELECT name FROM sqlite_master WHERE type='table'")).fetchall()
        table_names = {row[0] for row in rows}
        if "seen_lots" not in table_names:
            return

        columns = conn.execute(text("PRAGMA table_info(seen_lots)")).fetchall()
        column_names = {col[1] for col in columns}
        if "user_id" in column_names:
            return

        legacy_rows = conn.execute(
            text("SELECT lot_number, notified_at FROM seen_lots")
        ).fetchall()
        if not legacy_rows:
            conn.execute(text("DROP TABLE seen_lots"))
            conn.commit()
            Base.metadata.create_all(bind=engine)
            return

        seed_user_id: int | None = None
        if config.TELEGRAM_CHAT_ID:
            try:
                seed_user_id = int(config.TELEGRAM_CHAT_ID)
            except ValueError:
                seed_user_id = None

        conn.execute(text("ALTER TABLE seen_lots RENAME TO seen_lots_legacy"))
        conn.commit()

    Base.metadata.create_all(bind=engine)

    if seed_user_id is not None:
        with SessionLocal() as session:
            user = session.get(User, seed_user_id)
            if user is None:
                now = datetime.now(timezone.utc)
                user = User(
                    telegram_user_id=seed_user_id,
                    chat_id=config.TELEGRAM_CHAT_ID,
                    username=None,
                    is_active=True,
                    created_at=now,
                )
                session.add(user)
                session.add(
                    UserPreferenceRow(
                        user_id=seed_user_id,
                        prefs_json=default_preferences().to_json(),
                        updated_at=now,
                    )
                )
                session.commit()

        with engine.connect() as conn:
            for lot_number, notified_at in legacy_rows:
                conn.execute(
                    text(
                        "INSERT OR IGNORE INTO seen_lots (user_id, lot_number, notified_at) "
                        "VALUES (:user_id, :lot_number, :notified_at)"
                    ),
                    {
                        "user_id": seed_user_id,
                        "lot_number": lot_number,
                        "notified_at": notified_at,
                    },
                )
            conn.execute(text("DROP TABLE seen_lots_legacy"))
            conn.commit()
    else:
        with engine.connect() as conn:
            conn.execute(text("DROP TABLE seen_lots_legacy"))
            conn.commit()


def get_or_create_user(
    telegram_user_id: int,
    chat_id: str | int,
    username: str | None = None,
) -> UserRecord:
    """Return existing user or register with default preferences."""
    chat_id_str = str(chat_id)
    with SessionLocal() as session:
        user = session.get(User, telegram_user_id)
        now = datetime.now(timezone.utc)
        if user is None:
            user = User(
                telegram_user_id=telegram_user_id,
                chat_id=chat_id_str,
                username=username,
                is_active=True,
                created_at=now,
            )
            session.add(user)
            session.add(
                UserPreferenceRow(
                    user_id=telegram_user_id,
                    prefs_json=default_preferences().to_json(),
                    updated_at=now,
                )
            )
            session.commit()
        else:
            user.chat_id = chat_id_str
            if username:
                user.username = username
            session.commit()

        prefs = get_user_preferences(telegram_user_id)
        stored = session.get(User, telegram_user_id)
        return UserRecord(
            telegram_user_id=telegram_user_id,
            chat_id=stored.chat_id if stored else chat_id_str,
            username=stored.username if stored else username,
            prefs=prefs,
        )


def get_user_preferences(telegram_user_id: int) -> UserPreferences:
    with SessionLocal() as session:
        row = session.get(UserPreferenceRow, telegram_user_id)
        if row is None:
            return default_preferences()
        return UserPreferences.from_json(row.prefs_json)


def save_user_preferences(telegram_user_id: int, prefs: UserPreferences) -> None:
    with SessionLocal() as session:
        row = session.get(UserPreferenceRow, telegram_user_id)
        now = datetime.now(timezone.utc)
        if row is None:
            session.add(
                UserPreferenceRow(
                    user_id=telegram_user_id,
                    prefs_json=prefs.to_json(),
                    updated_at=now,
                )
            )
        else:
            row.prefs_json = prefs.to_json()
            row.updated_at = now
        session.commit()


def get_user_record(telegram_user_id: int) -> UserRecord | None:
    """Return a single active user record, or None if not registered."""
    with SessionLocal() as session:
        user = session.get(User, telegram_user_id)
        if user is None or not user.is_active:
            return None
        prefs_row = session.get(UserPreferenceRow, user.telegram_user_id)
        prefs = (
            UserPreferences.from_json(prefs_row.prefs_json)
            if prefs_row
            else default_preferences()
        )
        return UserRecord(
            telegram_user_id=user.telegram_user_id,
            chat_id=user.chat_id,
            username=user.username,
            prefs=prefs,
        )


def get_active_users() -> list[UserRecord]:
    with SessionLocal() as session:
        users = session.scalars(
            select(User).where(User.is_active.is_(True))
        ).all()
        records: list[UserRecord] = []
        for user in users:
            prefs_row = session.get(UserPreferenceRow, user.telegram_user_id)
            prefs = (
                UserPreferences.from_json(prefs_row.prefs_json)
                if prefs_row
                else default_preferences()
            )
            records.append(
                UserRecord(
                    telegram_user_id=user.telegram_user_id,
                    chat_id=user.chat_id,
                    username=user.username,
                    prefs=prefs,
                )
            )
        return records


def is_lot_seen(telegram_user_id: int, lot_number: str) -> bool:
    with SessionLocal() as session:
        return (
            session.get(SeenLot, (telegram_user_id, lot_number)) is not None
        )


def mark_lot_seen(telegram_user_id: int, lot_number: str) -> None:
    with SessionLocal() as session:
        session.merge(
            SeenLot(
                user_id=telegram_user_id,
                lot_number=lot_number,
                notified_at=datetime.now(timezone.utc),
            )
        )
        session.commit()


def get_seen_count(telegram_user_id: int | None = None) -> int:
    with SessionLocal() as session:
        query = select(func.count()).select_from(SeenLot)
        if telegram_user_id is not None:
            query = query.where(SeenLot.user_id == telegram_user_id)
        return session.scalar(query) or 0


def seed_admin_user_if_configured() -> None:
    """Ensure TELEGRAM_CHAT_ID user exists with default preferences."""
    if not config.TELEGRAM_CHAT_ID:
        return
    try:
        user_id = int(config.TELEGRAM_CHAT_ID)
    except ValueError:
        return

    with SessionLocal() as session:
        if session.get(User, user_id) is not None:
            return

    get_or_create_user(user_id, config.TELEGRAM_CHAT_ID)
