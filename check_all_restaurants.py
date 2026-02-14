#!/usr/bin/env python
"""Check availability on all target restaurants and book if possible."""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))

from reservation_agent.core.config import load_config
from reservation_agent.browser.session_manager import SessionManager
from reservation_agent.platforms.resy import ResyPlatform
from reservation_agent.platforms.opentable import OpenTablePlatform


async def main():
    config = load_config(Path("config/config.yaml"))
    config.browser.headless = False

    session_manager = SessionManager(config.browser, Path.cwd())
    await session_manager.start()

    try:
        # Initialize platforms
        resy_creds = config.get_credential("resy")
        ot_creds = config.get_credential("opentable")
        resy = ResyPlatform(session_manager, resy_creds)
        opentable = OpenTablePlatform(session_manager, ot_creds)

        platforms = {"resy": resy, "opentable": opentable}

        # Ensure logged in to both
        print("=" * 60)
        print("RESERVATION AGENT - Checking all restaurants")
        print("=" * 60)

        for name, platform in platforms.items():
            print(f"\nLogging in to {name}...")
            if await platform.ensure_logged_in():
                print(f"  {name}: logged in")
            else:
                print(f"  {name}: LOGIN FAILED")

        # Check each restaurant
        for restaurant in config.restaurants:
            if not restaurant.enabled:
                continue

            platform = platforms.get(restaurant.platform)
            if not platform:
                continue

            print(f"\n{'=' * 60}")
            print(f"  {restaurant.name} ({restaurant.platform})")
            print(f"  Party: {restaurant.party_size}")
            print(f"  Preferred times: {', '.join(restaurant.preferred_times)}")
            print(f"{'=' * 60}")

            for date in restaurant.target_dates:
                print(f"\n  Date: {date}")
                try:
                    result = await platform.check_availability(
                        restaurant, date, restaurant.party_size
                    )

                    if not result.available_slots:
                        print(f"    No slots available (may not be released yet)")
                        continue

                    # Filter to preferred times
                    matching = platform.filter_preferred_slots(
                        result.available_slots, restaurant.preferred_times
                    )

                    print(f"    Total slots: {len(result.available_slots)}")
                    print(f"    Matching preferred times: {len(matching)}")

                    if matching:
                        print(f"    MATCHING SLOTS FOUND:")
                        for slot in matching[:10]:
                            print(f"      {slot.time} - {slot.slot_type or 'N/A'}")

                        # Attempt to book the best matching slot
                        # Prefer Dining Room for Resy restaurants
                        chosen = matching[0]
                        for s in matching:
                            if s.slot_type and "dining" in s.slot_type.lower():
                                chosen = s
                                break

                        print(f"\n    >>> BOOKING: {chosen.time} {chosen.slot_type or ''}")
                        booking = await platform.book_slot(
                            restaurant, chosen, restaurant.party_size,
                            dry_run=False, date=date,
                        )

                        if booking.success:
                            print(f"    *** BOOKED! Confirmation: {booking.confirmation_number or 'check app'}")
                            # Don't check other dates for this restaurant
                            break
                        else:
                            print(f"    Booking failed: {booking.error_message}")
                    else:
                        # Show what's available even if not matching
                        sample = result.available_slots[:5]
                        if sample:
                            print(f"    Available (not matching preferred):")
                            for s in sample:
                                print(f"      {s.time} - {s.slot_type or 'N/A'}")

                except Exception as e:
                    print(f"    Error: {e}")

        print(f"\n{'=' * 60}")
        print("Done checking all restaurants.")
        print("=" * 60)

    finally:
        await session_manager.stop()


if __name__ == "__main__":
    asyncio.run(main())
