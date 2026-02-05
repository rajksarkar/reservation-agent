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
        url = f"{self.BASE_URL}/cities/ny/{restaurant.venue_id}?date={date}&seats={party_size}"
        self.logger.info("checking_availability", url=url)

        # Use a dedicated page for this check (allows concurrent checks)
        page = await self.get_page(force_new=True)
        interceptor = None

        try:
            # Retry navigation up to 3 times
            max_retries = 3
            last_error = None

            for attempt in range(max_retries):
                try:
                    # Set up API response interception
                    interceptor = RequestInterceptor(page)
                    await interceptor.start(["/4/find"])

                    # Navigate to restaurant page with date and party size
                    await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                    await asyncio.sleep(2)  # Wait for dynamic content
                    break  # Success, exit retry loop
                except Exception as e:
                    last_error = e
                    self.logger.warning(
                        "navigation_failed_retrying",
                        attempt=attempt + 1,
                        max_retries=max_retries,
                        error=str(e),
                    )
                    if attempt < max_retries - 1:
                        # Clear interceptor and reload page
                        if interceptor:
                            interceptor.clear()
                        await asyncio.sleep(1)  # Brief pause before retry
            else:
                # All retries failed
                raise last_error or Exception("Navigation failed after retries")

            # Try to get slots from intercepted API response
            slots = []
            api_responses = interceptor.get_captured("/4/find") if interceptor else []

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
        finally:
            # Always close the dedicated page
            if not page.is_closed():
                await page.close()

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
        date: str | None = None,
    ) -> BookingResult:
        """Book a specific slot on Resy."""
        # Use a dedicated page to avoid concurrent navigation conflicts
        page = await self.get_page(force_new=True)
        helper = PageHelper(page)

        try:
            self.logger.info(
                "booking_slot",
                restaurant=restaurant.name,
                time=slot.time,
                party_size=party_size,
                dry_run=dry_run,
            )

            # Navigate to restaurant page with date and party size
            book_date = date or datetime.now().strftime("%Y-%m-%d")
            url = f"{self.BASE_URL}/cities/ny/{restaurant.venue_id}?date={book_date}&seats={party_size}"
            self.logger.info("navigating_to_restaurant", url=url)
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await asyncio.sleep(3)  # Wait for SPA to render slots

            # Click on the time slot
            clicked = False

            # Strategy 1: by data-testid using slot_id from API
            if slot.slot_id:
                testid_selector = f'button[data-testid="reservation-button-{slot.slot_id}"]'
                btn = await page.query_selector(testid_selector)
                if btn and await btn.is_visible():
                    await btn.click()
                    clicked = True

            # Strategy 2: find ReservationButton matching time and type
            if not clicked:
                # Convert 24h to 12h display time
                slot_hour = int(slot.time.split(":")[0])
                slot_minute = slot.time.split(":")[1]
                if slot_hour == 0:
                    display_time = f"12:{slot_minute} AM"
                elif slot_hour < 12:
                    display_time = f"{slot_hour}:{slot_minute} AM"
                elif slot_hour == 12:
                    display_time = f"12:{slot_minute} PM"
                else:
                    display_time = f"{slot_hour - 12}:{slot_minute} PM"

                buttons = await page.query_selector_all('button.ReservationButton')
                for btn in buttons:
                    if not await btn.is_visible():
                        continue
                    time_div = await btn.query_selector('.ReservationButton__time')
                    if time_div:
                        time_text = (await time_div.text_content() or "").strip()
                        if time_text == display_time:
                            # Prefer Dining Room over Patio
                            type_div = await btn.query_selector('.ReservationButton__type')
                            type_text = (await type_div.text_content() or "").strip() if type_div else ""
                            if type_text == (slot.slot_type or "Dining Room"):
                                await btn.click()
                                clicked = True
                                break

                # If preferred type not found, click any matching time
                if not clicked:
                    for btn in buttons:
                        if not await btn.is_visible():
                            continue
                        time_div = await btn.query_selector('.ReservationButton__time')
                        if time_div:
                            time_text = (await time_div.text_content() or "").strip()
                            if time_text == display_time:
                                await btn.click()
                                clicked = True
                                break

            # Strategy 3: legacy selector fallback
            if not clicked:
                slot_selector = f'[data-test-id="time_slot-{slot.time.replace(":", "")}"]'
                try:
                    await helper.wait_and_click(slot_selector, timeout=3000)
                    clicked = True
                except Exception:
                    pass

            if not clicked:
                raise SlotUnavailableError(self.PLATFORM_NAME, f"Slot {slot.time} not found")

            await asyncio.sleep(3)

            # Resy opens a widget iframe for the booking modal
            widget_frame = None
            for frame in page.frames:
                if "widgets.resy.com" in frame.url:
                    widget_frame = frame
                    self.logger.info("found_widget_iframe")
                    break

            # Click "Reserve Now" button — look in widget iframe first, then main page
            reserve_clicked = False

            if widget_frame:
                # Wait for iframe content to settle
                await asyncio.sleep(2)

                # Strategy 1: find button with "Reserve Now" text in widget iframe
                buttons = await widget_frame.query_selector_all('button')
                for btn in buttons:
                    try:
                        if not await btn.is_visible():
                            continue
                        text = (await btn.text_content() or "").strip()
                        if "Reserve Now" in text or "Complete Reservation" in text:
                            if dry_run:
                                self.logger.info("dry_run_stopping_before_confirm")
                                return BookingResult(
                                    success=False,
                                    booked_time=slot.time,
                                    error_message="Dry run - stopped before confirmation",
                                )
                            await btn.click()
                            reserve_clicked = True
                            self.logger.info("clicked_reserve_now_in_iframe")
                            break
                    except Exception:
                        continue

            # Fallback: search main page (older Resy layouts without iframe)
            if not reserve_clicked:
                buttons = await page.query_selector_all('button')
                for btn in buttons:
                    if not await btn.is_visible():
                        continue
                    text = (await btn.text_content() or "").strip()
                    if "Reserve Now" in text or "Complete Reservation" in text:
                        if dry_run:
                            self.logger.info("dry_run_stopping_before_confirm")
                            return BookingResult(
                                success=False,
                                booked_time=slot.time,
                                error_message="Dry run - stopped before confirmation",
                            )
                        await btn.click()
                        reserve_clicked = True
                        break

            # Strategy 3: try known selectors on main page
            if not reserve_clicked:
                for reserve_sel in [
                    self.SELECTORS["reserve_button"],
                    'button[data-test-id*="reserve"]',
                ]:
                    try:
                        await helper.wait_and_click(reserve_sel, timeout=3000)
                        reserve_clicked = True
                        break
                    except Exception:
                        continue

            if not reserve_clicked:
                return BookingResult(
                    success=False,
                    booked_time=slot.time,
                    error_message="Could not find Reserve Now button",
                )

            await asyncio.sleep(5)

            # Check for confirmation — look in widget iframe first, then main page
            confirmation_number = None
            search_targets = [widget_frame, page] if widget_frame else [page]

            for target in search_targets:
                if target is None:
                    continue
                # Look for confirmation number element
                confirmation_elem = await target.query_selector(
                    self.SELECTORS["confirmation_number"]
                )
                if confirmation_elem:
                    confirmation_number = await confirmation_elem.text_content()
                    break

                # Also check for confirmation text patterns
                try:
                    result = await target.evaluate("""() => {
                        const el = document.querySelector('[class*="confirmation"], [class*="Confirmation"]');
                        return el ? el.textContent.trim() : null;
                    }""")
                    if result:
                        confirmation_number = result
                        break
                except Exception:
                    pass

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
        finally:
            # Always close the dedicated page
            if not page.is_closed():
                await page.close()
