"""Anti-detection measures for browser automation."""

import asyncio
import random
from typing import Callable

from playwright.async_api import Page

from reservation_agent.utils.logging import get_logger

logger = get_logger(__name__)


class StealthBrowser:
    """Provides anti-detection measures for browser automation."""

    # Realistic mouse movement parameters
    MOUSE_STEP_MIN = 5
    MOUSE_STEP_MAX = 20
    MOUSE_DELAY_MIN = 10
    MOUSE_DELAY_MAX = 50

    # Typing parameters
    TYPE_DELAY_MIN = 50
    TYPE_DELAY_MAX = 150

    @staticmethod
    async def human_type(page: Page, selector: str, text: str) -> None:
        """Type text with human-like timing variations."""
        element = await page.wait_for_selector(selector)
        if not element:
            return

        await element.click()
        await asyncio.sleep(random.uniform(0.1, 0.3))

        for char in text:
            await page.keyboard.type(char)
            # Variable delay between keystrokes
            delay = random.randint(
                StealthBrowser.TYPE_DELAY_MIN, StealthBrowser.TYPE_DELAY_MAX
            )
            await asyncio.sleep(delay / 1000)

            # Occasional longer pause (simulating thinking)
            if random.random() < 0.05:
                await asyncio.sleep(random.uniform(0.3, 0.8))

    @staticmethod
    async def human_move_to(page: Page, x: int, y: int) -> None:
        """Move mouse to coordinates with human-like motion."""
        # Get current position (default to corner if not set)
        current = await page.evaluate("() => ({x: window.mouseX || 0, y: window.mouseY || 0})")
        start_x, start_y = current.get("x", 0), current.get("y", 0)

        # Calculate distance
        distance_x = x - start_x
        distance_y = y - start_y

        # Number of steps based on distance
        steps = max(
            10, int((abs(distance_x) + abs(distance_y)) / random.randint(10, 30))
        )

        for i in range(steps):
            # Easing function (ease-out)
            progress = (i + 1) / steps
            eased_progress = 1 - (1 - progress) ** 2

            # Add slight randomness
            noise_x = random.gauss(0, 2)
            noise_y = random.gauss(0, 2)

            current_x = start_x + (distance_x * eased_progress) + noise_x
            current_y = start_y + (distance_y * eased_progress) + noise_y

            await page.mouse.move(current_x, current_y)
            await asyncio.sleep(
                random.randint(StealthBrowser.MOUSE_DELAY_MIN, StealthBrowser.MOUSE_DELAY_MAX)
                / 1000
            )

        # Final precise move
        await page.mouse.move(x, y)

        # Store position
        await page.evaluate(f"() => {{ window.mouseX = {x}; window.mouseY = {y}; }}")

    @staticmethod
    async def human_click(page: Page, selector: str) -> None:
        """Click an element with human-like behavior."""
        element = await page.wait_for_selector(selector)
        if not element:
            return

        # Get element bounding box
        box = await element.bounding_box()
        if not box:
            await element.click()
            return

        # Click at random point within element (not center)
        x = box["x"] + random.uniform(box["width"] * 0.2, box["width"] * 0.8)
        y = box["y"] + random.uniform(box["height"] * 0.2, box["height"] * 0.8)

        # Move to element
        await StealthBrowser.human_move_to(page, int(x), int(y))

        # Slight pause before click
        await asyncio.sleep(random.uniform(0.05, 0.15))

        # Click
        await page.mouse.click(x, y)

        # Pause after click
        await asyncio.sleep(random.uniform(0.1, 0.3))

    @staticmethod
    async def random_scroll(page: Page, direction: str = "down", amount: int | None = None) -> None:
        """Perform human-like scrolling."""
        if amount is None:
            amount = random.randint(100, 400)

        if direction == "up":
            amount = -amount

        # Smooth scroll with variable speed
        steps = random.randint(3, 8)
        step_amount = amount / steps

        for _ in range(steps):
            await page.mouse.wheel(0, step_amount)
            await asyncio.sleep(random.uniform(0.02, 0.08))

    @staticmethod
    async def random_idle(min_seconds: float = 1.0, max_seconds: float = 3.0) -> None:
        """Idle for a random duration (simulating reading/thinking)."""
        await asyncio.sleep(random.uniform(min_seconds, max_seconds))

    @staticmethod
    async def simulate_reading(page: Page, duration_seconds: float = 2.0) -> None:
        """Simulate reading a page with occasional scrolls."""
        end_time = asyncio.get_event_loop().time() + duration_seconds

        while asyncio.get_event_loop().time() < end_time:
            # Random action
            action = random.choice(["scroll", "wait", "wait", "wait"])

            if action == "scroll":
                await StealthBrowser.random_scroll(page)
            else:
                await asyncio.sleep(random.uniform(0.5, 1.5))


class RequestInterceptor:
    """Intercept and monitor network requests."""

    def __init__(self, page: Page):
        self.page = page
        self.captured_responses: dict[str, list] = {}
        self._handlers: list[Callable] = []

    async def start(self, url_patterns: list[str] | None = None) -> None:
        """Start intercepting requests matching patterns."""
        self.url_patterns = url_patterns or []

        async def on_response(response):
            url = response.url
            for pattern in self.url_patterns:
                if pattern in url:
                    try:
                        body = await response.json()
                        if pattern not in self.captured_responses:
                            self.captured_responses[pattern] = []
                        self.captured_responses[pattern].append({
                            "url": url,
                            "status": response.status,
                            "body": body,
                        })
                        logger.debug("captured_response", url=url, pattern=pattern)
                    except Exception:
                        pass
                    break

        self.page.on("response", on_response)

    def get_captured(self, pattern: str) -> list:
        """Get captured responses for a pattern."""
        return self.captured_responses.get(pattern, [])

    def clear(self) -> None:
        """Clear captured responses."""
        self.captured_responses.clear()


class RateLimiter:
    """Rate limiter with adaptive timing."""

    def __init__(
        self,
        requests_per_minute: int = 30,
        min_delay_ms: int = 500,
        max_delay_ms: int = 3000,
    ):
        self.requests_per_minute = requests_per_minute
        self.min_delay = min_delay_ms / 1000
        self.max_delay = max_delay_ms / 1000
        self.base_interval = 60 / requests_per_minute
        self._last_request_time = 0.0
        self._consecutive_fast_requests = 0

    async def wait(self) -> None:
        """Wait appropriate time before next request."""
        now = asyncio.get_event_loop().time()
        elapsed = now - self._last_request_time

        # Calculate required delay
        delay = max(self.min_delay, self.base_interval - elapsed)

        # Add jitter
        jitter = random.uniform(0, delay * 0.3)
        delay += jitter

        # Clamp to max
        delay = min(delay, self.max_delay)

        if delay > 0:
            await asyncio.sleep(delay)

        self._last_request_time = asyncio.get_event_loop().time()

    def adapt_rate(self, success: bool) -> None:
        """Adapt rate based on success/failure."""
        if success:
            # Gradually speed up on success
            self._consecutive_fast_requests += 1
            if self._consecutive_fast_requests > 5:
                self.min_delay = max(0.3, self.min_delay * 0.9)
        else:
            # Slow down on failure
            self._consecutive_fast_requests = 0
            self.min_delay = min(self.max_delay, self.min_delay * 1.5)
