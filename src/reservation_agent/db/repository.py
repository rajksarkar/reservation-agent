"""Data access layer for the reservation agent."""

import json
from datetime import datetime
from typing import Any

from sqlalchemy import select, update, delete, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from reservation_agent.db.models import (
    ActivityLog,
    Booking,
    BookingAttempt,
    BookingStatus,
    PlatformSession,
    Restaurant,
)
from reservation_agent.utils.logging import get_logger

logger = get_logger(__name__)


class Repository:
    """Data access layer for all database operations."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]):
        self.session_factory = session_factory

    # Restaurant operations

    async def get_or_create_restaurant(
        self,
        name: str,
        platform: str,
        venue_id: str,
    ) -> Restaurant:
        """Get existing restaurant or create new one."""
        async with self.session_factory() as session:
            # Try to find existing
            stmt = select(Restaurant).where(
                and_(
                    Restaurant.platform == platform,
                    Restaurant.venue_id == venue_id,
                )
            )
            result = await session.execute(stmt)
            restaurant = result.scalar_one_or_none()

            if restaurant:
                return restaurant

            # Create new
            restaurant = Restaurant(
                name=name,
                platform=platform,
                venue_id=venue_id,
            )
            session.add(restaurant)
            await session.commit()
            await session.refresh(restaurant)

            logger.info(
                "created_restaurant",
                name=name,
                platform=platform,
                venue_id=venue_id,
            )
            return restaurant

    async def get_restaurant(self, restaurant_id: int) -> Restaurant | None:
        """Get restaurant by ID."""
        async with self.session_factory() as session:
            stmt = select(Restaurant).where(Restaurant.id == restaurant_id)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def get_restaurants(self, enabled_only: bool = True) -> list[Restaurant]:
        """Get all restaurants."""
        async with self.session_factory() as session:
            stmt = select(Restaurant)
            if enabled_only:
                stmt = stmt.where(Restaurant.enabled == True)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    # Booking operations

    async def create_booking(
        self,
        restaurant_id: int,
        party_size: int,
        target_date: str,
        preferred_times: str,
        monitor_cancellations: bool = True,
        release_datetime: datetime | None = None,
    ) -> Booking:
        """Create a new booking request."""
        async with self.session_factory() as session:
            # Check for existing booking
            stmt = select(Booking).where(
                and_(
                    Booking.restaurant_id == restaurant_id,
                    Booking.target_date == target_date,
                    Booking.party_size == party_size,
                    Booking.status.in_([
                        BookingStatus.PENDING.value,
                        BookingStatus.SCHEDULED.value,
                        BookingStatus.ATTEMPTING.value,
                    ]),
                )
            )
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                logger.info("booking_already_exists", booking_id=existing.id)
                return existing

            booking = Booking(
                restaurant_id=restaurant_id,
                party_size=party_size,
                target_date=target_date,
                preferred_times=preferred_times,
                monitor_cancellations=monitor_cancellations,
                release_datetime=release_datetime,
                status=BookingStatus.PENDING.value,
            )
            session.add(booking)
            await session.commit()
            await session.refresh(booking)

            logger.info(
                "created_booking",
                booking_id=booking.id,
                target_date=target_date,
            )
            return booking

    async def get_booking(self, booking_id: int) -> Booking | None:
        """Get booking by ID."""
        async with self.session_factory() as session:
            stmt = select(Booking).where(Booking.id == booking_id)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def get_active_bookings(self) -> list[Booking]:
        """Get all non-completed bookings."""
        async with self.session_factory() as session:
            stmt = select(Booking).where(
                Booking.status.in_([
                    BookingStatus.PENDING.value,
                    BookingStatus.SCHEDULED.value,
                    BookingStatus.ATTEMPTING.value,
                ])
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def get_bookings_by_restaurant(self, restaurant_id: int) -> list[Booking]:
        """Get all bookings for a restaurant."""
        async with self.session_factory() as session:
            stmt = select(Booking).where(Booking.restaurant_id == restaurant_id)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    async def update_booking_status(self, booking_id: int, status: str) -> None:
        """Update booking status."""
        async with self.session_factory() as session:
            stmt = (
                update(Booking)
                .where(Booking.id == booking_id)
                .values(status=status, updated_at=datetime.now())
            )
            await session.execute(stmt)
            await session.commit()

            logger.info("updated_booking_status", booking_id=booking_id, status=status)

    async def update_booking_success(
        self,
        booking_id: int,
        booked_time: str | None,
        confirmation_number: str | None,
    ) -> None:
        """Update booking with successful reservation details."""
        async with self.session_factory() as session:
            stmt = (
                update(Booking)
                .where(Booking.id == booking_id)
                .values(
                    status=BookingStatus.BOOKED.value,
                    booked_time=booked_time,
                    confirmation_number=confirmation_number,
                    booked_at=datetime.now(),
                    updated_at=datetime.now(),
                )
            )
            await session.execute(stmt)
            await session.commit()

            logger.info(
                "booking_success",
                booking_id=booking_id,
                time=booked_time,
                confirmation=confirmation_number,
            )

    # Booking attempt operations

    async def add_booking_attempt(
        self,
        booking_id: int,
        attempt_type: str,
        result: str,
        slot_time: str | None = None,
        error_message: str | None = None,
        duration_ms: int | None = None,
    ) -> BookingAttempt:
        """Record a booking attempt."""
        async with self.session_factory() as session:
            attempt = BookingAttempt(
                booking_id=booking_id,
                attempt_type=attempt_type,
                result=result,
                slot_time=slot_time,
                error_message=error_message,
                duration_ms=duration_ms,
            )
            session.add(attempt)
            await session.commit()
            await session.refresh(attempt)
            return attempt

    async def get_booking_attempts(
        self, booking_id: int, limit: int = 50
    ) -> list[BookingAttempt]:
        """Get attempts for a booking."""
        async with self.session_factory() as session:
            stmt = (
                select(BookingAttempt)
                .where(BookingAttempt.booking_id == booking_id)
                .order_by(BookingAttempt.attempted_at.desc())
                .limit(limit)
            )
            result = await session.execute(stmt)
            return list(result.scalars().all())

    # Platform session operations

    async def save_platform_session(
        self, platform: str, session_data: dict
    ) -> None:
        """Save platform session data."""
        async with self.session_factory() as session:
            stmt = select(PlatformSession).where(PlatformSession.platform == platform)
            result = await session.execute(stmt)
            existing = result.scalar_one_or_none()

            if existing:
                existing.session_data = json.dumps(session_data)
                existing.last_validated = datetime.now()
            else:
                ps = PlatformSession(
                    platform=platform,
                    session_data=json.dumps(session_data),
                    last_validated=datetime.now(),
                )
                session.add(ps)

            await session.commit()

    async def get_platform_session(self, platform: str) -> dict | None:
        """Get platform session data."""
        async with self.session_factory() as session:
            stmt = select(PlatformSession).where(PlatformSession.platform == platform)
            result = await session.execute(stmt)
            ps = result.scalar_one_or_none()

            if ps:
                return json.loads(ps.session_data)
            return None

    # Activity log operations

    async def log_activity(
        self,
        level: str,
        category: str,
        message: str,
        details: dict | None = None,
    ) -> None:
        """Log an activity."""
        async with self.session_factory() as session:
            log = ActivityLog(
                level=level,
                category=category,
                message=message,
                details=json.dumps(details) if details else None,
            )
            session.add(log)
            await session.commit()

    async def get_activity_log(
        self,
        category: str | None = None,
        limit: int = 100,
    ) -> list[ActivityLog]:
        """Get activity log entries."""
        async with self.session_factory() as session:
            stmt = select(ActivityLog).order_by(ActivityLog.created_at.desc())
            if category:
                stmt = stmt.where(ActivityLog.category == category)
            stmt = stmt.limit(limit)
            result = await session.execute(stmt)
            return list(result.scalars().all())

    # Dashboard queries

    async def get_dashboard_stats(self) -> dict:
        """Get statistics for dashboard."""
        async with self.session_factory() as session:
            # Count bookings by status
            bookings = await self.get_active_bookings()
            booked_stmt = select(Booking).where(Booking.status == BookingStatus.BOOKED.value)
            booked_result = await session.execute(booked_stmt)
            booked = list(booked_result.scalars().all())

            # Recent activity
            activity = await self.get_activity_log(limit=10)

            return {
                "active_bookings": len(bookings),
                "completed_bookings": len(booked),
                "recent_activity": [
                    {
                        "level": a.level,
                        "category": a.category,
                        "message": a.message,
                        "created_at": a.created_at.isoformat(),
                    }
                    for a in activity
                ],
            }
