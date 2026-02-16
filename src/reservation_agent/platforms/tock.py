"""Tock platform implementation."""

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


class TockPlatform(BasePlatform):
    """Tock reservation platform integration.

    Tock is unique in that many restaurants require prepayment/deposits
    and may have ticketed experiences rather than traditional reservations.
    """

    PLATFORM_NAME = "tock"
    BASE_URL = "https://www.exploretock.com"

    # Selectors
    SELECTORS = {
        "sign_in_button": '[data-testid="sign-in-button"]',
        "email_input": 'input[type="email"]',
        "password_input": 'input[type="password"]',
        "submit_login": 'button[type="submit"]',
        "logged_in_avatar": '[data-testid="user-menu-button"]',
        "time_slots": '[data-testid="time-slot"]',
        "experience_card": '[data-testid="experience-card"]',
        "book_button": '[data-testid="book-button"]',
        "checkout_button": '[data-testid="checkout-button"]',
        "confirmation_message": '[data-testid="confirmation-message"]',
        "party_size_dropdown": '[data-testid="party-size-dropdown"]',
        "date_selector": '[data-testid="date-selector"]',
    }

    async def check_session_valid(self) -> bool:
        """Check if we're logged in to Tock."""
        if self.session_manager.has_recent_session(self.PLATFORM_NAME, max_age_hours=168):
            self.logger.info("using_recent_saved_session")
            return True

        try:
            page = await self.get_page()
            await page.goto(self.BASE_URL, wait_until="domcontentloaded")

            # Look for logged-in indicator
            avatar = await page.query_selector(self.SELECTORS["logged_in_avatar"])
            return avatar is not None
        except Exception as e:
            self.logger.warning("session_check_failed", error=str(e))
            return False

    async def login(self) -> bool:
        """Log in to Tock using email/password."""
        if not self.credentials or not getattr(self.credentials, 'username', None):
            if self.session_manager.has_recent_session(self.PLATFORM_NAME, max_age_hours=168):
                self.logger.info("skipping_login_using_session")
                return True
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
        """Check availability on Tock for a specific date.

        Tock often shows experiences/tickets rather than simple time slots.
        """
        page = await self.get_page()

        # Set up API response interception
        interceptor = RequestInterceptor(page)
        await interceptor.start(["/api/consumer/search", "/api/consumer/booking"])

        # Navigate to restaurant page
        # Tock URLs are like /restaurant-name or /restaurant-name/experience/experience-id
        url = f"{self.BASE_URL}/{restaurant.venue_id}"
        self.logger.info("checking_availability", url=url)

        await page.goto(url, wait_until="domcontentloaded")
        await asyncio.sleep(2)

        # Set party size if dropdown exists
        await self._set_party_size(page, party_size)

        # Set date if date selector exists
        await self._set_date(page, date)

        await asyncio.sleep(2)  # Wait for availability to update

        # Try to get slots from API response
        slots = []
        api_responses = interceptor.get_captured("/api/consumer/")

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

    async def _set_party_size(self, page: Page, party_size: int) -> None:
        """Set party size on the page."""
        try:
            dropdown = await page.query_selector(self.SELECTORS["party_size_dropdown"])
            if dropdown:
                await dropdown.click()
                await asyncio.sleep(0.5)
                # Click the option with matching party size
                option = await page.query_selector(f'[data-value="{party_size}"]')
                if option:
                    await option.click()
        except Exception as e:
            self.logger.debug("party_size_set_failed", error=str(e))

    async def _set_date(self, page: Page, date: str) -> None:
        """Set date on the page."""
        try:
            date_selector = await page.query_selector(self.SELECTORS["date_selector"])
            if date_selector:
                await date_selector.click()
                await asyncio.sleep(0.5)
                # Parse date and find matching calendar cell
                # Date format: YYYY-MM-DD
                day = int(date.split("-")[2])
                day_cell = await page.query_selector(f'[data-day="{day}"]')
                if day_cell:
                    await day_cell.click()
        except Exception as e:
            self.logger.debug("date_set_failed", error=str(e))

    def _parse_api_availability(self, response: dict) -> list[TimeSlot]:
        """Parse availability from Tock API response."""
        slots = []
        try:
            # Tock might return experiences or time slots
            experiences = response.get("experiences", [])
            for exp in experiences:
                for slot_data in exp.get("times", []):
                    time_str = slot_data.get("time", "")
                    time_24h = self._convert_to_24h(time_str)
                    if time_24h:
                        slots.append(
                            TimeSlot(
                                time=time_24h,
                                slot_id=slot_data.get("id", ""),
                                slot_type=exp.get("name", ""),
                                deposit_required=slot_data.get("price"),
                                raw_data=slot_data,
                            )
                        )

            # Also check for direct time slots
            time_slots = response.get("timeSlots", response.get("slots", []))
            for slot_data in time_slots:
                time_str = slot_data.get("time", slot_data.get("startTime", ""))
                time_24h = self._convert_to_24h(time_str)
                if time_24h:
                    slots.append(
                        TimeSlot(
                            time=time_24h,
                            slot_id=slot_data.get("id", ""),
                            slot_type=slot_data.get("type", ""),
                            deposit_required=slot_data.get("depositAmount"),
                            raw_data=slot_data,
                        )
                    )
        except Exception as e:
            self.logger.warning("api_parse_error", error=str(e))
        return slots

    def _convert_to_24h(self, time_str: str) -> str | None:
        """Convert time string to 24-hour format."""
        if not time_str:
            return None

        # Handle already 24h format
        if re.match(r"^\d{2}:\d{2}$", time_str):
            return time_str

        # Handle 12h format
        match = re.search(r"(\d{1,2}):(\d{2})\s*(AM|PM)?", time_str, re.IGNORECASE)
        if match:
            hour = int(match.group(1))
            minute = match.group(2)
            period = match.group(3)

            if period:
                period = period.upper()
                if period == "PM" and hour != 12:
                    hour += 12
                elif period == "AM" and hour == 12:
                    hour = 0

            return f"{hour:02d}:{minute}"

        # Handle ISO format
        iso_match = re.search(r"T(\d{2}):(\d{2})", time_str)
        if iso_match:
            return f"{iso_match.group(1)}:{iso_match.group(2)}"

        return None

    async def _parse_dom_availability(self, page: Page) -> list[TimeSlot]:
        """Parse availability from page DOM."""
        slots = []
        try:
            # Look for time slots
            elements = await page.query_selector_all(
                f'{self.SELECTORS["time_slots"]}, [class*="time-slot"], [class*="TimeSlot"]'
            )

            for elem in elements:
                time_text = await elem.text_content()
                slot_id = await elem.get_attribute("data-id") or ""

                if time_text:
                    time_24h = self._convert_to_24h(time_text.strip())
                    if time_24h:
                        # Check for price/deposit
                        price_elem = await elem.query_selector('[class*="price"]')
                        deposit = None
                        if price_elem:
                            price_text = await price_elem.text_content()
                            price_match = re.search(r"\$?([\d,]+(?:\.\d{2})?)", price_text or "")
                            if price_match:
                                deposit = float(price_match.group(1).replace(",", ""))

                        slots.append(
                            TimeSlot(
                                time=time_24h,
                                slot_id=slot_id,
                                slot_type=None,
                                deposit_required=deposit,
                            )
                        )

            # Also look for experience cards (common on Tock)
            if not slots:
                exp_cards = await page.query_selector_all(self.SELECTORS["experience_card"])
                for card in exp_cards:
                    title = await card.query_selector('[class*="title"]')
                    time_elem = await card.query_selector('[class*="time"]')

                    if time_elem:
                        time_text = await time_elem.text_content()
                        time_24h = self._convert_to_24h(time_text or "")
                        card_id = await card.get_attribute("data-id")
                        card_title = await title.text_content() if title else None

                        if time_24h:
                            slots.append(
                                TimeSlot(
                                    time=time_24h,
                                    slot_id=card_id or "",
                                    slot_type=card_title,
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
        """Book a specific slot on Tock.

        Note: Tock often requires payment information for deposits.
        This implementation assumes payment info is saved in the account.
        """
        page = await self.get_page()
        helper = PageHelper(page)

        try:
            self.logger.info(
                "booking_slot",
                restaurant=restaurant.name,
                time=slot.time,
                party_size=party_size,
                dry_run=dry_run,
                deposit_required=slot.deposit_required,
            )

            # Find and click the time slot
            clicked = False

            # Strategy 1: by slot ID
            if slot.slot_id:
                slot_selector = f'[data-id="{slot.slot_id}"]'
                if await page.query_selector(slot_selector):
                    await helper.wait_and_click(slot_selector)
                    clicked = True

            # Strategy 2: by time text
            if not clicked:
                elements = await page.query_selector_all(
                    '[data-testid="time-slot"], [class*="time-slot"]'
                )
                for elem in elements:
                    text = await elem.text_content()
                    if text and slot.time in self._convert_to_24h(text):
                        await elem.click()
                        clicked = True
                        break

            if not clicked:
                raise SlotUnavailableError(self.PLATFORM_NAME, f"Slot {slot.time} not found")

            await asyncio.sleep(2)

            # Click book/add to cart button
            book_button = await page.query_selector(self.SELECTORS["book_button"])
            if book_button:
                await book_button.click()
                await asyncio.sleep(2)

            if dry_run:
                self.logger.info("dry_run_stopping_before_checkout")
                return BookingResult(
                    success=False,
                    booked_time=slot.time,
                    error_message="Dry run - stopped before checkout",
                )

            # Proceed to checkout
            checkout_button = await page.query_selector(self.SELECTORS["checkout_button"])
            if checkout_button:
                await checkout_button.click()
                await asyncio.sleep(3)

            # Look for confirmation
            confirmation = await page.query_selector(self.SELECTORS["confirmation_message"])
            if confirmation:
                confirmation_text = await confirmation.text_content()
                # Extract confirmation number if present
                conf_match = re.search(r"#?(\w{6,})", confirmation_text or "")
                confirmation_number = conf_match.group(1) if conf_match else None

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

            # Check URL for confirmation indicator
            if "confirmation" in page.url.lower() or "success" in page.url.lower():
                return BookingResult(
                    success=True,
                    booked_time=slot.time,
                )

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
