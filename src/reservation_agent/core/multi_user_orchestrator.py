"""Multi-user orchestrator for web worker mode.

Polls Supabase for active reservation requests from all users,
processes them using the existing platform classes with per-user
browser contexts and credentials.
"""

import asyncio
import json
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
from reservation_agent.db.supabase_client import SupabaseRepository
from reservation_agent.platforms.base import BasePlatform, TimeSlot
from reservation_agent.platforms.opentable import OpenTablePlatform
from reservation_agent.platforms.resy import ResyPlatform
from reservation_agent.platforms.tock import TockPlatform
from reservation_agent.utils.logging import get_logger, LogContext

logger = get_logger(__name__)

POLL_INTERVAL = 30  # seconds

# Backoff constants for repeated platform failures
_MAX_NAV_FAILURES = 5     # consecutive nav timeouts before cooldown
_COOLDOWN_MINUTES = 10    # minutes to pause a request after repeated failures
_BROWSER_CRASH_MSGS = (
    "Target page, context or browser has been closed",
    "Browser has been closed",
    "context has been closed",
)


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

        # Snipe scheduling state
        self._scheduled_snipes: set[str] = set()  # "requestId_targetDate" keys already scheduled
        self._active_snipe_requests: set[str] = set()  # request IDs currently being sniped

        # Per-request failure tracking for backoff
        self._nav_failure_counts: dict[str, int] = {}   # request_id → consecutive nav timeouts
        self._cooldown_until: dict[str, datetime] = {}  # request_id → resume datetime

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

        # Schedule snipes for release_snipe requests
        for req in requests:
            if req.get("release_snipe"):
                self._schedule_snipes(req)

        # Filter to requests that should be cancellation-polled:
        # - Skip requests currently being sniped
        # - Skip snipe-only requests (release_snipe=True but monitor_cancellations=False)
        cancellation_requests = [
            r for r in requests
            if r["id"] not in self._active_snipe_requests
            and (r.get("monitor_cancellations", True) or not r.get("release_snipe"))
        ]

        if not cancellation_requests:
            return

        # Process requests concurrently (limited concurrency)
        sem = asyncio.Semaphore(3)

        async def process_with_sem(req: dict) -> None:
            async with sem:
                await self._process_request(req)

        await asyncio.gather(
            *[process_with_sem(r) for r in cancellation_requests],
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
            # Skip requests that are cooling down after repeated failures
            now_dt = datetime.now()
            if request_id in self._cooldown_until:
                if now_dt < self._cooldown_until[request_id]:
                    remaining = int(
                        (self._cooldown_until[request_id] - now_dt).total_seconds() // 60
                    )
                    logger.info("request_in_cooldown", remaining_minutes=remaining)
                    return
                else:
                    del self._cooldown_until[request_id]
                    self._nav_failure_counts.pop(request_id, None)
                    logger.info("cooldown_expired_resuming")

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
                # Skip dates whose slots haven't been released yet — the
                # snipe scheduler will handle those.  Only poll for
                # cancellations on dates that are already released.
                if self._is_date_unreleased(target_date, restaurant):
                    continue

                start_time = datetime.now()

                # OpenTable: single-page check+book avoids Firefox crash
                if isinstance(platform, OpenTablePlatform):
                    booked = await self._opentable_poll_attempt(
                        request_id, user_id, platform, restaurant_config,
                        target_date, start_time,
                    )
                    if booked:
                        return
                    continue

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
                    restaurant_config, slot, party_size,
                    dry_run=self.config.dry_run, date=target_date,
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

    def _schedule_snipes(self, request: dict) -> None:
        """Schedule snipe tasks for upcoming release windows."""
        request_id = request["id"]
        restaurant = request.get("restaurants", {})
        restaurant_name = restaurant.get("name", "unknown")

        release_time = (
            request.get("release_time")
            or restaurant.get("release_time")
            or "09:00"
        )
        release_days_ahead = (
            request.get("release_days_ahead")
            or restaurant.get("release_days_ahead")
            or 14
        )

        et = ZoneInfo("America/New_York")
        now = datetime.now(tz=et)
        wake_before = self.config.scheduler.snipe_wake_before
        snipe_duration = self.config.scheduler.snipe_duration

        time_parts = release_time.split(":")
        release_hour, release_minute = int(time_parts[0]), int(time_parts[1])

        for target_date in request.get("target_dates", []):
            snipe_id = f"{request_id}_{target_date}"
            if snipe_id in self._scheduled_snipes:
                continue

            target = datetime.strptime(target_date, "%Y-%m-%d").replace(tzinfo=et)
            release_date = target - timedelta(days=release_days_ahead)
            release_dt = release_date.replace(
                hour=release_hour, minute=release_minute, second=0, microsecond=0
            )
            wake_dt = release_dt - timedelta(seconds=wake_before)
            end_dt = release_dt + timedelta(seconds=snipe_duration)

            if now > end_dt:
                # Window already passed
                continue

            # Only schedule if wake time is within the next 2 hours
            if wake_dt > now + timedelta(hours=2):
                continue

            self._scheduled_snipes.add(snipe_id)

            logger.info(
                "snipe_scheduled",
                request_id=request_id,
                restaurant=restaurant_name,
                target_date=target_date,
                release_dt=release_dt.isoformat(),
                wake_dt=wake_dt.isoformat(),
            )

            asyncio.create_task(
                self._execute_snipe(snipe_id, request, target_date, wake_dt)
            )

    async def _execute_snipe(
        self, snipe_id: str, request: dict, target_date: str, wake_dt: datetime
    ) -> None:
        """Execute a snipe: sleep until wake time, then rapid-poll for slots."""
        request_id = request["id"]
        user_id = request["user_id"]
        restaurant = request.get("restaurants", {})
        platform_name = restaurant.get("platform", "")

        try:
            self._active_snipe_requests.add(request_id)

            # Sleep until wake time
            et = ZoneInfo("America/New_York")
            now = datetime.now(tz=et)
            if wake_dt > now:
                sleep_seconds = (wake_dt - now).total_seconds()
                logger.info(
                    "snipe_sleeping",
                    request_id=request_id,
                    sleep_seconds=int(sleep_seconds),
                )
                await asyncio.sleep(sleep_seconds)

            with LogContext(
                request_id=request_id,
                user_id=user_id[:8],
                restaurant=restaurant.get("name", "unknown"),
            ):
                logger.info("snipe_starting", target_date=target_date)

                # Clear cached platform to get a fresh browser context
                cache_key = (user_id, platform_name)
                self._platforms.pop(cache_key, None)

                platform = await self._get_platform(user_id, platform_name)
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

                restaurant_config = RestaurantConfig(
                    name=restaurant.get("name", ""),
                    platform=platform_name,
                    venue_id=restaurant.get("venue_id", ""),
                    party_size=request.get("party_size", 2),
                    target_dates=request.get("target_dates", []),
                    preferred_times=request.get("preferred_times", []),
                    release_time=request.get("release_time", "09:00"),
                    release_days_ahead=request.get("release_days_ahead", 14),
                    monitor_cancellations=request.get("monitor_cancellations", True),
                )

                poller = RapidPoller(
                    interval_ms=self.config.scheduler.snipe_rapid_poll_interval * 1000,
                    duration_seconds=self.config.scheduler.snipe_duration,
                )

                success = await poller.poll(
                    self._snipe_attempt,
                    request_id=request_id,
                    user_id=user_id,
                    platform=platform,
                    restaurant_config=restaurant_config,
                    target_date=target_date,
                )

                if not success:
                    logger.warning("snipe_timeout", target_date=target_date)
                    self.repo.log_attempt(
                        request_id=request_id,
                        attempt_type="snipe",
                        result="no_availability",
                    )
        except Exception as e:
            logger.error("snipe_error", error=str(e), request_id=request_id)
        finally:
            self._active_snipe_requests.discard(request_id)
            self._scheduled_snipes.discard(snipe_id)

    async def _snipe_attempt(
        self,
        request_id: str,
        user_id: str,
        platform: BasePlatform,
        restaurant_config: RestaurantConfig,
        target_date: str,
    ) -> bool:
        """Single snipe attempt: check availability and try to book. Returns True on success."""
        start_time = datetime.now()

        # OpenTable: use single-page check_and_book to avoid Firefox crash on
        # second page navigation.
        if isinstance(platform, OpenTablePlatform):
            return await self._opentable_snipe_attempt(
                request_id, user_id, platform, restaurant_config, target_date, start_time,
            )

        # All other platforms: two-step check then book
        try:
            result = await platform.check_availability(
                restaurant_config, target_date, restaurant_config.party_size
            )
        except Exception as e:
            logger.warning("snipe_check_error", error=str(e))
            return False

        if not result.available_slots:
            return False

        matching_slots = platform.filter_preferred_slots(
            result.available_slots, restaurant_config.preferred_times
        )
        if not matching_slots:
            return False

        # Only try the best matching slot per attempt (let rapid poller retry)
        slot = matching_slots[0]
        try:
            book_result = await platform.book_slot(
                restaurant_config, slot, restaurant_config.party_size,
                dry_run=self.config.dry_run,
                date=target_date,
            )
            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

            if book_result.success:
                self._record_snipe_success(
                    request_id, user_id, restaurant_config.name,
                    target_date, book_result, slot, duration_ms,
                )
                return True
        except SlotUnavailableError:
            pass
        except Exception as e:
            logger.warning("snipe_book_error", slot_time=slot.time, error=str(e))

        return False

    async def _opentable_poll_attempt(
        self,
        request_id: str,
        user_id: str,
        platform: OpenTablePlatform,
        restaurant_config: RestaurantConfig,
        target_date: str,
        start_time: datetime,
    ) -> bool:
        """Single-page OpenTable poll: check + book on one Firefox page (cancellation monitor)."""
        try:
            book_result, slot = await platform.check_and_book(
                restaurant=restaurant_config,
                date=target_date,
                party_size=restaurant_config.party_size,
                preferred_times=restaurant_config.preferred_times,
                dry_run=self.config.dry_run,
            )
        except SlotUnavailableError:
            return False
        except Exception as e:
            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            logger.error("opentable_poll_error", error=str(e), date=target_date)
            self.repo.log_attempt(
                request_id=request_id,
                attempt_type="cancellation_check",
                result="error",
                error_message=str(e),
                duration_ms=duration_ms,
            )
            return False

        if book_result is None:
            # Successful check, just no slots — reset failure streak
            self._nav_failure_counts.pop(request_id, None)
            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            self.repo.log_attempt(
                request_id=request_id,
                attempt_type="cancellation_check",
                result="no_availability",
                duration_ms=duration_ms,
            )
            return False

        duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

        if book_result.success:
            # Successful booking — reset failure streak
            self._nav_failure_counts.pop(request_id, None)
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
                slot_time=slot.time if slot else None,
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

        # check_and_book returned a failure — classify the error
        error_msg = book_result.error_message or ""
        is_browser_crash = any(s in error_msg for s in _BROWSER_CRASH_MSGS)
        is_nav_timeout = "Timeout" in error_msg

        if is_browser_crash:
            # Context died mid-operation — reset it so the next poll gets a fresh one
            logger.warning("browser_crash_resetting_context", date=target_date)
            if self.session_manager:
                await self.session_manager.reset_context("opentable")
            result_label = "error"
        elif is_nav_timeout:
            # Navigation timeout — likely rate-limited; count toward cooldown
            count = self._nav_failure_counts.get(request_id, 0) + 1
            self._nav_failure_counts[request_id] = count
            logger.warning(
                "nav_timeout_failure",
                count=count,
                max=_MAX_NAV_FAILURES,
                date=target_date,
            )
            if count >= _MAX_NAV_FAILURES:
                cooldown_until = datetime.now() + timedelta(minutes=_COOLDOWN_MINUTES)
                self._cooldown_until[request_id] = cooldown_until
                self._nav_failure_counts.pop(request_id, None)
                logger.warning(
                    "request_entering_cooldown",
                    cooldown_minutes=_COOLDOWN_MINUTES,
                    cooldown_until=cooldown_until.isoformat(),
                )
            result_label = "error"
        else:
            # Slot taken or other transient booking failure — reset streak
            self._nav_failure_counts.pop(request_id, None)
            result_label = "slot_taken"

        self.repo.log_attempt(
            request_id=request_id,
            attempt_type="cancellation_check",
            result=result_label,
            slot_time=slot.time if slot else None,
            error_message=book_result.error_message,
            duration_ms=duration_ms,
        )
        return False

    async def _opentable_snipe_attempt(
        self,
        request_id: str,
        user_id: str,
        platform: OpenTablePlatform,
        restaurant_config: RestaurantConfig,
        target_date: str,
        start_time: datetime,
    ) -> bool:
        """Single-page OpenTable snipe: check + book on one Firefox page."""
        try:
            book_result, slot = await platform.check_and_book(
                restaurant=restaurant_config,
                date=target_date,
                party_size=restaurant_config.party_size,
                preferred_times=restaurant_config.preferred_times,
                dry_run=self.config.dry_run,
            )
        except SlotUnavailableError:
            return False
        except Exception as e:
            logger.warning("opentable_snipe_error", error=str(e))
            return False

        if book_result is None:
            return False

        duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

        if book_result.success:
            self._record_snipe_success(
                request_id, user_id, restaurant_config.name,
                target_date, book_result, slot, duration_ms,
            )
            return True

        return False

    def _record_snipe_success(
        self,
        request_id: str,
        user_id: str,
        restaurant_name: str,
        target_date: str,
        book_result: Any,
        slot: Any,
        duration_ms: int,
    ) -> None:
        """Persist a successful snipe booking to the database."""
        self.repo.update_request_status(
            request_id=request_id,
            status="booked",
            booked_date=target_date,
            booked_time=book_result.booked_time,
            confirmation_number=book_result.confirmation_number,
        )
        self.repo.log_attempt(
            request_id=request_id,
            attempt_type="snipe",
            result="success",
            slot_time=slot.time if slot else None,
            duration_ms=duration_ms,
        )
        self.repo.log_activity(
            user_id=user_id,
            event_type="booking_success",
            title=f"Sniped {restaurant_name}!",
            description=f"{target_date} at {book_result.booked_time}",
            request_id=request_id,
        )
        logger.info(
            "snipe_booking_successful",
            confirmation=book_result.confirmation_number,
        )

    @staticmethod
    def _is_date_unreleased(target_date: str, restaurant: dict) -> bool:
        """Return True if the restaurant hasn't released slots for target_date yet.

        Uses the restaurant's release_days_ahead and release_time to compute
        when slots for target_date become available.  If that moment is still
        in the future, the date is unreleased and should not be polled for
        cancellations (a snipe will handle it instead).
        """
        days_ahead = restaurant.get("release_days_ahead")
        if not days_ahead:
            return False  # no schedule info → assume released

        release_time_str = restaurant.get("release_time") or "09:00"
        # release_time may be "HH:MM" or "HH:MM:SS"
        parts = release_time_str.split(":")
        rh, rm = int(parts[0]), int(parts[1])

        et = ZoneInfo("America/New_York")
        now = datetime.now(tz=et)

        target = datetime.strptime(target_date, "%Y-%m-%d").replace(tzinfo=et)
        release_date = target - timedelta(days=days_ahead)
        release_dt = release_date.replace(
            hour=rh, minute=rm, second=0, microsecond=0
        )

        return now < release_dt

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
