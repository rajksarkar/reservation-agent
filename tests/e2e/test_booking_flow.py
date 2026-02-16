"""E2E smoke test: full booking flow with mocked platforms.

Verifies: request pickup → availability check → booking → status update.
Uses real MultiUserOrchestrator logic with mocked SupabaseRepository and platforms.
"""

import asyncio
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from reservation_agent.platforms.base import AvailabilityResult, BookingResult, TimeSlot


@pytest.fixture(autouse=True)
def supabase_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-key")
    monkeypatch.setenv("ENCRYPTION_KEY", "test-encryption-key")


def _make_active_request():
    return {
        "id": "req-e2e-1",
        "user_id": "user-e2e-abc",
        "party_size": 2,
        "target_dates": ["2026-04-01"],
        "preferred_times": ["19:00-20:00"],
        "monitor_cancellations": True,
        "release_time": "09:00",
        "release_days_ahead": 14,
        "restaurants": {
            "name": "Le Bernardin",
            "platform": "resy",
            "venue_id": "le-bernardin-ny",
        },
    }


@pytest_asyncio.fixture
async def mock_platform():
    platform = AsyncMock()
    platform.ensure_logged_in = AsyncMock(return_value=True)
    platform.check_availability = AsyncMock(
        return_value=AvailabilityResult(
            available_slots=[
                TimeSlot(time="19:30", slot_id="slot-1"),
                TimeSlot(time="20:30", slot_id="slot-2"),
            ],
            date="2026-04-01",
            party_size=2,
            checked_at=datetime.now(),
        )
    )
    platform.filter_preferred_slots = MagicMock(
        return_value=[TimeSlot(time="19:30", slot_id="slot-1")]
    )
    platform.book_slot = AsyncMock(
        return_value=BookingResult(
            success=True,
            confirmation_number="CONF-E2E-001",
            booked_time="19:30",
        )
    )
    return platform


@pytest_asyncio.fixture
async def mock_repo():
    repo = MagicMock()
    repo.get_active_requests.return_value = [_make_active_request()]
    repo.get_user_platform_account.return_value = {
        "encrypted_username": "enc-u",
        "encrypted_password": "enc-p",
        "encryption_iv": "iv1|iv2",
        "encryption_tag": "tag1|tag2",
    }
    repo.decrypt_credentials.return_value = ("user@test.com", "pass123")
    return repo


@pytest_asyncio.fixture
async def orchestrator(mock_repo, mock_platform, mock_config):
    with patch(
        "reservation_agent.core.multi_user_orchestrator.SupabaseRepository",
        return_value=mock_repo,
    ), patch(
        "reservation_agent.core.multi_user_orchestrator.ResyPlatform",
        return_value=mock_platform,
    ):
        from reservation_agent.core.multi_user_orchestrator import MultiUserOrchestrator

        orch = MultiUserOrchestrator(mock_config, base_dir=Path("/tmp/test"))
    orch.repo = mock_repo
    orch.session_manager = MagicMock()
    orch._running = True
    # Inject mock platform into cache
    orch.PLATFORM_CLASSES = {"resy": MagicMock(return_value=mock_platform)}
    return orch


@pytest.fixture
def mock_config():
    config = MagicMock()
    config.dry_run = False
    config.browser = MagicMock()
    return config


class TestFullBookingFlow:
    @pytest.mark.asyncio
    async def test_end_to_end_happy_path(self, orchestrator, mock_repo, mock_platform):
        """Full flow: poll → check availability → book → update status."""
        await orchestrator._poll_and_process()

        # 1. Fetched active requests
        mock_repo.get_active_requests.assert_called_once()

        # 2. Logged in to platform
        mock_platform.ensure_logged_in.assert_called_once()

        # 3. Checked availability
        mock_platform.check_availability.assert_called_once()

        # 4. Filtered slots
        mock_platform.filter_preferred_slots.assert_called_once()

        # 5. Booked a slot
        mock_platform.book_slot.assert_called_once()

        # 6. Updated request status to "booked"
        mock_repo.update_request_status.assert_called_once()
        status_call = mock_repo.update_request_status.call_args
        assert status_call[1]["status"] == "booked"
        assert status_call[1]["booked_date"] == "2026-04-01"
        assert status_call[1]["booked_time"] == "19:30"
        assert status_call[1]["confirmation_number"] == "CONF-E2E-001"

        # 7. Logged activity
        mock_repo.log_activity.assert_called_once()
        activity_call = mock_repo.log_activity.call_args
        assert activity_call[1]["event_type"] == "booking_success"

        # 8. Logged attempt as success
        success_attempts = [
            c for c in mock_repo.log_attempt.call_args_list
            if c[1].get("result") == "success"
        ]
        assert len(success_attempts) == 1

    @pytest.mark.asyncio
    async def test_no_availability_flow(self, orchestrator, mock_repo, mock_platform):
        """No slots available → logs no_availability, no booking attempted."""
        mock_platform.check_availability = AsyncMock(
            return_value=AvailabilityResult(
                available_slots=[],
                date="2026-04-01",
                party_size=2,
                checked_at=datetime.now(),
            )
        )

        await orchestrator._poll_and_process()

        mock_platform.book_slot.assert_not_called()
        mock_repo.update_request_status.assert_not_called()
        # Should have logged a no_availability attempt
        assert any(
            c[1].get("result") == "no_availability"
            for c in mock_repo.log_attempt.call_args_list
        )

    @pytest.mark.asyncio
    async def test_booking_fails_flow(self, orchestrator, mock_repo, mock_platform):
        """Booking fails → status not updated, attempt logged as slot_taken."""
        mock_platform.book_slot = AsyncMock(
            return_value=BookingResult(
                success=False, error_message="Someone else got it"
            )
        )

        await orchestrator._poll_and_process()

        mock_repo.update_request_status.assert_not_called()
        assert any(
            c[1].get("result") == "slot_taken"
            for c in mock_repo.log_attempt.call_args_list
        )

    @pytest.mark.asyncio
    async def test_multiple_requests_processed(self, orchestrator, mock_repo, mock_platform):
        """Multiple active requests are all processed."""
        req1 = _make_active_request()
        req2 = _make_active_request()
        req2["id"] = "req-e2e-2"
        req2["user_id"] = "user-e2e-def"
        mock_repo.get_active_requests.return_value = [req1, req2]

        await orchestrator._poll_and_process()

        # Both requests should trigger availability checks
        assert mock_platform.check_availability.call_count == 2
