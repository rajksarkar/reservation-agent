#!/usr/bin/env python
"""Quick test: check Musaafer availability with the fixed code."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from reservation_agent.core.config import load_config, RestaurantConfig
from reservation_agent.browser.session_manager import SessionManager
from reservation_agent.platforms.opentable import OpenTablePlatform


async def main():
    config = load_config(Path("config/config.yaml"))
    config.browser.headless = False

    musaafer = RestaurantConfig(
        name="Musaafer", platform="opentable",
        venue_id="musaafer-new-york-new-york-city", party_size=2,
        target_dates=["2026-02-28"], preferred_times=["19:00-20:00"],
        release_time="00:01", release_days_ahead=14,
        monitor_cancellations=True, enabled=True,
    )

    session_manager = SessionManager(config.browser, Path.cwd())
    await session_manager.start()

    try:
        credentials = config.get_credential("opentable")
        platform = OpenTablePlatform(session_manager, credentials)

        print("Ensuring logged in to OpenTable...")
        if not await platform.ensure_logged_in():
            print("ERROR: Could not log in!")
            return
        print("  Logged in.")

        for date in ["2026-02-28", "2026-03-01"]:
            print(f"\nChecking Musaafer for {date}...")
            result = await platform.check_availability(musaafer, date, 2)
            print(f"  Slots found: {len(result.available_slots)}")
            for s in result.available_slots[:5]:
                print(f"    {s.time} - {s.slot_type or 'N/A'} (id: {s.slot_id})")

    finally:
        await session_manager.stop()


if __name__ == "__main__":
    asyncio.run(main())
