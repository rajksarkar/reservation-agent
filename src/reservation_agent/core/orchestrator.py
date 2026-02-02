"""Main orchestration logic for the reservation agent."""

import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from reservation_agent.browser.session_manager import SessionManager
from reservation_agent.core.config import AgentConfig, RestaurantConfig
from reservation_agent.core.exceptions import (
    AuthenticationError,
    BookingError,
    CircuitBreakerOpenError,
    PlatformError,
    SlotUnavailableError,
)
from reservation_agent.core.scheduler import JobScheduler, RapidPoller
from reservation_agent.db.models import (
    AttemptResult,
    Booking,
    BookingAttempt,
    BookingStatus,
    Restaurant,
    init_database,
    get_session_factory,
)
from reservation_agent.db.repository import Repository
from reservation_agent.notifications.email import EmailNotifier
from reservation_agent.platforms.base import BasePlatform, TimeSlot
from reservation_agent.platforms.opentable import OpenTablePlatform
from reservation_agent.platforms.resy import ResyPlatform
from reservation_agent.platforms.tock import TockPlatform
from reservation_agent.utils.logging import get_logger, LogContext
from reservation_agent.utils.retry import CircuitBreaker, RetryConfig, retry_with_backoff

logger = get_logger(__name__)


class Orchestrator:
    """Coordinates all reservation agent activities."""

    PLATFORM_CLASSES = {
        "resy": ResyPlatform,
        "opentable": OpenTablePlatform,
        "tock": TockPlatform,
    }

    def __init__(self, config: AgentConfig, base_dir: Path | None = None):
        self.config = config
        self.base_dir = base_dir or Path.cwd()
        self.dry_run = config.dry_run

        # Components (initialized in start())
        self.session_manager: SessionManager | None = None
        self.scheduler: JobScheduler | None = None
        self.repository: Repository | None = None
        self.notifier: EmailNotifier | None = None

        # Platforms
        self.platforms: dict[str, BasePlatform] = {}
        self.circuit_breakers: dict[str, CircuitBreaker] = {}

        self._running = False
        self._shutdown_event = asyncio.Event()

    async def start(
        self,
        *,
        enable_scheduler: bool = True,
        init_db: bool = True,
    ) -> None:
        """Initialize and start all components.

        Args:
            enable_scheduler: If False, skip scheduler (avoids pickle issues for
                CLI commands like check that don't need scheduling).
            init_db: If False, skip database init (for check-only usage).
        """
        logger.info("starting_orchestrator", dry_run=self.dry_run)

        if init_db:
            engine = await init_database(self.config.database_url)
            session_factory = get_session_factory(engine)
            self.repository = Repository(session_factory)

        # Initialize browser session manager
        self.session_manager = SessionManager(self.config.browser, self.base_dir)
        await self.session_manager.start()

        # Initialize platforms
        await self._init_platforms()

        if enable_scheduler:
            # Initialize scheduler (requires DB - uses SQLAlchemyJobStore)
            if not self.repository:
                raise RuntimeError("Database must be initialized for scheduler")
            self.scheduler = JobScheduler(
                self.config.scheduler,
                self.config.database_url,
                self.base_dir,
            )
            self.scheduler.start()

            # Initialize email notifier
            self.notifier = EmailNotifier(self.config.smtp)

            # Schedule jobs from config
            await self._schedule_from_config()
        else:
            self.notifier = EmailNotifier(self.config.smtp)

        self._running = True
        logger.info("orchestrator_started")

    async def stop(self) -> None:
        """Stop all components gracefully."""
        logger.info("stopping_orchestrator")
        self._shutdown_event.set()

        if self.scheduler:
            self.scheduler.shutdown(wait=True)

        if self.session_manager:
            await self.session_manager.stop()

        self._running = False
        logger.info("orchestrator_stopped")

    async def _init_platforms(self) -> None:
        """Initialize platform instances."""
        for platform_name, platform_class in self.PLATFORM_CLASSES.items():
            credentials = self.config.get_credential(platform_name)
            platform = platform_class(self.session_manager, credentials)
            self.platforms[platform_name] = platform
            self.circuit_breakers[platform_name] = CircuitBreaker(
                name=platform_name,
                failure_threshold=5,
                recovery_timeout=60.0,
            )
            logger.info("initialized_platform", platform=platform_name)

    async def _schedule_from_config(self) -> None:
        """Create scheduled jobs from configuration."""
        for restaurant_config in self.config.restaurants:
            if not restaurant_config.enabled:
                continue

            # Ensure restaurant exists in database
            restaurant = await self.repository.get_or_create_restaurant(
                name=restaurant_config.name,
                platform=restaurant_config.platform,
                venue_id=restaurant_config.venue_id,
            )

            for target_date in restaurant_config.target_dates:
                # Create booking record
                booking = await self.repository.create_booking(
                    restaurant_id=restaurant.id,
                    party_size=restaurant_config.party_size,
                    target_date=target_date,
                    preferred_times=json.dumps(restaurant_config.preferred_times),
                    monitor_cancellations=restaurant_config.monitor_cancellations,
                )

                # Schedule release snipe
                job_id = f"snipe_{restaurant.id}_{target_date}"
                self.scheduler.schedule_release_snipe(
                    job_id=job_id,
                    target_date=target_date,
                    release_time=restaurant_config.release_time,
                    release_days_ahead=restaurant_config.release_days_ahead,
                    callback=self._handle_release_snipe,
                    booking_id=booking.id,
                    restaurant_config=restaurant_config,
                )

                # Schedule cancellation monitoring
                if restaurant_config.monitor_cancellations:
                    monitor_job_id = f"monitor_{restaurant.id}_{target_date}"
                    self.scheduler.schedule_cancellation_monitor(
                        job_id=monitor_job_id,
                        callback=self._handle_cancellation_check,
                        booking_id=booking.id,
                        restaurant_config=restaurant_config,
                    )

        logger.info(
            "scheduled_jobs",
            count=len(self.scheduler.get_jobs()),
        )

    async def _handle_release_snipe(
        self,
        booking_id: int,
        restaurant_config: RestaurantConfig,
    ) -> None:
        """Handle a release snipe event."""
        with LogContext(booking_id=booking_id, restaurant=restaurant_config.name):
            logger.info("starting_release_snipe")

            booking = await self.repository.get_booking(booking_id)
            if not booking or booking.status == BookingStatus.BOOKED.value:
                logger.info("booking_already_completed")
                return

            await self.repository.update_booking_status(
                booking_id, BookingStatus.ATTEMPTING.value
            )

            platform = self.platforms.get(restaurant_config.platform)
            if not platform:
                logger.error("platform_not_found", platform=restaurant_config.platform)
                return

            # Ensure logged in
            if not await platform.ensure_logged_in():
                logger.error("login_failed")
                await self._notify_auth_required(restaurant_config.platform)
                return

            # Rapid poll for availability
            poller = RapidPoller(
                interval_ms=self.config.scheduler.snipe_rapid_poll_interval * 1000,
                duration_seconds=self.config.scheduler.snipe_duration,
            )

            success = await poller.poll(
                self._try_book,
                platform=platform,
                booking=booking,
                restaurant_config=restaurant_config,
            )

            if not success:
                logger.warning("snipe_failed_no_slots")
                await self.repository.update_booking_status(
                    booking_id, BookingStatus.PENDING.value
                )

    async def _handle_cancellation_check(
        self,
        booking_id: int,
        restaurant_config: RestaurantConfig,
    ) -> None:
        """Check for cancellations and attempt to book."""
        with LogContext(booking_id=booking_id, restaurant=restaurant_config.name):
            booking = await self.repository.get_booking(booking_id)
            if not booking or booking.status == BookingStatus.BOOKED.value:
                return

            platform = self.platforms.get(restaurant_config.platform)
            circuit_breaker = self.circuit_breakers.get(restaurant_config.platform)

            if not platform or not circuit_breaker:
                return

            try:
                await circuit_breaker.call(
                    self._check_and_book,
                    platform=platform,
                    booking=booking,
                    restaurant_config=restaurant_config,
                )
            except CircuitBreakerOpenError:
                logger.warning("circuit_breaker_open")
            except AuthenticationError:
                await self._notify_auth_required(restaurant_config.platform)
            except Exception as e:
                logger.error("cancellation_check_error", error=str(e))

    async def _check_and_book(
        self,
        platform: BasePlatform,
        booking: Booking,
        restaurant_config: RestaurantConfig,
    ) -> bool:
        """Check availability and book if slot found."""
        # Ensure logged in
        if not await platform.ensure_logged_in():
            raise AuthenticationError(platform.PLATFORM_NAME, "Session invalid")

        # Check availability
        result = await platform.check_availability(
            restaurant_config,
            booking.target_date,
            booking.party_size,
        )

        if not result.available_slots:
            logger.debug("no_slots_available")
            return False

        # Filter to preferred times
        preferred_times = json.loads(booking.preferred_times)
        matching_slots = platform.filter_preferred_slots(
            result.available_slots, preferred_times
        )

        if not matching_slots:
            logger.debug("no_matching_slots", available=len(result.available_slots))
            return False

        # Try to book the first matching slot
        return await self._try_book(
            platform=platform,
            booking=booking,
            restaurant_config=restaurant_config,
            slots=matching_slots,
        )

    async def _try_book(
        self,
        platform: BasePlatform,
        booking: Booking,
        restaurant_config: RestaurantConfig,
        slots: list[TimeSlot] | None = None,
    ) -> bool:
        """Attempt to book a slot."""
        start_time = datetime.now()

        # Get available slots if not provided
        if slots is None:
            result = await platform.check_availability(
                restaurant_config,
                booking.target_date,
                booking.party_size,
            )
            preferred_times = json.loads(booking.preferred_times)
            slots = platform.filter_preferred_slots(
                result.available_slots, preferred_times
            )

        if not slots:
            return False

        # Try each slot
        for slot in slots:
            try:
                logger.info("attempting_book", slot_time=slot.time)

                book_result = await platform.book_slot(
                    restaurant_config,
                    slot,
                    booking.party_size,
                    dry_run=self.dry_run,
                )

                duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

                if book_result.success:
                    # Update booking record
                    await self.repository.update_booking_success(
                        booking.id,
                        booked_time=book_result.booked_time,
                        confirmation_number=book_result.confirmation_number,
                    )

                    # Record attempt
                    await self.repository.add_booking_attempt(
                        booking_id=booking.id,
                        attempt_type="snipe",
                        result=AttemptResult.SUCCESS.value,
                        slot_time=slot.time,
                        duration_ms=duration_ms,
                    )

                    # Send notification
                    await self._notify_booking_success(
                        restaurant_config,
                        booking,
                        book_result.booked_time,
                        book_result.confirmation_number,
                    )

                    logger.info(
                        "booking_successful",
                        confirmation=book_result.confirmation_number,
                    )
                    return True

                else:
                    # Record failed attempt
                    await self.repository.add_booking_attempt(
                        booking_id=booking.id,
                        attempt_type="snipe",
                        result=AttemptResult.SLOT_TAKEN.value,
                        slot_time=slot.time,
                        error_message=book_result.error_message,
                        duration_ms=duration_ms,
                    )

            except SlotUnavailableError:
                logger.warning("slot_unavailable", slot_time=slot.time)
                continue
            except Exception as e:
                logger.error("booking_error", slot_time=slot.time, error=str(e))
                await self.repository.add_booking_attempt(
                    booking_id=booking.id,
                    attempt_type="snipe",
                    result=AttemptResult.ERROR.value,
                    slot_time=slot.time,
                    error_message=str(e),
                )
                continue

        return False

    async def _notify_booking_success(
        self,
        restaurant_config: RestaurantConfig,
        booking: Booking,
        booked_time: str | None,
        confirmation_number: str | None,
    ) -> None:
        """Send success notification."""
        if self.notifier:
            await self.notifier.send_booking_success(
                restaurant_name=restaurant_config.name,
                date=booking.target_date,
                time=booked_time or "Unknown",
                party_size=booking.party_size,
                confirmation_number=confirmation_number,
            )

    async def _notify_auth_required(self, platform: str) -> None:
        """Send notification that re-authentication is needed."""
        if self.notifier:
            await self.notifier.send_auth_required(platform=platform)

    async def run_forever(self) -> None:
        """Run the orchestrator until shutdown."""
        while self._running and not self._shutdown_event.is_set():
            await asyncio.sleep(1)

    # Manual operations

    async def manual_check(
        self,
        restaurant_name: str,
        date: str,
        party_size: int,
    ) -> dict:
        """Manually check availability for a restaurant."""
        # Find restaurant config
        restaurant_config = None
        for r in self.config.restaurants:
            if r.name.lower() == restaurant_name.lower():
                restaurant_config = r
                break

        if not restaurant_config:
            return {"error": f"Restaurant '{restaurant_name}' not found in config"}

        platform = self.platforms.get(restaurant_config.platform)
        if not platform:
            return {"error": f"Platform '{restaurant_config.platform}' not available"}

        if not await platform.ensure_logged_in():
            return {"error": "Login failed"}

        result = await platform.check_availability(restaurant_config, date, party_size)

        return {
            "restaurant": restaurant_name,
            "date": date,
            "party_size": party_size,
            "slots": [
                {
                    "time": s.time,
                    "type": s.slot_type,
                    "deposit": s.deposit_required,
                }
                for s in result.available_slots
            ],
        }

    async def trigger_snipe(self, booking_id: int) -> dict:
        """Manually trigger a snipe attempt."""
        booking = await self.repository.get_booking(booking_id)
        if not booking:
            return {"error": "Booking not found"}

        # Find matching restaurant config
        restaurant = await self.repository.get_restaurant(booking.restaurant_id)
        restaurant_config = None
        for r in self.config.restaurants:
            if r.venue_id == restaurant.venue_id:
                restaurant_config = r
                break

        if not restaurant_config:
            return {"error": "Restaurant config not found"}

        await self._handle_release_snipe(booking_id, restaurant_config)
        return {"status": "triggered"}
