"""Abstract base class for reservation platforms."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from playwright.async_api import Page

from reservation_agent.browser.session_manager import SessionManager
from reservation_agent.core.config import PlatformCredential, RestaurantConfig
from reservation_agent.utils.logging import get_logger


@dataclass
class TimeSlot:
    """Represents an available reservation time slot."""

    time: str  # HH:MM format
    slot_id: str  # Platform-specific ID
    slot_type: str | None = None  # e.g., "dining room", "bar", "patio"
    deposit_required: float | None = None
    raw_data: dict | None = None  # Platform-specific raw data


@dataclass
class AvailabilityResult:
    """Result of checking availability."""

    available_slots: list[TimeSlot]
    date: str
    party_size: int
    checked_at: datetime
    raw_response: dict | None = None


@dataclass
class BookingResult:
    """Result of a booking attempt."""

    success: bool
    confirmation_number: str | None = None
    booked_time: str | None = None
    error_message: str | None = None
    raw_response: dict | None = None


class BasePlatform(ABC):
    """Abstract base class for reservation platform integrations."""

    PLATFORM_NAME: str = "base"
    BASE_URL: str = ""

    def __init__(
        self,
        session_manager: SessionManager,
        credentials: PlatformCredential | None = None,
    ):
        self.session_manager = session_manager
        self.credentials = credentials
        self.logger = get_logger(f"platform.{self.PLATFORM_NAME}")
        self._page: Page | None = None

    async def get_page(self) -> Page:
        """Get or create a page for this platform."""
        if self._page is None or self._page.is_closed():
            self._page = await self.session_manager.get_page(self.PLATFORM_NAME)
        return self._page

    async def close_page(self) -> None:
        """Close the current page."""
        if self._page and not self._page.is_closed():
            await self._page.close()
            self._page = None

    @abstractmethod
    async def login(self) -> bool:
        """
        Log in to the platform.

        Returns True if login successful, False otherwise.
        Should use stored session if available and valid.
        """
        pass

    @abstractmethod
    async def check_session_valid(self) -> bool:
        """
        Check if current session is valid/logged in.

        Returns True if session is valid, False if re-login needed.
        """
        pass

    @abstractmethod
    async def check_availability(
        self,
        restaurant: RestaurantConfig,
        date: str,
        party_size: int,
    ) -> AvailabilityResult:
        """
        Check availability for a restaurant on a specific date.

        Args:
            restaurant: Restaurant configuration
            date: Date to check (YYYY-MM-DD format)
            party_size: Number of guests

        Returns:
            AvailabilityResult with available slots
        """
        pass

    @abstractmethod
    async def book_slot(
        self,
        restaurant: RestaurantConfig,
        slot: TimeSlot,
        party_size: int,
        dry_run: bool = False,
    ) -> BookingResult:
        """
        Book a specific time slot.

        Args:
            restaurant: Restaurant configuration
            slot: The slot to book
            party_size: Number of guests
            dry_run: If True, stop before final confirmation

        Returns:
            BookingResult indicating success/failure
        """
        pass

    def matches_preferred_time(
        self, slot_time: str, preferred_times: list[str]
    ) -> bool:
        """Check if a slot time matches any preferred time range."""
        if not preferred_times:
            return True

        slot_minutes = self._time_to_minutes(slot_time)

        for time_range in preferred_times:
            if "-" in time_range:
                start, end = time_range.split("-")
                start_minutes = self._time_to_minutes(start.strip())
                end_minutes = self._time_to_minutes(end.strip())
                if start_minutes <= slot_minutes <= end_minutes:
                    return True
            else:
                # Exact time match (with 30 min tolerance)
                target_minutes = self._time_to_minutes(time_range.strip())
                if abs(slot_minutes - target_minutes) <= 30:
                    return True

        return False

    def _time_to_minutes(self, time_str: str) -> int:
        """Convert HH:MM to minutes since midnight."""
        parts = time_str.split(":")
        return int(parts[0]) * 60 + int(parts[1])

    def filter_preferred_slots(
        self, slots: list[TimeSlot], preferred_times: list[str]
    ) -> list[TimeSlot]:
        """Filter slots to only those matching preferred times."""
        return [s for s in slots if self.matches_preferred_time(s.time, preferred_times)]

    async def ensure_logged_in(self) -> bool:
        """Ensure we have a valid session, logging in if necessary."""
        if await self.check_session_valid():
            self.logger.info("session_valid")
            return True

        self.logger.info("session_invalid_logging_in")
        if not self.credentials:
            self.logger.error("no_credentials_available")
            return False

        return await self.login()

    async def save_session(self) -> None:
        """Save the current session state."""
        await self.session_manager.save_session(self.PLATFORM_NAME)
