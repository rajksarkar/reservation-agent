"""Reservations API routes."""

import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from reservation_agent.api.app import get_orchestrator
from reservation_agent.db.models import BookingStatus
from reservation_agent.db.repository import Repository

router = APIRouter()


def get_repository(request: Request) -> Repository:
    """Dependency to get repository from app state."""
    return request.app.state.repository


class CreateBookingRequest(BaseModel):
    """Request to create a new booking."""

    restaurant_id: int
    party_size: int
    target_date: str
    preferred_times: list[str]
    monitor_cancellations: bool = True


class TriggerSnipeRequest(BaseModel):
    """Request to trigger a manual snipe."""

    booking_id: int


@router.get("/reservations")
async def list_reservations(
    repository: Repository = Depends(get_repository),
    status: str | None = None,
):
    """List all reservations/bookings."""
    bookings = await repository.get_active_bookings()

    if status:
        bookings = [b for b in bookings if b.status == status]

    result = []
    for booking in bookings:
        restaurant = await repository.get_restaurant(booking.restaurant_id)
        result.append({
            "id": booking.id,
            "restaurant": {
                "id": restaurant.id,
                "name": restaurant.name,
                "platform": restaurant.platform,
            } if restaurant else None,
            "party_size": booking.party_size,
            "target_date": booking.target_date,
            "preferred_times": json.loads(booking.preferred_times),
            "status": booking.status,
            "booked_time": booking.booked_time,
            "confirmation_number": booking.confirmation_number,
            "booked_at": booking.booked_at.isoformat() if booking.booked_at else None,
            "created_at": booking.created_at.isoformat(),
        })

    return {"reservations": result}


@router.get("/reservations/{booking_id}")
async def get_reservation(
    booking_id: int,
    repository: Repository = Depends(get_repository),
):
    """Get a specific reservation."""
    booking = await repository.get_booking(booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    restaurant = await repository.get_restaurant(booking.restaurant_id)
    attempts = await repository.get_booking_attempts(booking_id)

    return {
        "id": booking.id,
        "restaurant": {
            "id": restaurant.id,
            "name": restaurant.name,
            "platform": restaurant.platform,
        } if restaurant else None,
        "party_size": booking.party_size,
        "target_date": booking.target_date,
        "preferred_times": json.loads(booking.preferred_times),
        "status": booking.status,
        "booked_time": booking.booked_time,
        "confirmation_number": booking.confirmation_number,
        "booked_at": booking.booked_at.isoformat() if booking.booked_at else None,
        "release_datetime": booking.release_datetime.isoformat() if booking.release_datetime else None,
        "monitor_cancellations": booking.monitor_cancellations,
        "created_at": booking.created_at.isoformat(),
        "attempts": [
            {
                "id": a.id,
                "type": a.attempt_type,
                "result": a.result,
                "slot_time": a.slot_time,
                "error": a.error_message,
                "duration_ms": a.duration_ms,
                "attempted_at": a.attempted_at.isoformat(),
            }
            for a in attempts
        ],
    }


@router.post("/reservations")
async def create_reservation(
    request: CreateBookingRequest,
    repository: Repository = Depends(get_repository),
):
    """Create a new reservation request."""
    booking = await repository.create_booking(
        restaurant_id=request.restaurant_id,
        party_size=request.party_size,
        target_date=request.target_date,
        preferred_times=json.dumps(request.preferred_times),
        monitor_cancellations=request.monitor_cancellations,
    )

    return {
        "id": booking.id,
        "status": booking.status,
        "created_at": booking.created_at.isoformat(),
    }


@router.post("/reservations/{booking_id}/cancel")
async def cancel_reservation(
    booking_id: int,
    repository: Repository = Depends(get_repository),
):
    """Cancel a reservation request (stops monitoring)."""
    booking = await repository.get_booking(booking_id)
    if not booking:
        raise HTTPException(status_code=404, detail="Booking not found")

    await repository.update_booking_status(booking_id, BookingStatus.CANCELLED.value)

    # Remove scheduled jobs
    orchestrator = get_orchestrator()
    if orchestrator and orchestrator.scheduler:
        orchestrator.scheduler.remove_job(f"snipe_{booking.restaurant_id}_{booking.target_date}")
        orchestrator.scheduler.remove_job(f"monitor_{booking.restaurant_id}_{booking.target_date}")

    return {"status": "cancelled"}


@router.post("/reservations/trigger-snipe")
async def trigger_snipe(
    request: TriggerSnipeRequest,
):
    """Manually trigger a snipe attempt."""
    orchestrator = get_orchestrator()
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not available")

    result = await orchestrator.trigger_snipe(request.booking_id)
    return result


@router.post("/reservations/check-availability")
async def check_availability(
    restaurant_name: str,
    date: str,
    party_size: int = 2,
):
    """Manually check availability for a restaurant."""
    orchestrator = get_orchestrator()
    if not orchestrator:
        raise HTTPException(status_code=503, detail="Orchestrator not available")

    result = await orchestrator.manual_check(restaurant_name, date, party_size)
    return result
