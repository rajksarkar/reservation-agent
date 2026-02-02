"""Integration tests for the repository."""

import json

import pytest

from reservation_agent.db.models import BookingStatus
from reservation_agent.db.repository import Repository


@pytest.mark.asyncio
async def test_create_restaurant(repository: Repository):
    """Test creating a restaurant."""
    restaurant = await repository.get_or_create_restaurant(
        name="Test Restaurant",
        platform="resy",
        venue_id="test-venue",
    )

    assert restaurant.id is not None
    assert restaurant.name == "Test Restaurant"
    assert restaurant.platform == "resy"
    assert restaurant.venue_id == "test-venue"
    assert restaurant.enabled is True


@pytest.mark.asyncio
async def test_get_or_create_restaurant_idempotent(repository: Repository):
    """Test that get_or_create returns existing restaurant."""
    r1 = await repository.get_or_create_restaurant(
        name="Test",
        platform="resy",
        venue_id="test",
    )

    r2 = await repository.get_or_create_restaurant(
        name="Test Different Name",  # Different name
        platform="resy",
        venue_id="test",  # Same venue_id
    )

    assert r1.id == r2.id


@pytest.mark.asyncio
async def test_create_booking(repository: Repository):
    """Test creating a booking."""
    restaurant = await repository.get_or_create_restaurant(
        name="Test",
        platform="resy",
        venue_id="test",
    )

    booking = await repository.create_booking(
        restaurant_id=restaurant.id,
        party_size=2,
        target_date="2026-03-15",
        preferred_times=json.dumps(["19:00-20:00"]),
    )

    assert booking.id is not None
    assert booking.restaurant_id == restaurant.id
    assert booking.party_size == 2
    assert booking.target_date == "2026-03-15"
    assert booking.status == BookingStatus.PENDING.value


@pytest.mark.asyncio
async def test_update_booking_status(repository: Repository):
    """Test updating booking status."""
    restaurant = await repository.get_or_create_restaurant(
        name="Test",
        platform="resy",
        venue_id="test",
    )

    booking = await repository.create_booking(
        restaurant_id=restaurant.id,
        party_size=2,
        target_date="2026-03-15",
        preferred_times=json.dumps([]),
    )

    await repository.update_booking_status(booking.id, BookingStatus.ATTEMPTING.value)

    updated = await repository.get_booking(booking.id)
    assert updated.status == BookingStatus.ATTEMPTING.value


@pytest.mark.asyncio
async def test_update_booking_success(repository: Repository):
    """Test marking a booking as successful."""
    restaurant = await repository.get_or_create_restaurant(
        name="Test",
        platform="resy",
        venue_id="test",
    )

    booking = await repository.create_booking(
        restaurant_id=restaurant.id,
        party_size=2,
        target_date="2026-03-15",
        preferred_times=json.dumps([]),
    )

    await repository.update_booking_success(
        booking_id=booking.id,
        booked_time="19:30",
        confirmation_number="ABC123",
    )

    updated = await repository.get_booking(booking.id)
    assert updated.status == BookingStatus.BOOKED.value
    assert updated.booked_time == "19:30"
    assert updated.confirmation_number == "ABC123"
    assert updated.booked_at is not None


@pytest.mark.asyncio
async def test_add_booking_attempt(repository: Repository):
    """Test recording booking attempts."""
    restaurant = await repository.get_or_create_restaurant(
        name="Test",
        platform="resy",
        venue_id="test",
    )

    booking = await repository.create_booking(
        restaurant_id=restaurant.id,
        party_size=2,
        target_date="2026-03-15",
        preferred_times=json.dumps([]),
    )

    attempt = await repository.add_booking_attempt(
        booking_id=booking.id,
        attempt_type="snipe",
        result="slot_taken",
        slot_time="19:00",
        error_message="Slot was taken",
        duration_ms=1500,
    )

    assert attempt.id is not None
    assert attempt.booking_id == booking.id
    assert attempt.result == "slot_taken"

    attempts = await repository.get_booking_attempts(booking.id)
    assert len(attempts) == 1


@pytest.mark.asyncio
async def test_get_active_bookings(repository: Repository):
    """Test getting active bookings."""
    restaurant = await repository.get_or_create_restaurant(
        name="Test",
        platform="resy",
        venue_id="test",
    )

    # Create pending booking
    await repository.create_booking(
        restaurant_id=restaurant.id,
        party_size=2,
        target_date="2026-03-15",
        preferred_times=json.dumps([]),
    )

    # Create booked booking
    booked = await repository.create_booking(
        restaurant_id=restaurant.id,
        party_size=2,
        target_date="2026-03-16",
        preferred_times=json.dumps([]),
    )
    await repository.update_booking_status(booked.id, BookingStatus.BOOKED.value)

    active = await repository.get_active_bookings()
    assert len(active) == 1
    assert active[0].target_date == "2026-03-15"


@pytest.mark.asyncio
async def test_log_activity(repository: Repository):
    """Test activity logging."""
    await repository.log_activity(
        level="info",
        category="booking",
        message="Test activity",
        details={"key": "value"},
    )

    logs = await repository.get_activity_log(limit=10)
    assert len(logs) == 1
    assert logs[0].level == "info"
    assert logs[0].message == "Test activity"


@pytest.mark.asyncio
async def test_dashboard_stats(repository: Repository):
    """Test dashboard statistics."""
    restaurant = await repository.get_or_create_restaurant(
        name="Test",
        platform="resy",
        venue_id="test",
    )

    # Create some bookings
    await repository.create_booking(
        restaurant_id=restaurant.id,
        party_size=2,
        target_date="2026-03-15",
        preferred_times=json.dumps([]),
    )

    stats = await repository.get_dashboard_stats()
    assert "active_bookings" in stats
    assert "completed_bookings" in stats
    assert stats["active_bookings"] == 1
