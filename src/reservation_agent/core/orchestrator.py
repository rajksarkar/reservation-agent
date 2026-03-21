"""Local single-user orchestrator.

Reads restaurants and credentials from config.yaml, runs cancellation
monitoring and release snipes using the existing platform classes.
"""

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from reservation_agent.browser.session_manager import SessionManager
from reservation_agent.core.config import AgentConfig, RestaurantConfig
from reservation_agent.core.exceptions import (
    AuthenticationError,
    SlotUnavailableError,
)
from reservation_agent.core.scheduler import RapidPoller
from reservation_agent.platforms.base import BasePlatform, TimeSlot
from reservation_agent.platforms.opentable import OpenTablePlatform
from reservation_agent.platforms.resy import ResyPlatform
from reservation_agent.platforms.tock import TockPlatform
from reservation_agent.utils.logging import get_logger, LogContext

logger = get_logger(__name__)


class Orchestrator:
    """Single-user local orchestrator that processes restaurants from config.yaml."""

    PLATFORM_CLASSES = {
        "resy": ResyPlatform,
        "opentable": OpenTablePlatform,
        "tock": TockPlatform,
    }

    def __init__(self, config: AgentConfig, base_dir: Path | None = None):
        self.config = config
        self.base_dir = base_dir or Path.cwd()

        # Platform instances keyed by platform name
        self._platforms: dict[str, BasePlatform] = {}
        self.session_manager: SessionManager | None = None
        self._running = False

        # Snipe scheduling state
        self._scheduled_snipes: set[str] = set()
        self._active_snipe_restaurants: set[str] = set()

    async def start(self) -> None:
        """Initialize browser session manager."""
        logger.info("starting_orchestrator")
        self.session_manager = SessionManager(self.config.browser, self.base_dir)
        await self.session_manager.start()
        self._running = True
        logger.info("orchestrator_started")

    async def stop(self) -> None:
        """Shut down gracefully."""
        logger.info("stopping_orchestrator")
        self._running = False
        if self.session_manager:
            await self.session_manager.stop()
        logger.info("orchestrator_stopped")

    async def run_forever(self) -> None:
        """Main polling loop: process enabled restaurants on interval."""
        poll_interval = self.config.scheduler.cancellation_poll_interval
        while self._running:
            try:
                await self._poll_and_process()
            except Exception as e:
                logger.error("poll_error", error=str(e))
            await asyncio.sleep(poll_interval)

    async def _poll_and_process(self) -> None:
        """Process all enabled restaurants from config."""
        restaurants = [r for r in self.config.restaurants if r.enabled]
        if not restaurants:
            return

        logger.info("processing_restaurants", count=len(restaurants))

        # Schedule snipes for restaurants with upcoming release windows
        for restaurant in restaurants:
            self._schedule_snipes(restaurant)

        # Filter to restaurants that should be cancellation-polled
        cancellation_restaurants = [
            r for r in restaurants
            if r.name not in self._active_snipe_restaurants
            and r.monitor_cancellations
        ]

        if not cancellation_restaurants:
            return

        # Process with per-platform concurrency limits
        platform_sems: dict[str, asyncio.Semaphore] = {
            "opentable": asyncio.Semaphore(1),
            "resy": asyncio.Semaphore(2),
            "tock": asyncio.Semaphore(2),
        }

        async def process_with_sem(restaurant: RestaurantConfig) -> None:
            sem = platform_sems.get(restaurant.platform, asyncio.Semaphore(1))
            async with sem:
                await self._process_restaurant(restaurant)

        await asyncio.gather(
            *[process_with_sem(r) for r in cancellation_restaurants],
            return_exceptions=True,
        )

    async def _process_restaurant(self, restaurant: RestaurantConfig) -> None:
        """Process a single restaurant config: check availability and book."""
        with LogContext(restaurant=restaurant.name, platform=restaurant.platform):
            platform = await self._get_platform(restaurant.platform)
            if not platform:
                logger.warning("no_platform_credentials", platform=restaurant.platform)
                return

            try:
                if not await platform.ensure_logged_in():
                    logger.error("login_failed")
                    return
            except AuthenticationError as e:
                logger.error("auth_error", error=str(e))
                return

            for target_date in restaurant.target_dates:
                if self._is_date_unreleased(target_date, restaurant):
                    continue

                start_time = datetime.now()

                # OpenTable: single-page check+book
                if isinstance(platform, OpenTablePlatform):
                    booked = await self._opentable_poll_attempt(
                        platform, restaurant, target_date, start_time,
                    )
                    if booked:
                        return
                    continue

                try:
                    result = await platform.check_availability(
                        restaurant, target_date, restaurant.party_size
                    )
                except Exception as e:
                    logger.error("availability_check_error", error=str(e), date=target_date)
                    continue

                if not result.available_slots:
                    logger.info("no_availability", date=target_date)
                    continue

                matching_slots = platform.filter_preferred_slots(
                    result.available_slots, restaurant.preferred_times
                )

                if not matching_slots:
                    logger.info("no_matching_slots", date=target_date)
                    continue

                booked = await self._try_book(
                    platform, restaurant, matching_slots,
                    restaurant.party_size, target_date, start_time,
                )
                if booked:
                    return

    async def _try_book(
        self,
        platform: BasePlatform,
        restaurant: RestaurantConfig,
        slots: list[TimeSlot],
        party_size: int,
        target_date: str,
        start_time: datetime,
    ) -> bool:
        """Attempt to book one of the matching slots."""
        for slot in slots:
            try:
                logger.info("attempting_book", slot_time=slot.time, date=target_date)

                book_result = await platform.book_slot(
                    restaurant, slot, party_size,
                    dry_run=self.config.dry_run, date=target_date,
                )

                if book_result.success:
                    logger.info(
                        "booking_successful",
                        restaurant=restaurant.name,
                        date=target_date,
                        time=book_result.booked_time,
                        confirmation=book_result.confirmation_number,
                    )
                    # Mark restaurant as done by disabling it
                    restaurant.enabled = False
                    return True
                else:
                    logger.warning(
                        "booking_failed",
                        slot_time=slot.time,
                        error=book_result.error_message,
                    )
            except SlotUnavailableError:
                logger.warning("slot_unavailable", slot_time=slot.time)
                continue
            except Exception as e:
                logger.error("booking_error", slot_time=slot.time, error=str(e))
                continue

        return False

    def _schedule_snipes(self, restaurant: RestaurantConfig) -> None:
        """Schedule snipe tasks for upcoming release windows."""
        et = ZoneInfo("America/New_York")
        now = datetime.now(tz=et)
        wake_before = self.config.scheduler.snipe_wake_before
        snipe_duration = self.config.scheduler.snipe_duration

        time_parts = restaurant.release_time.split(":")
        release_hour, release_minute = int(time_parts[0]), int(time_parts[1])

        for target_date in restaurant.target_dates:
            snipe_id = f"{restaurant.name}_{target_date}"
            if snipe_id in self._scheduled_snipes:
                continue

            target = datetime.strptime(target_date, "%Y-%m-%d").replace(tzinfo=et)
            release_date = target - timedelta(days=restaurant.release_days_ahead)
            release_dt = release_date.replace(
                hour=release_hour, minute=release_minute, second=0, microsecond=0
            )
            wake_dt = release_dt - timedelta(seconds=wake_before)
            end_dt = release_dt + timedelta(seconds=snipe_duration)

            if now > end_dt:
                continue

            # Only schedule if wake time is within the next 2 hours
            if wake_dt > now + timedelta(hours=2):
                continue

            self._scheduled_snipes.add(snipe_id)

            logger.info(
                "snipe_scheduled",
                restaurant=restaurant.name,
                target_date=target_date,
                release_dt=release_dt.isoformat(),
                wake_dt=wake_dt.isoformat(),
            )

            asyncio.create_task(
                self._execute_snipe(snipe_id, restaurant, target_date, wake_dt)
            )

    async def _execute_snipe(
        self, snipe_id: str, restaurant: RestaurantConfig,
        target_date: str, wake_dt: datetime,
    ) -> None:
        """Execute a snipe: sleep until wake time, then rapid-poll for slots."""
        try:
            self._active_snipe_restaurants.add(restaurant.name)

            et = ZoneInfo("America/New_York")
            now = datetime.now(tz=et)
            if wake_dt > now:
                sleep_seconds = (wake_dt - now).total_seconds()
                logger.info(
                    "snipe_sleeping",
                    restaurant=restaurant.name,
                    sleep_seconds=int(sleep_seconds),
                )
                await asyncio.sleep(sleep_seconds)

            with LogContext(restaurant=restaurant.name, platform=restaurant.platform):
                logger.info("snipe_starting", target_date=target_date)

                # Clear cached platform for fresh browser context
                self._platforms.pop(restaurant.platform, None)

                platform = await self._get_platform(restaurant.platform)
                if not platform:
                    logger.warning("snipe_no_platform_credentials")
                    return

                try:
                    if not await platform.ensure_logged_in():
                        logger.error("snipe_login_failed")
                        return
                except AuthenticationError as e:
                    logger.error("snipe_auth_error", error=str(e))
                    return

                poller = RapidPoller(
                    interval_ms=self.config.scheduler.snipe_rapid_poll_interval * 1000,
                    duration_seconds=self.config.scheduler.snipe_duration,
                )

                success = await poller.poll(
                    self._snipe_attempt,
                    platform=platform,
                    restaurant=restaurant,
                    target_date=target_date,
                )

                if not success:
                    logger.warning("snipe_timeout", target_date=target_date)
        except Exception as e:
            logger.error("snipe_error", error=str(e), restaurant=restaurant.name)
        finally:
            self._active_snipe_restaurants.discard(restaurant.name)
            self._scheduled_snipes.discard(snipe_id)

    async def _snipe_attempt(
        self,
        platform: BasePlatform,
        restaurant: RestaurantConfig,
        target_date: str,
    ) -> bool:
        """Single snipe attempt: check availability and try to book."""
        start_time = datetime.now()

        if isinstance(platform, OpenTablePlatform):
            return await self._opentable_snipe_attempt(
                platform, restaurant, target_date, start_time,
            )

        try:
            result = await platform.check_availability(
                restaurant, target_date, restaurant.party_size
            )
        except Exception as e:
            logger.warning("snipe_check_error", error=str(e))
            return False

        if not result.available_slots:
            return False

        matching_slots = platform.filter_preferred_slots(
            result.available_slots, restaurant.preferred_times
        )
        if not matching_slots:
            return False

        slot = matching_slots[0]
        try:
            book_result = await platform.book_slot(
                restaurant, slot, restaurant.party_size,
                dry_run=self.config.dry_run, date=target_date,
            )
            if book_result.success:
                logger.info(
                    "snipe_booking_successful",
                    restaurant=restaurant.name,
                    date=target_date,
                    time=book_result.booked_time,
                    confirmation=book_result.confirmation_number,
                )
                restaurant.enabled = False
                return True
        except SlotUnavailableError:
            pass
        except Exception as e:
            logger.warning("snipe_book_error", slot_time=slot.time, error=str(e))

        return False

    async def _opentable_poll_attempt(
        self,
        platform: OpenTablePlatform,
        restaurant: RestaurantConfig,
        target_date: str,
        start_time: datetime,
    ) -> bool:
        """Single-page OpenTable poll: check + book on one Firefox page."""
        try:
            book_result, slot = await platform.check_and_book(
                restaurant=restaurant,
                date=target_date,
                party_size=restaurant.party_size,
                preferred_times=restaurant.preferred_times,
                dry_run=self.config.dry_run,
            )
        except SlotUnavailableError:
            return False
        except Exception as e:
            logger.error("opentable_poll_error", error=str(e), date=target_date)
            return False

        if book_result is None:
            logger.info("no_availability", date=target_date)
            return False

        if book_result.success:
            logger.info(
                "booking_successful",
                restaurant=restaurant.name,
                date=target_date,
                time=book_result.booked_time,
                confirmation=book_result.confirmation_number,
            )
            restaurant.enabled = False
            return True

        logger.warning("booking_failed", error=book_result.error_message)
        return False

    async def _opentable_snipe_attempt(
        self,
        platform: OpenTablePlatform,
        restaurant: RestaurantConfig,
        target_date: str,
        start_time: datetime,
    ) -> bool:
        """Single-page OpenTable snipe: check + book on one Firefox page."""
        try:
            book_result, slot = await platform.check_and_book(
                restaurant=restaurant,
                date=target_date,
                party_size=restaurant.party_size,
                preferred_times=restaurant.preferred_times,
                dry_run=self.config.dry_run,
            )
        except SlotUnavailableError:
            return False
        except Exception as e:
            logger.warning("opentable_snipe_error", error=str(e))
            return False

        if book_result is None:
            return False

        if book_result.success:
            logger.info(
                "snipe_booking_successful",
                restaurant=restaurant.name,
                date=target_date,
                time=book_result.booked_time,
                confirmation=book_result.confirmation_number,
            )
            restaurant.enabled = False
            return True

        return False

    @staticmethod
    def _is_date_unreleased(target_date: str, restaurant: RestaurantConfig) -> bool:
        """Return True if the restaurant hasn't released slots for target_date yet."""
        days_ahead = restaurant.release_days_ahead
        if not days_ahead:
            return False

        parts = restaurant.release_time.split(":")
        rh, rm = int(parts[0]), int(parts[1])

        et = ZoneInfo("America/New_York")
        now = datetime.now(tz=et)

        target = datetime.strptime(target_date, "%Y-%m-%d").replace(tzinfo=et)
        release_date = target - timedelta(days=days_ahead)
        release_dt = release_date.replace(hour=rh, minute=rm, second=0, microsecond=0)

        return now < release_dt

    async def _get_platform(self, platform_name: str) -> BasePlatform | None:
        """Get or create a platform instance."""
        if platform_name in self._platforms:
            return self._platforms[platform_name]

        platform_class = self.PLATFORM_CLASSES.get(platform_name)
        if not platform_class:
            logger.error("unknown_platform", platform=platform_name)
            return None

        credential = self.config.get_credential(platform_name)
        if not credential:
            logger.error("no_credentials", platform=platform_name)
            return None

        credentials = {
            "platform": platform_name,
            "username": credential.username,
            "password": credential.password,
        }

        platform = platform_class(self.session_manager, credentials)
        self._platforms[platform_name] = platform
        logger.info("created_platform_instance", platform=platform_name)
        return platform
