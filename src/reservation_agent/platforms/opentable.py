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
        # Build URL - Firefox handles OpenTable; Chromium is often blocked
        url = f"{self.BASE_URL}/r/{restaurant.venue_id}?covers={party_size}&dateTime={date}%2019%3A00"
        self.logger.info("checking_availability", url=url, date=date)

        # Use a dedicated page for this check (allows concurrent checks)
        page = await self.get_page(force_new=True)
        interceptor = None

        try:
            # Block heavy resources to reduce memory pressure in the Railway container
            await page.route(
                "**/*.{png,jpg,jpeg,gif,svg,ico,webp,woff,woff2,ttf,eot,otf,mp4,webm,mp3,ogg,css}",
                lambda route: route.abort(),
            )

            # Retry navigation up to 3 times
            max_retries = 3
            last_error = None

            for attempt in range(max_retries):
                try:
                    # Set up API response interception
                    interceptor = RequestInterceptor(page)
                    await interceptor.start(["/availability"])

                    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                    await asyncio.sleep(4)  # Let slots populate
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
                        # Clear interceptor and reload
                        if interceptor:
                            interceptor.clear()
                        await asyncio.sleep(2)  # Brief pause before retry
            else:
                # All retries failed
                raise last_error or Exception("Navigation failed after retries")

            # Check for "no availability" message first
            no_avail = await page.evaluate("""() => {
                const text = document.body.innerText;
                return text.includes("no online availability") ||
                       text.includes("No availability") ||
                       text.includes("no availability");
            }""")

            # Try to get slots from API response
            slots = []
            api_responses = interceptor.get_captured("/availability") if interceptor else []

            if no_avail:
                self.logger.info("no_availability_message_detected", date=date)
                # Even with no-availability message, check API for actual data
                if api_responses:
                    for resp in api_responses:
                        slots.extend(self._parse_api_availability(resp.get("body", {})))
                # Do NOT fall through to DOM parsing - "also like" section has other restaurants
            elif api_responses:
                for resp in api_responses:
                    slots.extend(self._parse_api_availability(resp.get("body", {})))
            else:
                # Fallback: parse from DOM only for target restaurant's slot area
                slots = await self._parse_dom_availability(page, restaurant.name)

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

    async def _parse_dom_availability(self, page: Page, restaurant_name: str = "") -> list[TimeSlot]:
        """Parse availability from page DOM for the target restaurant only."""
        slots = []
        try:
            # Only match slots whose aria-label references the target restaurant
            slot_links = await page.query_selector_all('li[data-test^="time-slot-"] a[role="button"]')
            restaurant_lower = restaurant_name.lower() if restaurant_name else ""

            for link in slot_links:
                if not await link.is_visible():
                    continue
                aria = (await link.get_attribute("aria-label") or "").lower()
                # Only accept slots for the target restaurant (or accept all if name unknown)
                if restaurant_lower and restaurant_lower not in aria:
                    continue

                text = (await link.text_content() or "").strip()
                time_24h = self._convert_to_24h(text)
                if time_24h:
                    slots.append(
                        TimeSlot(
                            time=time_24h,
                            slot_id=text,
                            slot_type=None,
                        )
                    )

        except Exception as e:
            err_str = str(e)
            # Re-raise browser/page crash errors so the orchestrator can reset the
            # browser context.  Silently returning [] would mask the crash and leave
            # Firefox in a dead state for subsequent requests.
            if any(
                s in err_str
                for s in (
                    "Target page, context or browser has been closed",
                    "Browser has been closed",
                    "context has been closed",
                )
            ):
                raise
            self.logger.warning("dom_parse_error", error=err_str)
        return slots

    async def book_slot(
        self,
        restaurant: RestaurantConfig,
        slot: TimeSlot,
        party_size: int,
        dry_run: bool = False,
        date: str | None = None,
    ) -> BookingResult:
        """Book a specific slot on OpenTable."""
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

            # Navigate to restaurant page if not already there
            if date:
                url = f"{self.BASE_URL}/r/{restaurant.venue_id}?covers={party_size}&dateTime={date}%20{slot.time.replace(':', '%3A')}"
                self.logger.info("navigating_to_restaurant", url=url)
                await page.goto(url, wait_until="domcontentloaded", timeout=30000)
                await asyncio.sleep(2)  # Let slots populate

            # Click on the time slot
            # Convert 24h time to 12h for matching DOM text (e.g. "19:00" -> "7:00 PM")
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

            clicked = False

            # Strategy 1: find visible slot by aria-label containing the time AND restaurant name
            restaurant_lower = restaurant.name.lower()
            slot_links = await page.query_selector_all('li[data-test^="time-slot-"] a[role="button"]')
            for link in slot_links:
                if not await link.is_visible():
                    continue
                aria_label = await link.get_attribute("aria-label") or ""
                text = await link.text_content() or ""
                # Must match the time AND reference the target restaurant (not other restaurants)
                if display_time in aria_label or display_time in text:
                    if restaurant_lower in aria_label.lower() or "reserve" not in aria_label.lower():
                        await link.click()
                        clicked = True
                        break

            # Strategy 2: find visible slot by text content (scoped to target restaurant)
            if not clicked:
                slot_items = await page.query_selector_all('li[data-test^="time-slot-"]')
                for item in slot_items:
                    if not await item.is_visible():
                        continue
                    text = await item.text_content() or ""
                    if display_time in text:
                        # Check aria-label of child link for restaurant name
                        child_link = await item.query_selector('a[role="button"]')
                        if child_link:
                            aria = (await child_link.get_attribute("aria-label") or "").lower()
                            if restaurant_lower not in aria and "reserve" in aria:
                                continue  # Skip - this is another restaurant's slot
                        clickable = await item.query_selector("a, button")
                        if clickable:
                            await clickable.click()
                        else:
                            await item.click()
                        clicked = True
                        break

            # Strategy 3: fallback to older selectors
            if not clicked:
                buttons = await page.query_selector_all('button[data-time], [data-test="time-slot"]')
                for btn in buttons:
                    if not await btn.is_visible():
                        continue
                    btn_time = await btn.get_attribute("data-time")
                    btn_text = await btn.text_content() or ""
                    if btn_time == slot.time or display_time in btn_text:
                        await btn.click()
                        clicked = True
                        break

            if not clicked:
                raise SlotUnavailableError(self.PLATFORM_NAME, f"Slot {slot.time} ({display_time}) not found")

            # Wait for navigation after clicking the slot
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=15000)
            except Exception:
                pass
            await asyncio.sleep(1)

            self.logger.info("post_slot_click", url=page.url)

            # Handle seating options page if present (Standard / Outdoor / etc.)
            if "seating-options" in page.url:
                self.logger.info("selecting_seating_option", option="Standard")
                select_buttons = await page.query_selector_all('button')
                for btn in select_buttons:
                    if await btn.is_visible():
                        text = await btn.text_content() or ""
                        if text.strip() == "Select":
                            await btn.click()
                            break
                try:
                    await page.wait_for_load_state("domcontentloaded", timeout=10000)
                except Exception:
                    pass
                await asyncio.sleep(1)

            # Handle specials/upgrades page if present
            if "specials" in page.url:
                self.logger.info("skipping_specials_page")
                # Look for "No thanks" or "Skip" button, or just the complete button
                for skip_text in ["No thanks", "No, thanks", "Skip"]:
                    skip_btns = await page.query_selector_all('button')
                    for btn in skip_btns:
                        if await btn.is_visible():
                            text = (await btn.text_content() or "").strip()
                            if skip_text.lower() in text.lower():
                                await btn.click()
                                try:
                                    await page.wait_for_load_state("domcontentloaded", timeout=10000)
                                except Exception:
                                    pass
                                await asyncio.sleep(1)
                                break
                    else:
                        continue
                    break

            if dry_run:
                self.logger.info("dry_run_stopping_before_confirm")
                return BookingResult(
                    success=False,
                    booked_time=slot.time,
                    error_message="Dry run - stopped before confirmation",
                )

            self.logger.info("looking_for_complete_button", url=page.url)

            # Click complete reservation button (try multiple selectors)
            complete_clicked = False
            for complete_sel in [
                self.SELECTORS["complete_reservation"],
                'button[data-test*="complete"]',
                'button[type="submit"]',
            ]:
                try:
                    await helper.wait_and_click(complete_sel, timeout=10000)
                    complete_clicked = True
                    self.logger.info("clicked_complete_reservation")
                    break
                except Exception:
                    continue

            if not complete_clicked:
                # Log page content for debugging
                page_text = await page.evaluate("() => document.body.innerText.substring(0, 500)")
                self.logger.warning(
                    "complete_button_not_found",
                    url=page.url,
                    page_text=page_text,
                )
                return BookingResult(
                    success=False,
                    error_message="Could not find complete reservation button",
                    booked_time=slot.time,
                )

            # Wait for confirmation page
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=15000)
            except Exception:
                pass
            await asyncio.sleep(2)

            # Check for confirmation
            confirmation_number = None
            confirmation_elem = await page.query_selector(
                self.SELECTORS["confirmation_number"]
            )
            if confirmation_elem:
                confirmation_number = await confirmation_elem.text_content()

            # Verify success by URL, confirmation element, or page text
            page_text = await page.evaluate("() => document.body.innerText")
            is_confirmed = (
                "confirmation" in page.url.lower()
                or confirmation_number
                or "reservation is confirmed" in page_text.lower()
                or "you're all booked" in page_text.lower()
                or "booking confirmed" in page_text.lower()
            )

            if is_confirmed:
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
                self.logger.warning(
                    "booking_not_confirmed",
                    url=page.url,
                    page_text=page_text[:300],
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
        finally:
            # Always close the dedicated page
            if not page.is_closed():
                await page.close()

    # ------------------------------------------------------------------
    # Combined single-page check + book (used by snipe flow)
    # ------------------------------------------------------------------
    async def check_and_book(
        self,
        restaurant: RestaurantConfig,
        date: str,
        party_size: int,
        preferred_times: list[str],
        dry_run: bool = False,
    ) -> tuple[BookingResult | None, TimeSlot | None]:
        """Check availability and book in a single page session.

        Instead of navigating twice (once to check, once to book), this keeps
        the same page open: find slots → click the best one → handle seating
        options → confirm.  Returns (BookingResult, slot) or (None, None) when
        no matching slot is found.
        """
        url = (
            f"{self.BASE_URL}/r/{restaurant.venue_id}"
            f"?covers={party_size}&dateTime={date}%2019%3A00"
        )
        self.logger.info("check_and_book_start", url=url, date=date)

        page = await self.get_page(force_new=True)
        helper = PageHelper(page)
        interceptor = None

        try:
            # Block heavy resources to reduce memory pressure in the Railway container
            await page.route(
                "**/*.{png,jpg,jpeg,gif,svg,ico,webp,woff,woff2,ttf,eot,otf,mp4,webm,mp3,ogg,css}",
                lambda route: route.abort(),
            )

            # ---- 1. Navigate to restaurant page ----
            max_retries = 3
            last_error = None
            for attempt in range(max_retries):
                try:
                    interceptor = RequestInterceptor(page)
                    await interceptor.start(["/availability"])
                    await page.goto(url, wait_until="domcontentloaded", timeout=60000)
                    await asyncio.sleep(4)
                    break
                except Exception as e:
                    last_error = e
                    self.logger.warning(
                        "check_and_book_nav_retry",
                        attempt=attempt + 1,
                        error=str(e),
                    )
                    if interceptor:
                        interceptor.clear()
                    if attempt < max_retries - 1:
                        await asyncio.sleep(2)
            else:
                raise last_error or Exception("Navigation failed after retries")

            # ---- 2. Collect available slots ----
            slots: list[TimeSlot] = []
            api_responses = (
                interceptor.get_captured("/availability") if interceptor else []
            )

            no_avail = await page.evaluate("""() => {
                const text = document.body.innerText;
                return text.includes("no online availability") ||
                       text.includes("No availability") ||
                       text.includes("no availability");
            }""")

            if no_avail:
                self.logger.info("check_and_book_no_avail", date=date)
                if api_responses:
                    for resp in api_responses:
                        slots.extend(self._parse_api_availability(resp.get("body", {})))
            elif api_responses:
                for resp in api_responses:
                    slots.extend(self._parse_api_availability(resp.get("body", {})))
            else:
                slots = await self._parse_dom_availability(page, restaurant.name)

            self.logger.info("check_and_book_slots", count=len(slots))

            if not slots:
                return None, None

            # ---- 3. Filter for preferred times ----
            matching = self.filter_preferred_slots(slots, preferred_times)
            if not matching:
                self.logger.info("check_and_book_no_match", preferred=preferred_times)
                return None, None

            slot = matching[0]
            self.logger.info("check_and_book_clicking_slot", time=slot.time)

            # ---- 4. Click the slot on the same page ----
            display_time = self._to_display_time(slot.time)
            clicked = await self._click_time_slot(page, display_time, restaurant.name)

            if not clicked:
                raise SlotUnavailableError(
                    self.PLATFORM_NAME,
                    f"Slot {slot.time} ({display_time}) not found on page",
                )

            try:
                await page.wait_for_load_state("domcontentloaded", timeout=15000)
            except Exception:
                pass
            await asyncio.sleep(1)

            self.logger.info("check_and_book_post_click", url=page.url)

            # ---- 4b. Swap to a fresh page to free Firefox memory ----
            # The slot click navigates to a heavy booking page (seating-options,
            # etc.).  Keeping the restaurant page's JS heap alive while loading
            # that second page causes OOM on Railway.  Close the current page
            # and reopen a fresh one; the booking URL is self-contained so the
            # same session cookies are enough to resume the flow.
            booking_url = page.url
            await page.close()
            page = await self.get_page(force_new=True)
            helper = PageHelper(page)
            await page.route(
                "**/*.{png,jpg,jpeg,gif,svg,ico,webp,woff,woff2,ttf,eot,otf,mp4,webm,mp3,ogg,css}",
                lambda route: route.abort(),
            )
            if "/booking/" in booking_url or "seating-options" in booking_url:
                try:
                    await page.goto(
                        booking_url, wait_until="domcontentloaded", timeout=30000
                    )
                    await asyncio.sleep(1)
                    self.logger.info("reopened_booking_page", url=booking_url[:80])
                except Exception as e:
                    self.logger.warning("reopen_booking_nav_error", error=str(e))

            # ---- 5. Handle seating options (prefer non-outdoor) ----
            await self._handle_seating_options(page)

            # ---- 6. Handle specials/upgrades page ----
            await self._handle_specials(page)

            # ---- 7. Confirm reservation ----
            if dry_run:
                self.logger.info("dry_run_stopping_before_confirm")
                return (
                    BookingResult(
                        success=False,
                        booked_time=slot.time,
                        error_message="Dry run - stopped before confirmation",
                    ),
                    slot,
                )

            result = await self._click_confirm_and_verify(page, helper, slot.time)
            return result, slot

        except SlotUnavailableError:
            raise
        except Exception as e:
            self.logger.error("check_and_book_error", error=str(e))
            return (
                BookingResult(success=False, error_message=str(e), booked_time=None),
                None,
            )
        finally:
            if not page.is_closed():
                await page.close()

    # ------------------------------------------------------------------
    # Shared helpers (used by both book_slot and check_and_book)
    # ------------------------------------------------------------------
    @staticmethod
    def _to_display_time(time_24h: str) -> str:
        """Convert 24-hour time (e.g. '19:00') to display format ('7:00 PM')."""
        hour = int(time_24h.split(":")[0])
        minute = time_24h.split(":")[1]
        if hour == 0:
            return f"12:{minute} AM"
        if hour < 12:
            return f"{hour}:{minute} AM"
        if hour == 12:
            return f"12:{minute} PM"
        return f"{hour - 12}:{minute} PM"

    async def _click_time_slot(
        self, page: Page, display_time: str, restaurant_name: str
    ) -> bool:
        """Click a time-slot button on the page. Returns True on success."""
        restaurant_lower = restaurant_name.lower()

        # Strategy 1: aria-label on slot links
        slot_links = await page.query_selector_all(
            'li[data-test^="time-slot-"] a[role="button"]'
        )
        for link in slot_links:
            if not await link.is_visible():
                continue
            aria = await link.get_attribute("aria-label") or ""
            text = await link.text_content() or ""
            if display_time in aria or display_time in text:
                if restaurant_lower in aria.lower() or "reserve" not in aria.lower():
                    await link.click()
                    return True

        # Strategy 2: slot items by text content
        slot_items = await page.query_selector_all('li[data-test^="time-slot-"]')
        for item in slot_items:
            if not await item.is_visible():
                continue
            text = await item.text_content() or ""
            if display_time in text:
                child_link = await item.query_selector('a[role="button"]')
                if child_link:
                    aria = (await child_link.get_attribute("aria-label") or "").lower()
                    if restaurant_lower not in aria and "reserve" in aria:
                        continue
                clickable = await item.query_selector("a, button")
                if clickable:
                    await clickable.click()
                else:
                    await item.click()
                return True

        # Strategy 3: older selectors
        buttons = await page.query_selector_all(
            'button[data-time], [data-test="time-slot"]'
        )
        for btn in buttons:
            if not await btn.is_visible():
                continue
            btn_time = await btn.get_attribute("data-time")
            btn_text = await btn.text_content() or ""
            if btn_time == display_time.replace(" ", "") or display_time in btn_text:
                await btn.click()
                return True

        return False

    async def _handle_seating_options(self, page: Page) -> None:
        """Handle the seating-options page: prefer non-outdoor options."""
        if "seating-options" not in page.url:
            return

        self.logger.info("handling_seating_options")

        # Collect all option cards with their labels and Select buttons.
        # Each option is typically a section/div with a heading and a Select btn.
        outdoor_keywords = {"outdoor", "patio", "terrace", "garden", "rooftop"}
        preferred_btn = None
        fallback_btn = None

        select_buttons = await page.query_selector_all("button")
        for btn in select_buttons:
            if not await btn.is_visible():
                continue
            text = (await btn.text_content() or "").strip()
            if text.lower() != "select":
                continue

            # Walk up to the parent card/container and get its full text
            parent_text = await page.evaluate(
                """(el) => {
                    let node = el.parentElement;
                    for (let i = 0; i < 5 && node; i++) { node = node.parentElement; }
                    return node ? node.innerText : '';
                }""",
                btn,
            )
            parent_lower = parent_text.lower()
            is_outdoor = any(kw in parent_lower for kw in outdoor_keywords)

            if not is_outdoor and preferred_btn is None:
                preferred_btn = btn
            if fallback_btn is None:
                fallback_btn = btn

        chosen = preferred_btn or fallback_btn
        if chosen:
            label = "non-outdoor" if preferred_btn else "fallback"
            self.logger.info("selecting_seating_option", choice=label)
            await chosen.click()
            try:
                await page.wait_for_load_state("domcontentloaded", timeout=10000)
            except Exception:
                pass
            await asyncio.sleep(1)

    async def _handle_specials(self, page: Page) -> None:
        """Skip the specials/upgrades page if present."""
        if "specials" not in page.url:
            return

        self.logger.info("skipping_specials_page")
        for skip_text in ["No thanks", "No, thanks", "Skip"]:
            skip_btns = await page.query_selector_all("button")
            for btn in skip_btns:
                if not await btn.is_visible():
                    continue
                text = (await btn.text_content() or "").strip()
                if skip_text.lower() in text.lower():
                    await btn.click()
                    try:
                        await page.wait_for_load_state(
                            "domcontentloaded", timeout=10000
                        )
                    except Exception:
                        pass
                    await asyncio.sleep(1)
                    return

    async def _click_confirm_and_verify(
        self, page: Page, helper: PageHelper, slot_time: str
    ) -> BookingResult:
        """Click 'Complete Reservation' and verify confirmation."""
        self.logger.info("looking_for_complete_button", url=page.url)

        # Fill phone number if the booking/details form requires it
        phone = (self.credentials or {}).get("phone") if isinstance(self.credentials, dict) else None
        if phone:
            try:
                phone_input = await page.query_selector('input[type="tel"], input[name*="phone"], input[placeholder*="phone" i]')
                if phone_input:
                    current = await phone_input.input_value()
                    if not current:
                        await phone_input.fill(phone)
                        self.logger.info("filled_phone_number")
            except Exception as e:
                self.logger.warning("phone_fill_failed", error=str(e))

        complete_clicked = False
        for sel in [
            self.SELECTORS["complete_reservation"],
            'button[data-test*="complete"]',
            'button[type="submit"]',
        ]:
            try:
                await helper.wait_and_click(sel, timeout=10000)
                complete_clicked = True
                self.logger.info("clicked_complete_reservation")
                break
            except Exception:
                continue

        if not complete_clicked:
            page_text = await page.evaluate(
                "() => document.body.innerText.substring(0, 500)"
            )
            self.logger.warning(
                "complete_button_not_found", url=page.url, page_text=page_text
            )
            return BookingResult(
                success=False,
                error_message="Could not find complete reservation button",
                booked_time=slot_time,
            )

        try:
            await page.wait_for_load_state("domcontentloaded", timeout=15000)
        except Exception:
            pass
        await asyncio.sleep(2)

        # Check confirmation
        confirmation_number = None
        conf_elem = await page.query_selector(self.SELECTORS["confirmation_number"])
        if conf_elem:
            confirmation_number = await conf_elem.text_content()

        page_text = await page.evaluate("() => document.body.innerText")
        is_confirmed = (
            "confirmation" in page.url.lower()
            or confirmation_number
            or "reservation is confirmed" in page_text.lower()
            or "you're all booked" in page_text.lower()
            or "booking confirmed" in page_text.lower()
        )

        if is_confirmed:
            self.logger.info(
                "booking_successful",
                confirmation=confirmation_number,
                time=slot_time,
            )
            return BookingResult(
                success=True,
                confirmation_number=confirmation_number,
                booked_time=slot_time,
            )

        self.logger.warning(
            "booking_not_confirmed", url=page.url, page_text=page_text[:300]
        )
        return BookingResult(
            success=False,
            error_message="Could not confirm booking success",
            booked_time=slot_time,
        )
