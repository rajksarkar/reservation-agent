"""SQLAlchemy database models."""

from datetime import datetime
from enum import Enum
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.ext.asyncio import AsyncAttrs, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(AsyncAttrs, DeclarativeBase):
    """Base class for all models."""

    pass


class BookingStatus(str, Enum):
    """Status of a booking request."""

    PENDING = "pending"
    SCHEDULED = "scheduled"
    ATTEMPTING = "attempting"
    BOOKED = "booked"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AttemptResult(str, Enum):
    """Result of a booking attempt."""

    SUCCESS = "success"
    SLOT_TAKEN = "slot_taken"
    AUTH_FAILED = "auth_failed"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    ERROR = "error"


class Restaurant(Base):
    """Restaurant being monitored."""

    __tablename__ = "restaurants"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    platform: Mapped[str] = mapped_column(String(50), nullable=False)
    venue_id: Mapped[str] = mapped_column(String(255), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    bookings: Mapped[list["Booking"]] = relationship(back_populates="restaurant")

    __table_args__ = (
        Index("ix_restaurants_platform_venue", "platform", "venue_id", unique=True),
    )


class Booking(Base):
    """Booking request to be fulfilled."""

    __tablename__ = "bookings"

    id: Mapped[int] = mapped_column(primary_key=True)
    restaurant_id: Mapped[int] = mapped_column(ForeignKey("restaurants.id"), nullable=False)
    party_size: Mapped[int] = mapped_column(Integer, nullable=False)
    target_date: Mapped[str] = mapped_column(String(10), nullable=False)  # YYYY-MM-DD
    preferred_times: Mapped[str] = mapped_column(Text, nullable=False)  # JSON array
    status: Mapped[str] = mapped_column(
        String(50), default=BookingStatus.PENDING.value, nullable=False
    )

    # Booking details (filled when successful)
    booked_time: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    confirmation_number: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)
    booked_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    # Scheduling
    release_datetime: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    monitor_cancellations: Mapped[bool] = mapped_column(Boolean, default=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # Relationships
    restaurant: Mapped["Restaurant"] = relationship(back_populates="bookings")
    attempts: Mapped[list["BookingAttempt"]] = relationship(back_populates="booking")

    __table_args__ = (
        Index("ix_bookings_status", "status"),
        Index("ix_bookings_release", "release_datetime"),
        Index("ix_bookings_target_date", "target_date"),
    )


class BookingAttempt(Base):
    """Record of each booking attempt."""

    __tablename__ = "booking_attempts"

    id: Mapped[int] = mapped_column(primary_key=True)
    booking_id: Mapped[int] = mapped_column(ForeignKey("bookings.id"), nullable=False)
    attempt_type: Mapped[str] = mapped_column(String(50), nullable=False)  # snipe, cancellation
    result: Mapped[str] = mapped_column(String(50), nullable=False)
    slot_time: Mapped[Optional[str]] = mapped_column(String(10), nullable=True)
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    # Relationships
    booking: Mapped["Booking"] = relationship(back_populates="attempts")

    __table_args__ = (Index("ix_attempts_booking_time", "booking_id", "attempted_at"),)


class PlatformSession(Base):
    """Stored session data for platforms."""

    __tablename__ = "platform_sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    platform: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    session_data: Mapped[str] = mapped_column(Text, nullable=False)  # JSON
    last_validated: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ActivityLog(Base):
    """Log of important agent activities."""

    __tablename__ = "activity_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    level: Mapped[str] = mapped_column(String(20), nullable=False)  # info, warning, error
    category: Mapped[str] = mapped_column(String(50), nullable=False)
    message: Mapped[str] = mapped_column(Text, nullable=False)
    details: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # JSON
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_activity_created", "created_at"),
        Index("ix_activity_category", "category"),
    )


async def init_database(database_url: str):
    """Initialize database and create tables."""
    engine = create_async_engine(database_url, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine


def get_session_factory(engine):
    """Create an async session factory."""
    return async_sessionmaker(engine, expire_on_commit=False)
