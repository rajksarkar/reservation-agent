"""OpenTable platform implementation."""

import asyncio
import re
from datetime import datetime

from playwright.async_api import Page

from reservation_agent.browser.session_manager import PageHelper
from reservation_agent.browser.stealth import RequestInterceptor, StealthBrowser
from reservation_agent.core.config import PlatformCredential, RestaurantConfig
from reservation_agent.core.exceptions import (
    AuthenticationError,
    BookingError,
    SlotUnavailableError,
)
from reservation_agent.platforms.base import (
    AvailabilityResult,
    BasePlatform,
    BookingResult,
    TimeSlot,
)


class OpenTablePlatform(BasePlatform):
    """OpenTable reservation platform integration."""

    PLATFORM_NAME = "opentable"
    BASE_URL = "https://www.opentable.com"

    # Selectors
    SELECTORS = {
        "sign_in_link": '[data-test="user-menu-trigger"]',
        "email_input": 'input[name="email"]',
        "password_input": 'input[name="password"]',
        "submit_login": 'button[type="submit"]',
        "logged_in_avatar": '[data-test="user-menu-avatar"]',
        "time_slots": '[data-test="time-slot"]',
        "time_button": 'button[data-time]',
        "complete_reservation": '[data-test="complete-reservation-button"]',
        "confirmation_number": '[data-test="confirmation-number"]',
        "party_size_select": '[data-test="party-size-select"]',
        "date_picker": '[data-test="date-picker"]',
    }

    async def check_session_valid(self) -> bool:
        """Check if we're logged in to OpenTable."""
        # Trust recent session from manual_auth
        if self.session_manager.has_recent_session(self.PLATFORM_NAME, max_age_hours=168):
            self.logger.info("using_recent_saved_session")
            return True

        try:
            page = await self.get_page()
            await page.goto(self.BASE_URL, wait_until="domcontentloaded")
            await asyncio.sleep(3)  # SPA hydration

            # Look for logged-in avatar
            avatar = await page.query_selector(self.SELECTORS["logged_in_avatar"])
            return avatar is not None
        except Exception as e:
            self.logger.warning("session_check_failed", error=str(e))
            return False

    async def login(self) -> bool:
        """Log in to OpenTable using email/password."""
        if not self.credentials:
            raise AuthenticationError(self.PLATFORM_NAME, "No credentials provided")

        try:
            page = await self.get_page()
            helper = PageHelper(page)

            self.logger.info("navigating_to_login")
            await page.goto(f"{self.BASE_URL}/login", wait_until="domcontentloaded")

            # Enter email
            await StealthBrowser.human_type(
                page, self.SELECTORS["email_input"], self.credentials.username
            )
            await StealthBrowser.random_idle(0.5, 1.0)

            # Enter password
            await StealthBrowser.human_type(
                page, self.SELECTORS["password_input"], self.credentials.password
            )
            await StealthBrowser.random_idle(0.3, 0.8)

            # Submit
            await helper.wait_and_click(self.SELECTORS["submit_login"])

            # Wait for login to complete
            try:
                await page.wait_for_selector(
                    self.SELECTORS["logged_in_avatar"], timeout=15000
                )
                self.logger.info("login_successful")
                await self.save_session()
                return True
            except Exception:
                # Check for error message
                error = await page.query_selector('[data-test="auth-error"]')
                if error:
                    error_text = await error.text_content()
                    self.logger.error("login_failed", error=error_text)
                return False

        except Exception as e:
            self.logger.error("login_error", error=str(e))
            raise AuthenticationError(self.PLATFORM_NAME, str(e))

    async def check_availability(
        self,
        restaurant: RestaurantConfig,
        date: str,
        party_size: int,
    ) -> AvailabilityResult:
        """Check availability on OpenTable for a specific date."""
        page = await self.get_page()

        # Set up API response interception
        interceptor = RequestInterceptor(page)
        await interceptor.start(["/availability"])

        # Build URL - Firefox handles OpenTable; Chromium is often blocked
        url = f"{self.BASE_URL}/r/{restaurant.venue_id}?covers={party_size}&dateTime={date}%2019%3A00"
        self.logger.info("checking_availability", url=url, date=date)

        await page.goto(url, wait_until="domcontentloaded", timeout=60000)
        await asyncio.sleep(4)  # Let slots populate

        # Try to get slots from API response
        slots = []
        api_responses = interceptor.get_captured("/availability")

        if api_responses:
            for resp in api_responses:
                slots.extend(self._parse_api_availability(resp.get("body", {})))
        else:
            # Fallback: parse from DOM
            slots = await self._parse_dom_availability(page)

        self.logger.info("found_slots", count=len(slots), date=date)

        return AvailabilityResult(
            available_slots=slots,
            date=date,
            party_size=party_size,
            checked_at=datetime.now(),
        )

    def _parse_api_availability(self, response: dict) -> list[TimeSlot]:
        """Parse availability from OpenTable API response."""
        slots = []
        try:
            # OpenTable API structure
            time_slots = response.get("availability", {}).get("times", [])
            for slot_data in time_slots:
                time_str = slot_data.get("time", "")
                if time_str:
                    # Convert from "7:00 PM" format to "19:00"
                    time_24h = self._convert_to_24h(time_str)
                    if time_24h:
                        slots.append(
                            TimeSlot(
                                time=time_24h,
                                slot_id=slot_data.get("slotHash", time_str),
                                slot_type=slot_data.get("tableType", ""),
                                raw_data=slot_data,
                            )
                        )
        except Exception as e:
            self.logger.warning("api_parse_error", error=str(e))
        return slots

    def _convert_to_24h(self, time_str: str) -> str | None:
        """Convert 12-hour time to 24-hour format."""
        match = re.search(r"(\d{1,2}):(\d{2})\s*(AM|PM)", time_str, re.IGNORECASE)
        if match:
            hour = int(match.group(1))
            minute = match.group(2)
            period = match.group(3).upper()

            if period == "PM" and hour != 12:
                hour += 12
            elif period == "AM" and hour == 12:
                hour = 0

            return f"{hour:02d}:{minute}"
        return None

    async def _parse_dom_availability(self, page: Page) -> list[TimeSlot]:
        """Parse availability from page DOM."""
        slots = []
        try:
            # Try different possible selectors
            selectors = [
                self.SELECTORS["time_slots"],
                self.SELECTORS["time_button"],
                'button[class*="time"]',
                '[data-test*="slot"]',
            ]

            for selector in selectors:
                elements = await page.query_selector_all(selector)
                if elements:
                    for elem in elements:
                        time_text = await elem.text_content()
                        data_time = await elem.get_attribute("data-time")

                        if data_time:
                            time_24h = self._convert_to_24h(data_time)
                        elif time_text:
                            time_24h = self._convert_to_24h(time_text.strip())
                        else:
                            continue

                        if time_24h:
                            slots.append(
                                TimeSlot(
                                    time=time_24h,
                                    slot_id=data_time or time_24h,
                                    slot_type=None,
                                )
                            )
                    break  # Found slots, stop trying selectors

        except Exception as e:
            self.logger.warning("dom_parse_error", error=str(e))
        return slots

    async def book_slot(
        self,
        restaurant: RestaurantConfig,
        slot: TimeSlot,
        party_size: int,
        dry_run: bool = False,
    ) -> BookingResult:
        """Book a specific slot on OpenTable."""
        page = await self.get_page()
        helper = PageHelper(page)

        try:
            self.logger.info(
                "booking_slot",
                restaurant=restaurant.name,
                time=slot.time,
                party_size=party_size,
                dry_run=dry_run,
            )

            # Click on the time slot
            # Try multiple strategies to find the slot
            clicked = False

            # Strategy 1: by data-time attribute
            slot_selector = f'button[data-time="{slot.time}"]'
            if await page.query_selector(slot_selector):
                await helper.wait_and_click(slot_selector)
                clicked = True

            # Strategy 2: by slot ID
            if not clicked and slot.slot_id:
                slot_selector = f'button[data-slot-hash="{slot.slot_id}"]'
                if await page.query_selector(slot_selector):
                    await helper.wait_and_click(slot_selector)
                    clicked = True

            # Strategy 3: search all time buttons
            if not clicked:
                buttons = await page.query_selector_all('[data-test="time-slot"], button[data-time]')
                for btn in buttons:
                    btn_time = await btn.get_attribute("data-time")
                    btn_text = await btn.text_content()
                    if btn_time == slot.time or (btn_text and slot.time in btn_text):
                        await btn.click()
                        clicked = True
                        break

            if not clicked:
                raise SlotUnavailableError(self.PLATFORM_NAME, f"Slot {slot.time} not found")

            await asyncio.sleep(2)

            if dry_run:
                self.logger.info("dry_run_stopping_before_confirm")
                return BookingResult(
                    success=False,
                    booked_time=slot.time,
                    error_message="Dry run - stopped before confirmation",
                )

            # Click complete reservation button
            await helper.wait_and_click(self.SELECTORS["complete_reservation"], timeout=10000)
            await asyncio.sleep(3)

            # Check for confirmation
            confirmation_elem = await page.query_selector(
                self.SELECTORS["confirmation_number"]
            )
            confirmation_number = None
            if confirmation_elem:
                confirmation_number = await confirmation_elem.text_content()

            # Verify success by URL or confirmation element
            if "confirmation" in page.url.lower() or confirmation_number:
                self.logger.info(
                    "booking_successful",
                    confirmation=confirmation_number,
                    time=slot.time,
                )
                return BookingResult(
                    success=True,
                    confirmation_number=confirmation_number,
                    booked_time=slot.time,
                )
            else:
                return BookingResult(
                    success=False,
                    error_message="Could not confirm booking success",
                    booked_time=slot.time,
                )

        except SlotUnavailableError:
            raise
        except Exception as e:
            self.logger.error("booking_failed", error=str(e))
            return BookingResult(
                success=False,
                error_message=str(e),
                booked_time=slot.time,
            )
