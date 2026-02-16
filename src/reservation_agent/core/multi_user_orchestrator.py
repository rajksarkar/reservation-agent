"""Multi-user orchestrator for web worker mode.

Polls Supabase for active reservation requests from all users,
processes them using the existing platform classes with per-user
browser contexts and credentials.
"""

import asyncio
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from reservation_agent.browser.session_manager import SessionManager
from reservation_agent.core.config import AgentConfig, RestaurantConfig
from reservation_agent.core.exceptions import (
    AuthenticationError,
    SlotUnavailableError,
)
from reservation_agent.db.supabase_client import SupabaseRepository
from reservation_agent.platforms.base import BasePlatform, TimeSlot
from reservation_agent.platforms.opentable import OpenTablePlatform
from reservation_agent.platforms.resy import ResyPlatform
from reservation_agent.platforms.tock import TockPlatform
from reservation_agent.utils.logging import get_logger, LogContext

logger = get_logger(__name__)

POLL_INTERVAL = 30  # seconds


class MultiUserOrchestrator:
    """Processes reservation requests from multiple users via Supabase."""

    PLATFORM_CLASSES = {
        "resy": ResyPlatform,
        "opentable": OpenTablePlatform,
        "tock": TockPlatform,
    }

    def __init__(self, config: AgentConfig, base_dir: Path | None = None):
        self.config = config
        self.base_dir = base_dir or Path.cwd()
        self.repo = SupabaseRepository()

        # Per-user platform instances keyed by (user_id, platform)
        self._platforms: dict[tuple[str, str], BasePlatform] = {}
        # Shared session manager
        self.session_manager: SessionManager | None = None
        self._running = False

    async def start(self) -> None:
        """Initialize browser session manager."""
        logger.info("starting_multi_user_orchestrator")
        self.session_manager = SessionManager(self.config.browser, self.base_dir)
        await self.session_manager.start()
        self._running = True
        logger.info("multi_user_orchestrator_started")

    async def stop(self) -> None:
        """Shut down gracefully."""
        logger.info("stopping_multi_user_orchestrator")
        self._running = False
        if self.session_manager:
            await self.session_manager.stop()
        logger.info("multi_user_orchestrator_stopped")

    async def run_forever(self) -> None:
        """Main polling loop: fetch active requests, process each."""
        while self._running:
            try:
                await self._poll_and_process()
            except Exception as e:
                logger.error("poll_error", error=str(e))
            await asyncio.sleep(POLL_INTERVAL)

    async def _poll_and_process(self) -> None:
        """Fetch active requests from Supabase and process them."""
        requests = self.repo.get_active_requests()
        if not requests:
            return

        logger.info("processing_requests", count=len(requests))

        # Process requests concurrently (limited concurrency)
        sem = asyncio.Semaphore(3)

        async def process_with_sem(req: dict) -> None:
            async with sem:
                await self._process_request(req)

        await asyncio.gather(
            *[process_with_sem(r) for r in requests],
            return_exceptions=True,
        )

    async def _process_request(self, request: dict) -> None:
        """Process a single reservation request."""
        request_id = request["id"]
        user_id = request["user_id"]
        restaurant = request.get("restaurants", {})
        platform_name = restaurant.get("platform", "")

        with LogContext(
            request_id=request_id,
            user_id=user_id[:8],
            restaurant=restaurant.get("name", "unknown"),
        ):
            # Get or create platform instance for this user
            platform = await self._get_platform(user_id, platform_name)
            if not platform:
                logger.warning("no_platform_credentials")
                return

            # Ensure logged in
            try:
                if not await platform.ensure_logged_in():
                    logger.error("login_failed")
                    self.repo.log_attempt(
                        request_id=request_id,
                        attempt_type="cancellation_check",
                        result="auth_failed",
                        error_message="Login failed",
                    )
                    return
            except AuthenticationError as e:
                logger.error("auth_error", error=str(e))
                self.repo.log_attempt(
                    request_id=request_id,
                    attempt_type="cancellation_check",
                    result="auth_failed",
                    error_message=str(e),
                )
                return

            # Build a RestaurantConfig-like object for the platform
            venue_id = restaurant.get("venue_id", "")
            restaurant_config = RestaurantConfig(
                name=restaurant.get("name", ""),
                platform=platform_name,
                venue_id=venue_id,
                party_size=request.get("party_size", 2),
                target_dates=request.get("target_dates", []),
                preferred_times=request.get("preferred_times", []),
                release_time=request.get("release_time", "09:00"),
                release_days_ahead=request.get("release_days_ahead", 14),
                monitor_cancellations=request.get("monitor_cancellations", True),
            )

            # Check each target date
            for target_date in request.get("target_dates", []):
                start_time = datetime.now()
                try:
                    result = await platform.check_availability(
                        restaurant_config, target_date, request["party_size"]
                    )
                except Exception as e:
                    duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
                    logger.error("availability_check_error", error=str(e), date=target_date)
                    self.repo.log_attempt(
                        request_id=request_id,
                        attempt_type="cancellation_check",
                        result="error",
                        error_message=str(e),
                        duration_ms=duration_ms,
                    )
                    continue

                if not result.available_slots:
                    duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
                    self.repo.log_attempt(
                        request_id=request_id,
                        attempt_type="cancellation_check",
                        result="no_availability",
                        duration_ms=duration_ms,
                    )
                    continue

                # Filter to preferred times
                preferred_times = request.get("preferred_times", [])
                matching_slots = platform.filter_preferred_slots(
                    result.available_slots, preferred_times
                )

                if not matching_slots:
                    duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
                    self.repo.log_attempt(
                        request_id=request_id,
                        attempt_type="cancellation_check",
                        result="no_availability",
                        duration_ms=duration_ms,
                    )
                    continue

                # Try to book
                booked = await self._try_book(
                    request_id, user_id, platform, restaurant_config,
                    matching_slots, request["party_size"], target_date, start_time,
                )
                if booked:
                    return  # Done with this request

    async def _try_book(
        self,
        request_id: str,
        user_id: str,
        platform: BasePlatform,
        restaurant_config: RestaurantConfig,
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
                    restaurant_config, slot, party_size, dry_run=self.config.dry_run
                )

                duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

                if book_result.success:
                    self.repo.update_request_status(
                        request_id=request_id,
                        status="booked",
                        booked_date=target_date,
                        booked_time=book_result.booked_time,
                        confirmation_number=book_result.confirmation_number,
                    )
                    self.repo.log_attempt(
                        request_id=request_id,
                        attempt_type="cancellation_check",
                        result="success",
                        slot_time=slot.time,
                        duration_ms=duration_ms,
                    )
                    self.repo.log_activity(
                        user_id=user_id,
                        event_type="booking_success",
                        title=f"Booked {restaurant_config.name}!",
                        description=f"{target_date} at {book_result.booked_time}",
                        request_id=request_id,
                    )
                    logger.info("booking_successful", confirmation=book_result.confirmation_number)
                    return True
                else:
                    self.repo.log_attempt(
                        request_id=request_id,
                        attempt_type="cancellation_check",
                        result="slot_taken",
                        slot_time=slot.time,
                        error_message=book_result.error_message,
                        duration_ms=duration_ms,
                    )
            except SlotUnavailableError:
                logger.warning("slot_unavailable", slot_time=slot.time)
                continue
            except Exception as e:
                duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
                logger.error("booking_error", slot_time=slot.time, error=str(e))
                self.repo.log_attempt(
                    request_id=request_id,
                    attempt_type="cancellation_check",
                    result="error",
                    slot_time=slot.time,
                    error_message=str(e),
                    duration_ms=duration_ms,
                )
                continue

        return False

    async def _get_platform(self, user_id: str, platform_name: str) -> BasePlatform | None:
        """Get or create a platform instance for a user."""
        cache_key = (user_id, platform_name)
        if cache_key in self._platforms:
            return self._platforms[cache_key]

        platform_class = self.PLATFORM_CLASSES.get(platform_name)
        if not platform_class:
            logger.error("unknown_platform", platform=platform_name)
            return None

        # Fetch and decrypt credentials
        account = self.repo.get_user_platform_account(user_id, platform_name)
        if not account:
            return None

        # If Supabase has a stored browser session, write it to the session file
        # so SessionManager picks it up via has_recent_session() / _create_context()
        if account.get("session_data") and self.session_manager:
            session_file = self.session_manager.sessions_dir / f"{platform_name}_session.json"
            session_file.write_text(json.dumps(account["session_data"], indent=2))
            logger.info("injected_session_from_supabase", platform=platform_name, user=user_id[:8])

        try:
            username, password = self.repo.decrypt_credentials(account, user_id)
        except Exception as e:
            # If decryption fails but we have a session, proceed without credentials
            if account.get("session_data"):
                logger.warning("credential_decryption_failed_using_session", error=str(e))
                username, password = None, None
            else:
                logger.error("credential_decryption_failed", error=str(e))
                return None

        credentials = None
        if username and password:
            credentials = {
                "platform": platform_name,
                "username": username,
                "password": password,
            }

        # Create platform with a browser context scoped to this user
        platform = platform_class(self.session_manager, credentials)
        self._platforms[cache_key] = platform
        logger.info("created_platform_instance", platform=platform_name, user=user_id[:8])
        return platform
