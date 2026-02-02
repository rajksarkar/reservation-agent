"""Tests for platform implementations."""

import pytest

from reservation_agent.platforms.base import BasePlatform, TimeSlot


class TestBasePlatform:
    """Test base platform utilities."""

    def test_time_to_minutes(self):
        # Create a minimal concrete implementation for testing
        class TestPlatform(BasePlatform):
            PLATFORM_NAME = "test"

            async def login(self):
                pass

            async def check_session_valid(self):
                pass

            async def check_availability(self, restaurant, date, party_size):
                pass

            async def book_slot(self, restaurant, slot, party_size, dry_run=False):
                pass

        platform = TestPlatform(session_manager=None, credentials=None)

        assert platform._time_to_minutes("00:00") == 0
        assert platform._time_to_minutes("12:00") == 720
        assert platform._time_to_minutes("19:30") == 1170
        assert platform._time_to_minutes("23:59") == 1439

    def test_matches_preferred_time_empty(self):
        class TestPlatform(BasePlatform):
            PLATFORM_NAME = "test"

            async def login(self):
                pass

            async def check_session_valid(self):
                pass

            async def check_availability(self, restaurant, date, party_size):
                pass

            async def book_slot(self, restaurant, slot, party_size, dry_run=False):
                pass

        platform = TestPlatform(session_manager=None, credentials=None)

        # Empty preferred times should match anything
        assert platform.matches_preferred_time("19:00", []) is True
        assert platform.matches_preferred_time("12:00", []) is True

    def test_matches_preferred_time_range(self):
        class TestPlatform(BasePlatform):
            PLATFORM_NAME = "test"

            async def login(self):
                pass

            async def check_session_valid(self):
                pass

            async def check_availability(self, restaurant, date, party_size):
                pass

            async def book_slot(self, restaurant, slot, party_size, dry_run=False):
                pass

        platform = TestPlatform(session_manager=None, credentials=None)

        preferred = ["19:00-20:00"]

        assert platform.matches_preferred_time("19:00", preferred) is True
        assert platform.matches_preferred_time("19:30", preferred) is True
        assert platform.matches_preferred_time("20:00", preferred) is True
        assert platform.matches_preferred_time("18:59", preferred) is False
        assert platform.matches_preferred_time("20:01", preferred) is False

    def test_matches_preferred_time_exact(self):
        class TestPlatform(BasePlatform):
            PLATFORM_NAME = "test"

            async def login(self):
                pass

            async def check_session_valid(self):
                pass

            async def check_availability(self, restaurant, date, party_size):
                pass

            async def book_slot(self, restaurant, slot, party_size, dry_run=False):
                pass

        platform = TestPlatform(session_manager=None, credentials=None)

        preferred = ["19:00"]

        # Exact match with 30 min tolerance
        assert platform.matches_preferred_time("19:00", preferred) is True
        assert platform.matches_preferred_time("19:15", preferred) is True
        assert platform.matches_preferred_time("18:45", preferred) is True
        assert platform.matches_preferred_time("19:30", preferred) is True
        assert platform.matches_preferred_time("18:30", preferred) is True
        assert platform.matches_preferred_time("18:29", preferred) is False
        assert platform.matches_preferred_time("19:31", preferred) is False

    def test_filter_preferred_slots(self):
        class TestPlatform(BasePlatform):
            PLATFORM_NAME = "test"

            async def login(self):
                pass

            async def check_session_valid(self):
                pass

            async def check_availability(self, restaurant, date, party_size):
                pass

            async def book_slot(self, restaurant, slot, party_size, dry_run=False):
                pass

        platform = TestPlatform(session_manager=None, credentials=None)

        slots = [
            TimeSlot(time="17:00", slot_id="1"),
            TimeSlot(time="18:00", slot_id="2"),
            TimeSlot(time="19:00", slot_id="3"),
            TimeSlot(time="19:30", slot_id="4"),
            TimeSlot(time="20:00", slot_id="5"),
            TimeSlot(time="21:00", slot_id="6"),
        ]

        filtered = platform.filter_preferred_slots(slots, ["19:00-20:00"])

        assert len(filtered) == 3
        times = [s.time for s in filtered]
        assert "19:00" in times
        assert "19:30" in times
        assert "20:00" in times


class TestTimeSlot:
    def test_creation(self):
        slot = TimeSlot(
            time="19:00",
            slot_id="abc123",
            slot_type="dining room",
            deposit_required=50.0,
        )

        assert slot.time == "19:00"
        assert slot.slot_id == "abc123"
        assert slot.slot_type == "dining room"
        assert slot.deposit_required == 50.0

    def test_defaults(self):
        slot = TimeSlot(time="19:00", slot_id="abc")

        assert slot.slot_type is None
        assert slot.deposit_required is None
        assert slot.raw_data is None
