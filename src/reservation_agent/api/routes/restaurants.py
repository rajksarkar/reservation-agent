"""Restaurants API routes."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from reservation_agent.db.repository import Repository

router = APIRouter()


def get_repository(request: Request) -> Repository:
    """Dependency to get repository from app state."""
    return request.app.state.repository


class CreateRestaurantRequest(BaseModel):
    """Request to create a new restaurant."""

    name: str
    platform: str
    venue_id: str


@router.get("/restaurants")
async def list_restaurants(
    repository: Repository = Depends(get_repository),
    enabled_only: bool = True,
):
    """List all restaurants."""
    restaurants = await repository.get_restaurants(enabled_only=enabled_only)

    return {
        "restaurants": [
            {
                "id": r.id,
                "name": r.name,
                "platform": r.platform,
                "venue_id": r.venue_id,
                "enabled": r.enabled,
                "created_at": r.created_at.isoformat(),
            }
            for r in restaurants
        ]
    }


@router.get("/restaurants/{restaurant_id}")
async def get_restaurant(
    restaurant_id: int,
    repository: Repository = Depends(get_repository),
):
    """Get a specific restaurant."""
    restaurant = await repository.get_restaurant(restaurant_id)
    if not restaurant:
        raise HTTPException(status_code=404, detail="Restaurant not found")

    bookings = await repository.get_bookings_by_restaurant(restaurant_id)

    return {
        "id": restaurant.id,
        "name": restaurant.name,
        "platform": restaurant.platform,
        "venue_id": restaurant.venue_id,
        "enabled": restaurant.enabled,
        "created_at": restaurant.created_at.isoformat(),
        "bookings": [
            {
                "id": b.id,
                "target_date": b.target_date,
                "party_size": b.party_size,
                "status": b.status,
            }
            for b in bookings
        ],
    }


@router.post("/restaurants")
async def create_restaurant(
    request: CreateRestaurantRequest,
    repository: Repository = Depends(get_repository),
):
    """Create a new restaurant."""
    restaurant = await repository.get_or_create_restaurant(
        name=request.name,
        platform=request.platform,
        venue_id=request.venue_id,
    )

    return {
        "id": restaurant.id,
        "name": restaurant.name,
        "platform": restaurant.platform,
        "venue_id": restaurant.venue_id,
        "created_at": restaurant.created_at.isoformat(),
    }
