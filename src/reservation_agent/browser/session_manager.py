"""Browser session management with Playwright."""

import asyncio
import json
from pathlib import Path
from typing import Any

from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from reservation_agent.core.config import BrowserConfig
from reservation_agent.core.exceptions import BrowserError, BrowserTimeoutError
from reservation_agent.utils.logging import get_logger

logger = get_logger(__name__)

# OpenTable blocks Chromium; use Firefox for it
PLATFORM_BROWSER: dict[str, str] = {
    "opentable": "firefox",
    "resy": "chromium",
    "tock": "chromium",
}


class SessionManager:
    """Manages persistent browser sessions across restarts."""

    def __init__(self, config: BrowserConfig, base_dir: Path | None = None):
        self.config = config
        self.base_dir = base_dir or Path.cwd()
        self.sessions_dir = self.base_dir / config.sessions_dir
        self.sessions_dir.mkdir(parents=True, exist_ok=True)

        self._playwright = None
        self._browsers: dict[str, Browser] = {}
        self._contexts: dict[str, BrowserContext] = {}
        self._lock = asyncio.Lock()

    async def _get_browser(self, browser_type: str) -> Browser:
        """Get or launch the browser for the given type."""
        if browser_type in self._browsers:
            return self._browsers[browser_type]

        if self._playwright is None:
            self._playwright = await async_playwright().start()

        logger.info(
            "launching_browser", browser=browser_type, headless=self.config.headless
        )

        if browser_type == "firefox":
            self._browsers["firefox"] = await self._playwright.firefox.launch(
                headless=self.config.headless,
                slow_mo=self.config.slow_mo,
            )
        else:
            self._browsers["chromium"] = await self._playwright.chromium.launch(
                headless=self.config.headless,
                slow_mo=self.config.slow_mo,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-dev-shm-usage",
                    "--no-sandbox",
                    "--disable-http2",  # Avoid ERR_HTTP2_PROTOCOL_ERROR
                ],
            )

        return self._browsers[browser_type]

    async def start(self) -> None:
        """Start the default (Chromium) browser for backward compatibility."""
        await self._get_browser("chromium")

    async def stop(self) -> None:
        """Stop all browsers and save all sessions."""
        async with self._lock:
            for platform, context in self._contexts.items():
                await self._save_session(platform, context)
                await context.close()
            self._contexts.clear()

            for browser in self._browsers.values():
                await browser.close()
            self._browsers.clear()

            if self._playwright:
                await self._playwright.stop()
                self._playwright = None

        logger.info("browser_stopped")

    async def get_context(self, platform: str) -> BrowserContext:
        """Get or create a browser context for a platform."""
        async with self._lock:
            if platform in self._contexts:
                return self._contexts[platform]

            return await self._create_fresh_context(platform)

    async def _create_fresh_context(self, platform: str) -> BrowserContext:
        """Create a fresh browser context for a platform (caller must hold _lock).

        If the browser itself has died, the old process is closed before
        launching a replacement to avoid leaking memory.
        """
        browser_type = PLATFORM_BROWSER.get(platform, "chromium")

        try:
            browser = await self._get_browser(browser_type)
            context = await self._create_context(platform, browser)
        except Exception:
            logger.warning("browser_dead_relaunching", browser=browser_type)
            old_browser = self._browsers.pop(browser_type, None)
            if old_browser:
                try:
                    await old_browser.close()
                except Exception:
                    pass
            browser = await self._get_browser(browser_type)
            context = await self._create_context(platform, browser)

        self._contexts[platform] = context
        return context

    async def get_page(self, platform: str) -> Page:
        """Get a new page in the platform's context.

        If context.new_page() fails (stale/dead context), the cached context
        is discarded and a fresh one is created before retrying.
        """
        context = await self.get_context(platform)
        try:
            page = await context.new_page()
        except Exception:
            logger.warning("stale_context_detected_on_new_page", platform=platform)
            async with self._lock:
                old_ctx = self._contexts.pop(platform, None)
                if old_ctx:
                    try:
                        await old_ctx.close()
                    except Exception:
                        pass
                context = await self._create_fresh_context(platform)
            page = await context.new_page()
        page.set_default_timeout(self.config.timeout)
        return page

    async def _create_context(self, platform: str, browser: Browser) -> BrowserContext:
        """Create a new browser context, loading saved session if available."""
        session_file = self._get_session_file(platform)
        storage_state = None

        if session_file.exists():
            try:
                storage_state = json.loads(session_file.read_text())
                logger.info("loaded_session", platform=platform)
            except Exception as e:
                logger.warning("failed_to_load_session", platform=platform, error=str(e))

        # User agent: Firefox for OpenTable, Chrome for others
        is_firefox = platform == "opentable"
        user_agent = (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:131.0) "
            "Gecko/20100101 Firefox/131.0"
            if is_firefox
            else "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

        context = await browser.new_context(
            storage_state=storage_state,
            viewport={"width": 1920, "height": 1080},
            user_agent=user_agent,
            locale="en-US",
            timezone_id="America/New_York",
            permissions=["geolocation"],
            geolocation={"latitude": 40.7128, "longitude": -74.0060},  # NYC
            color_scheme="light",
        )

        # Stealth: hide webdriver (Chrome-specific scripts skip for Firefox)
        if not is_firefox:
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
                window.chrome = { runtime: {} };
            """)

        return context

    async def _save_session(self, platform: str, context: BrowserContext) -> None:
        """Save browser context storage state."""
        session_file = self._get_session_file(platform)
        try:
            storage_state = await context.storage_state()
            session_file.write_text(json.dumps(storage_state, indent=2))
            logger.info("saved_session", platform=platform)
        except Exception as e:
            logger.error("failed_to_save_session", platform=platform, error=str(e))

    async def save_session(self, platform: str) -> None:
        """Manually save a platform's session."""
        async with self._lock:
            if platform in self._contexts:
                await self._save_session(platform, self._contexts[platform])

    def _get_session_file(self, platform: str) -> Path:
        """Get the session file path for a platform."""
        return self.sessions_dir / f"{platform}_session.json"

    def has_recent_session(self, platform: str, max_age_hours: int = 48) -> bool:
        """Check if a valid session file exists and was saved recently."""
        import time

        session_file = self._get_session_file(platform)
        if not session_file.exists():
            return False
        age_seconds = time.time() - session_file.stat().st_mtime
        return age_seconds < max_age_hours * 3600

    async def reset_context(self, platform: str) -> None:
        """Close and discard the current browser context without removing the session file.

        Use this when the context has crashed mid-operation.  The next call to
        get_page() will create a fresh context and reload cookies from the
        existing session file.
        """
        async with self._lock:
            old_ctx = self._contexts.pop(platform, None)
            if old_ctx:
                try:
                    await old_ctx.close()
                except Exception:
                    pass
        logger.info("reset_context", platform=platform)

    async def clear_session(self, platform: str) -> None:
        """Clear saved session for a platform."""
        async with self._lock:
            session_file = self._get_session_file(platform)
            if session_file.exists():
                session_file.unlink()
                logger.info("cleared_session", platform=platform)

            if platform in self._contexts:
                await self._contexts[platform].close()
                del self._contexts[platform]


