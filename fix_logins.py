"""Re-login to OpenTable (and optionally Resy) with visible browser.

Opens the login pages in visible browsers and waits 90 seconds
for you to manually log in. Then saves the session cookies.

Usage: python fix_logins.py [--resy]
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from reservation_agent.core.config import load_config
from reservation_agent.browser.session_manager import SessionManager


async def fix_logins():
    include_resy = "--resy" in sys.argv

    config = load_config(Path(__file__).parent / "config" / "config.yaml")
    config.browser.headless = False
    config.browser.slow_mo = 50

    session_mgr = SessionManager(config.browser, Path(__file__).parent)
    await session_mgr.start()

    # --- OpenTable (Firefox) ---
    print("\n" + "=" * 60)
    print("Opening OpenTable login page in Firefox...")
    print("Please log in manually within 90 seconds.")
    print("=" * 60)

    ot_context = await session_mgr.get_context("opentable")
    ot_page = await ot_context.new_page()
    ot_page.set_default_timeout(60000)
    try:
        await ot_page.goto("https://www.opentable.com/login", wait_until="domcontentloaded")
    except Exception as e:
        print(f"  Navigation issue (may be redirect): {e}")
        # Try navigating directly
        try:
            await ot_page.goto("https://www.opentable.com", wait_until="domcontentloaded")
        except Exception:
            pass

    # --- Resy (Chromium) ---
    resy_page = None
    if include_resy:
        print("\n" + "=" * 60)
        print("Opening Resy login page in Chromium...")
        print("Please log in manually within 90 seconds.")
        print("=" * 60)

        resy_context = await session_mgr.get_context("resy")
        resy_page = await resy_context.new_page()
        resy_page.set_default_timeout(60000)
        try:
            await resy_page.goto("https://resy.com", wait_until="domcontentloaded")
        except Exception as e:
            print(f"  Navigation issue: {e}")

    # --- Wait for manual login ---
    print("\n>>> Waiting 90 seconds for you to log in manually...")
    print(">>> (Both OpenTable and Resy if --resy was used)")
    for remaining in range(90, 0, -10):
        print(f"    {remaining}s remaining...")
        await asyncio.sleep(10)

    # --- Check and save ---
    print("\nChecking login status...")

    # OpenTable
    try:
        await ot_page.goto("https://www.opentable.com", wait_until="domcontentloaded")
        await asyncio.sleep(3)
        avatar = await ot_page.query_selector('[data-test="user-menu-avatar"]')
        if avatar:
            print("  OpenTable: LOGGED IN - saving session")
            await session_mgr.save_session("opentable")
        else:
            print("  OpenTable: NOT logged in - saving session anyway (may have cookies)")
            await session_mgr.save_session("opentable")
    except Exception as e:
        print(f"  OpenTable check failed: {e}")
        await session_mgr.save_session("opentable")

    # Resy
    if include_resy and resy_page:
        try:
            await resy_page.goto("https://resy.com", wait_until="domcontentloaded")
            await asyncio.sleep(3)
            for sel in ['[data-test-id="menu_container-button-avatar"]', '[data-test-id*="avatar"]']:
                avatar = await resy_page.query_selector(sel)
                if avatar:
                    print("  Resy: LOGGED IN - saving session")
                    await session_mgr.save_session("resy")
                    break
            else:
                print("  Resy: NOT logged in - saving session anyway")
                await session_mgr.save_session("resy")
        except Exception as e:
            print(f"  Resy check failed: {e}")
            await session_mgr.save_session("resy")

    print("\n" + "=" * 60)
    print("Sessions saved. Closing browsers...")
    print("=" * 60)
    await session_mgr.stop()

    # Verify session files
    sessions_dir = Path(__file__).parent / "data" / "sessions"
    for f in sessions_dir.glob("*_session.json"):
        print(f"  Saved: {f.name} ({f.stat().st_size} bytes)")

    print("\nNow restart the daemon with:")
    print("  launchctl load ~/Library/LaunchAgents/com.reservationagent.daemon.plist")


if __name__ == "__main__":
    asyncio.run(fix_logins())
