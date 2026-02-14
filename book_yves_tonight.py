#!/usr/bin/env python
"""Book Yves NYC tonight at 7 PM via Resy."""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from reservation_agent.core.config import load_config, RestaurantConfig
from reservation_agent.browser.session_manager import SessionManager
from reservation_agent.platforms.resy import ResyPlatform


async def main():
    config = load_config(Path("config/config.yaml"))
    config.browser.headless = False

    yves = RestaurantConfig(
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

        print("Ensuring logged in...")
        if not await platform.ensure_logged_in():
            print("ERROR: Could not log in!")
            return
        print("  Logged in.")

        # Check availability
        date = "2026-02-05"
        party_size = 2
        print(f"\nChecking availability at Yves for {date}, party of {party_size}...")
        result = await platform.check_availability(yves, date, party_size)

        if not result.available_slots:
            print("  No slots available!")
            return

        print(f"  Found {len(result.available_slots)} slots.")

        # Find the 7 PM Dining Room slot
        target_slots = [s for s in result.available_slots
                        if s.time == "19:00" and s.slot_type and "Dining" in s.slot_type]
        if not target_slots:
            target_slots = [s for s in result.available_slots if s.time == "19:00"]

        if not target_slots:
            print("  No 7 PM slot found!")
            return

        chosen = target_slots[0]
        print(f"\nBooking: {chosen.time} {chosen.slot_type} (id: {chosen.slot_id[:60]}...)")

        # Book the slot
        booking = await platform.book_slot(yves, chosen, party_size, dry_run=False, date=date)

        if booking.success:
            print(f"\n*** BOOKING SUCCESSFUL! ***")
            print(f"  Confirmation: {booking.confirmation_number or 'check Resy app'}")
            print(f"  Time: {booking.booked_time}")
        else:
            print(f"\n  Booking failed: {booking.error_message}")

    finally:
        await session_manager.stop()


if __name__ == "__main__":
    asyncio.run(main())
