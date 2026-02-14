#!/usr/bin/env python
"""Debug Resy modal after slot click."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from reservation_agent.core.config import load_config, RestaurantConfig
from reservation_agent.browser.session_manager import SessionManager
from reservation_agent.platforms.resy import ResyPlatform


async def main():
    config = load_config(Path("config/config.yaml"))

    yves_config = RestaurantConfig(
        name="Yves", platform="resy", venue_id="yves", party_size=2,
        target_dates=["2026-02-05"], preferred_times=["19:00-19:30"],
        release_time="09:00", release_days_ahead=30,
        monitor_cancellations=False, enabled=True,
    )

    session_manager = SessionManager(config.browser, Path.cwd())
    await session_manager.start()

    try:
        credentials = config.get_credential("resy")
        platform = ResyPlatform(session_manager, credentials)

        if not await platform.ensure_logged_in():
            return

        page = await platform.get_page()
        url = "https://resy.com/cities/ny/yves?date=2026-02-05&seats=2"
        await page.goto(url, wait_until="domcontentloaded", timeout=30000)
        await asyncio.sleep(5)

        # Click the 7 PM Dining Room slot
        print("Clicking 7 PM Dining Room slot...")
        btn = await page.query_selector('button[data-testid="reservation-button-rgs://resy/785/856734/2/2026-02-05/2026-02-05/19:00:00/2/Dining Room"]')
        if btn:
            await btn.click()
            print("  Clicked!")
        else:
            print("  Button not found!")
            return

        # Wait longer for modal
        await asyncio.sleep(5)

        # Take screenshot
        await page.screenshot(path="data/yves_resy_modal.png", full_page=False)
        print("Screenshot saved")

        # Check for iframes
        frames = page.frames
        print(f"\nFrames: {len(frames)}")
        for i, frame in enumerate(frames):
            print(f"  [{i}] {frame.url}")

        # Search ALL elements for "Reserve" (not just buttons)
        print("\n--- ALL elements with 'Reserve Now' ---")
        result = await page.evaluate("""() => {
            const results = [];
            const walk = (node) => {
                if (node.nodeType === 3 && node.textContent.includes('Reserve')) {
                    let parent = node.parentElement;
                    results.push({
                        tag: parent.tagName,
                        text: parent.textContent.trim().substring(0, 60),
                        class: parent.className.substring(0, 80),
                        html: parent.outerHTML.substring(0, 300)
                    });
                }
                for (let child of node.childNodes) walk(child);
            };
            walk(document.body);
            return results;
        }""")
        for r in result:
            print(f"  <{r['tag']}> class='{r['class']}' text='{r['text']}'")
            print(f"    html={r['html'][:200]}")

    finally:
        await session_manager.stop()


if __name__ == "__main__":
    asyncio.run(main())