class PageHelper:
    """Helper methods for common page operations."""

    def __init__(self, page: Page):
        self.page = page
        self.logger = get_logger(__name__)

    async def wait_and_click(
        self, selector: str, timeout: int | None = None, wait_after: int = 500
    ) -> None:
        """Wait for element and click it."""
        try:
            element = await self.page.wait_for_selector(selector, timeout=timeout)
            if element:
                await element.click()
                await asyncio.sleep(wait_after / 1000)
        except Exception as e:
            raise BrowserTimeoutError(f"Timeout waiting for {selector}: {e}")

    async def wait_and_fill(
        self, selector: str, value: str, timeout: int | None = None, clear_first: bool = True
    ) -> None:
        """Wait for input and fill it."""
        try:
            element = await self.page.wait_for_selector(selector, timeout=timeout)
            if element:
                if clear_first:
                    await element.fill("")
                await element.fill(value)
        except Exception as e:
            raise BrowserTimeoutError(f"Timeout waiting for {selector}: {e}")

    async def safe_click(self, selector: str) -> bool:
        """Click if element exists, return whether click happened."""
        try:
            element = await self.page.query_selector(selector)
            if element:
                await element.click()
                return True
        except Exception:
            pass
        return False

    async def get_text(self, selector: str) -> str | None:
        """Get text content of an element."""
        try:
            element = await self.page.query_selector(selector)
            if element:
                return await element.text_content()
        except Exception:
            pass
        return None

    async def wait_for_navigation(self, url_pattern: str, timeout: int = 30000) -> None:
        """Wait for navigation to a URL matching pattern."""
        try:
            await self.page.wait_for_url(url_pattern, timeout=timeout)
        except Exception as e:
            raise BrowserTimeoutError(f"Navigation timeout for {url_pattern}: {e}")

    async def random_delay(self, min_ms: int = 500, max_ms: int = 2000) -> None:
        """Add a random human-like delay."""
        import random

        delay = random.randint(min_ms, max_ms) / 1000
        await asyncio.sleep(delay)
