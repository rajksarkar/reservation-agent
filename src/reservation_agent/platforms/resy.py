"""Resy platform implementation."""

import asyncio
import json
import re
from datetime import datetime
from urllib.parse import quote

from playwright.async_api import Page, Response

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


class ResyPlatform(BasePlatform):
    """Resy reservation platform integration."""

    PLATFORM_NAME = "resy"
    BASE_URL = "https://resy.com"
    API_BASE = "https://api.resy.com"

    # Selectors (Resy may change structure; fallbacks for robustness)
    SELECTORS = {
        "login_button": 'button[data-test-id="menu_container-button-log_in"]',
        "login_button_fallback": 'a[href*="login"], [data-test-id*="log_in"]',
        "email_input": 'input[data-test-id="auth_form-input-email"]',
        "email_input_fallback": 'input[type="email"]',
        "password_input": 'input[data-test-id="auth_form-input-password"]',
        "password_input_fallback": 'input[type="password"]',
        "submit_login": 'button[data-test-id="auth_form-button-log_in"]',
        "submit_login_fallback": 'button[type="submit"]',
        "logged_in_indicator": '[data-test-id="menu_container-button-avatar"]',
        "time_slot": '[data-test-id^="time_slot-"]',
        "reserve_button": 'button[data-test-id="order_summary_page-button-book"]',
        "confirm_button": 'button[data-test-id="confirm_button"]',
        "confirmation_number": '[data-test-id="confirmation_number"]',
    }

    async def check_session_valid(self) -> bool:
        """Check if we're logged in to Resy."""
        # Trust recent session from manual_auth (avoids fragile Resy DOM selectors)
        if self.session_manager.has_recent_session(self.PLATFORM_NAME, max_age_hours=168):
            self.logger.info("using_recent_saved_session")
            return True

        try:
            page = await self.get_page()
            await page.goto(self.BASE_URL, wait_until="domcontentloaded")
            await asyncio.sleep(3)  # SPA hydration

            # Look for logged-in indicator (multiple fallbacks)
            for selector in [
                self.SELECTORS["logged_in_indicator"],
                '[data-test-id*="avatar"]',
                'a[href*="profile"]',
                'a[href*="account"]',
            ]:
                avatar = await page.query_selector(selector)
                if avatar is not None:
                    return True

            return False
        except Exception as e:
            self.logger.warning("session_check_failed", error=str(e))
            return False

    async def _wait_and_type(self, page: Page, selectors: list[str], text: str) -> bool:
        """Wait for and type into the first matching visible input."""
        for selector in selectors:
            try:
                await page.wait_for_selector(selector, state="visible", timeout=8000)
                await page.locator(selector).first.click()
                await asyncio.sleep(0.2)
                await page.locator(selector).first.fill("")
                await page.locator(selector).first.fill(text)
                return True
            except Exception:
                continue
        return False

    async def login(self) -> bool:
        """Log in to Resy using email/password."""
        if not self.credentials:
            raise AuthenticationError(self.PLATFORM_NAME, "No credentials provided")

        try:
            page = await self.get_page()

            self.logger.info("navigating_to_login")
            await page.goto(self.BASE_URL, wait_until="domcontentloaded")

            # Click login button (try primary, then fallback)
            for login_sel in [
                self.SELECTORS["login_button"],
                self.SELECTORS["login_button_fallback"],
            ]:
                try:
                    await page.wait_for_selector(login_sel, state="visible", timeout=5000)
                    await page.locator(login_sel).first.click()
                    break
                except Exception:
                    continue
            else:
                raise AuthenticationError(
                    self.PLATFORM_NAME, "Could not find login button"
                )

            # Login modal may take several seconds to render (SPA)
            await asyncio.sleep(5)

            # Enter email (try primary, then fallback)
            email_ok = await self._wait_and_type(
                page,
                [
                    self.SELECTORS["email_input"],
                    self.SELECTORS["email_input_fallback"],
                ],
                self.credentials.username,
            )
            if not email_ok:
                raise AuthenticationError(
                    self.PLATFORM_NAME, "Could not find email input"
                )
            await StealthBrowser.random_idle(0.3, 0.6)

            # Enter password
            password_ok = await self._wait_and_type(
                page,
                [
                    self.SELECTORS["password_input"],
                    self.SELECTORS["password_input_fallback"],
                ],
                self.credentials.password,
            )
            if not password_ok:
                raise AuthenticationError(
                    self.PLATFORM_NAME, "Could not find password input"
                )
            await StealthBrowser.random_idle(0.2, 0.5)

            # Submit (try primary, then fallback)
            for submit_sel in [
                self.SELECTORS["submit_login"],
                self.SELECTORS["submit_login_fallback"],
            ]:
                try:
                    await page.wait_for_selector(submit_sel, state="visible", timeout=5000)
                    await page.locator(submit_sel).first.click()
                    break
                except Exception:
                    continue

            # Wait for login to complete
            try:
                await page.wait_for_selector(
                    self.SELECTORS["logged_in_indicator"], timeout=15000
                )
                self.logger.info("login_successful")
                await self.save_session()
                return True
            except Exception:
                self.logger.error("login_failed_no_indicator")
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
        """Check availability on Resy for a specific date."""
        page = await self.get_page()

        # Set up API response interception
        interceptor = RequestInterceptor(page)
        await interceptor.start(["/4/find"])

        # Navigate to restaurant page with date and party size
        url = f"{self.BASE_URL}/cities/ny/{restaurant.venue_id}?date={date}&seats={party_size}"
        self.logger.info("checking_availability", url=url)

        await page.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(2)  # Wait for dynamic content

        # Try to get slots from intercepted API response
        slots = []
        api_responses = interceptor.get_captured("/4/find")

        if api_responses:
            # Parse API response
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
        """Parse availability from Resy API response."""
        slots = []
        try:
            venues = response.get("results", {}).get("venues", [])
            for venue in venues:
                for slot_data in venue.get("slots", []):
                    config = slot_data.get("config", {})
                    time_str = slot_data.get("date", {}).get("start", "")

                    # Extract time from ISO format
                    if time_str:
                        time_match = re.search(r"(\d{2}:\d{2})", time_str)
                        if time_match:
                            slot_time = time_match.group(1)
                            slots.append(
                                TimeSlot(
                                    time=slot_time,
                                    slot_id=config.get("token", ""),
                                    slot_type=config.get("type", ""),
                                    raw_data=slot_data,
                                )
                            )
        except Exception as e:
            self.logger.warning("api_parse_error", error=str(e))
        return slots

    async def _parse_dom_availability(self, page: Page) -> list[TimeSlot]:
        """Parse availability from page DOM."""
        slots = []
        try:
            elements = await page.query_selector_all(self.SELECTORS["time_slot"])
            for elem in elements:
                time_text = await elem.text_content()
                slot_id = await elem.get_attribute("data-test-id") or ""

                if time_text:
                    # Parse time from text like "7:00 PM"
                    time_match = re.search(r"(\d{1,2}):(\d{2})\s*(AM|PM)", time_text)
                    if time_match:
                        hour = int(time_match.group(1))
                        minute = time_match.group(2)
                        period = time_match.group(3)

                        if period == "PM" and hour != 12:
                            hour += 12
                        elif period == "AM" and hour == 12:
                            hour = 0

                        slot_time = f"{hour:02d}:{minute}"
                        slots.append(
                            TimeSlot(
                                time=slot_time,
                                slot_id=slot_id,
                                slot_type=None,
                            )
                        )
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
        """Book a specific slot on Resy."""
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

            # Navigate to restaurant if not already there
            url = f"{self.BASE_URL}/cities/ny/{restaurant.venue_id}"
            if url not in page.url:
                await page.goto(
                    f"{url}?date={datetime.now().strftime('%Y-%m-%d')}&seats={party_size}",
                    wait_until="domcontentloaded",
                )

            # Click on the time slot
            slot_selector = f'[data-test-id="time_slot-{slot.time.replace(":", "")}"]'
            try:
                await helper.wait_and_click(slot_selector, timeout=5000)
            except Exception:
                # Try clicking by time text
                time_elements = await page.query_selector_all(self.SELECTORS["time_slot"])
                clicked = False
                for elem in time_elements:
                    text = await elem.text_content()
                    if slot.time in (text or ""):
                        await elem.click()
                        clicked = True
                        break
                if not clicked:
                    raise SlotUnavailableError(self.PLATFORM_NAME, f"Slot {slot.time} not found")

            await asyncio.sleep(1.5)

            # Click reserve button
            await helper.wait_and_click(self.SELECTORS["reserve_button"], timeout=10000)
            await asyncio.sleep(2)

            if dry_run:
                self.logger.info("dry_run_stopping_before_confirm")
                return BookingResult(
                    success=False,
                    booked_time=slot.time,
                    error_message="Dry run - stopped before confirmation",
                )

            # Click final confirm button
            await helper.wait_and_click(self.SELECTORS["confirm_button"], timeout=10000)
            await asyncio.sleep(3)

            # Get confirmation number
            confirmation_elem = await page.query_selector(
                self.SELECTORS["confirmation_number"]
            )
            confirmation_number = None
            if confirmation_elem:
                confirmation_number = await confirmation_elem.text_content()

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

        except SlotUnavailableError:
            raise
        except Exception as e:
            self.logger.error("booking_failed", error=str(e))
            return BookingResult(
                success=False,
                error_message=str(e),
                booked_time=slot.time,
            )
