"""Tests for MultiUserOrchestrator."""

import asyncio
from datetime import datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from reservation_agent.core.exceptions import AuthenticationError, SlotUnavailableError
from reservation_agent.platforms.base import AvailabilityResult, BookingResult, TimeSlot


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def supabase_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-key")
    monkeypatch.setenv("ENCRYPTION_KEY", "test-encryption-key")


@pytest.fixture
def mock_repo():
    repo = MagicMock()
    repo.get_active_requests.return_value = []
    repo.get_user_platform_account.return_value = None
    repo.decrypt_credentials.return_value = ("user@test.com", "pass123")
    return repo


@pytest.fixture
def mock_config():
    config = MagicMock()
    config.dry_run = False
    config.browser = MagicMock()
    return config


@pytest_asyncio.fixture
async def orchestrator(mock_repo, mock_config):
    with patch(
        "reservation_agent.core.multi_user_orchestrator.SupabaseRepository",
        return_value=mock_repo,
    ):
        from reservation_agent.core.multi_user_orchestrator import MultiUserOrchestrator

        orch = MultiUserOrchestrator(mock_config, base_dir=Path("/tmp/test"))
    orch.repo = mock_repo
    orch.session_manager = MagicMock()
    orch._running = True
    return orch


def _make_request(
    request_id="req-1",
    user_id="user-1",
    platform="resy",
    restaurant_name="Test Restaurant",
    venue_id="test-venue",
    party_size=2,
    target_dates=None,
    preferred_times=None,
):
    return {
        "id": request_id,
        "user_id": user_id,
        "party_size": party_size,
        "target_dates": target_dates or ["2026-03-15"],
        "preferred_times": preferred_times or ["19:00-20:00"],
        "monitor_cancellations": True,
        "release_time": "09:00",
        "release_days_ahead": 14,
        "restaurants": {
            "name": restaurant_name,
            "platform": platform,
            "venue_id": venue_id,
        },
    }


# ---------------------------------------------------------------------------
# _poll_and_process
# ---------------------------------------------------------------------------


class TestPollAndProcess:
    @pytest.mark.asyncio
    async def test_no_requests_is_noop(self, orchestrator, mock_repo):
        mock_repo.get_active_requests.return_value = []
        await orchestrator._poll_and_process()
        mock_repo.get_active_requests.assert_called_once()

    @pytest.mark.asyncio
    async def test_processes_active_requests(self, orchestrator, mock_repo):
        req = _make_request()
        mock_repo.get_active_requests.return_value = [req]

        with patch.object(orchestrator, "_process_request", new_callable=AsyncMock) as mock_pr:
            await orchestrator._poll_and_process()
            mock_pr.assert_called_once_with(req)

    @pytest.mark.asyncio
    async def test_respects_concurrency_semaphore(self, orchestrator, mock_repo):
        """Three requests should all be processed (semaphore=3)."""
        reqs = [_make_request(request_id=f"req-{i}") for i in range(3)]
        mock_repo.get_active_requests.return_value = reqs

        with patch.object(orchestrator, "_process_request", new_callable=AsyncMock) as mock_pr:
            await orchestrator._poll_and_process()
            assert mock_pr.call_count == 3


# ---------------------------------------------------------------------------
# _process_request
# ---------------------------------------------------------------------------


class TestProcessRequest:
    @pytest.mark.asyncio
    async def test_no_platform_returns_early(self, orchestrator):
        """Missing platform credentials → log warning and return."""
        with patch.object(orchestrator, "_get_platform", new_callable=AsyncMock, return_value=None):
            req = _make_request()
            await orchestrator._process_request(req)
            # Should not raise; just returns

    @pytest.mark.asyncio
    async def test_login_failure_logs_attempt(self, orchestrator, mock_repo):
        platform = AsyncMock()
        platform.ensure_logged_in = AsyncMock(return_value=False)

        with patch.object(orchestrator, "_get_platform", new_callable=AsyncMock, return_value=platform):
            await orchestrator._process_request(_make_request())

        mock_repo.log_attempt.assert_called_once()
        assert mock_repo.log_attempt.call_args[1]["result"] == "auth_failed"

    @pytest.mark.asyncio
    async def test_auth_error_logs_attempt(self, orchestrator, mock_repo):
        platform = AsyncMock()
        platform.ensure_logged_in = AsyncMock(side_effect=AuthenticationError("resy", "bad creds"))

        with patch.object(orchestrator, "_get_platform", new_callable=AsyncMock, return_value=platform):
            await orchestrator._process_request(_make_request())

        mock_repo.log_attempt.assert_called_once()
        assert mock_repo.log_attempt.call_args[1]["result"] == "auth_failed"

    @pytest.mark.asyncio
    async def test_checks_availability_and_books(self, orchestrator, mock_repo):
        slot = TimeSlot(time="19:30", slot_id="s1")
        avail = AvailabilityResult(
            available_slots=[slot],
            date="2026-03-15",
            party_size=2,
            checked_at=datetime.now(),
        )

        platform = AsyncMock()
        platform.ensure_logged_in = AsyncMock(return_value=True)
        platform.check_availability = AsyncMock(return_value=avail)
        platform.filter_preferred_slots = MagicMock(return_value=[slot])

        with (
            patch.object(orchestrator, "_get_platform", new_callable=AsyncMock, return_value=platform),
            patch.object(orchestrator, "_try_book", new_callable=AsyncMock, return_value=True) as mock_book,
        ):
            await orchestrator._process_request(_make_request())
            mock_book.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_matching_slots_logs_no_availability(self, orchestrator, mock_repo):
        avail = AvailabilityResult(
            available_slots=[TimeSlot(time="22:00", slot_id="s1")],
            date="2026-03-15",
            party_size=2,
            checked_at=datetime.now(),
        )

        platform = AsyncMock()
        platform.ensure_logged_in = AsyncMock(return_value=True)
        platform.check_availability = AsyncMock(return_value=avail)
        platform.filter_preferred_slots = MagicMock(return_value=[])

        with patch.object(orchestrator, "_get_platform", new_callable=AsyncMock, return_value=platform):
            await orchestrator._process_request(_make_request())

        # At least one log_attempt call for no_availability
        assert any(
            call[1].get("result") == "no_availability"
            for call in mock_repo.log_attempt.call_args_list
        )


# ---------------------------------------------------------------------------
# _try_book
# ---------------------------------------------------------------------------


class TestTryBook:
    @pytest.mark.asyncio
    async def test_returns_true_on_first_success(self, orchestrator, mock_repo):
        platform = AsyncMock()
        platform.book_slot = AsyncMock(
            return_value=BookingResult(
                success=True,
                confirmation_number="CONF1",
                booked_time="19:30",
            )
        )

        from reservation_agent.core.config import RestaurantConfig

        restaurant_config = RestaurantConfig(
            name="Test", platform="resy", venue_id="v1",
            party_size=2, target_dates=["2026-03-15"],
            preferred_times=["19:00-20:00"],
        )
        slots = [TimeSlot(time="19:30", slot_id="s1"), TimeSlot(time="19:45", slot_id="s2")]

        result = await orchestrator._try_book(
            "req-1", "user-1", platform, restaurant_config,
            slots, 2, "2026-03-15", datetime.now(),
        )

        assert result is True
        # Should only try first slot since it succeeded
        assert platform.book_slot.call_count == 1
        mock_repo.update_request_status.assert_called_once()
        mock_repo.log_activity.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_false_when_all_fail(self, orchestrator, mock_repo):
        platform = AsyncMock()
        platform.book_slot = AsyncMock(
            return_value=BookingResult(success=False, error_message="slot taken")
        )

        from reservation_agent.core.config import RestaurantConfig

        restaurant_config = RestaurantConfig(
            name="Test", platform="resy", venue_id="v1",
            party_size=2, target_dates=["2026-03-15"],
            preferred_times=["19:00-20:00"],
        )
        slots = [TimeSlot(time="19:30", slot_id="s1")]

        result = await orchestrator._try_book(
            "req-1", "user-1", platform, restaurant_config,
            slots, 2, "2026-03-15", datetime.now(),
        )

        assert result is False
        mock_repo.log_attempt.assert_called()
        assert mock_repo.log_attempt.call_args[1]["result"] == "slot_taken"

    @pytest.mark.asyncio
    async def test_continues_on_slot_unavailable(self, orchestrator, mock_repo):
        platform = AsyncMock()
        platform.book_slot = AsyncMock(
            side_effect=[
                SlotUnavailableError("resy", "gone"),
                BookingResult(success=True, confirmation_number="C2", booked_time="19:45"),
            ]
        )

        from reservation_agent.core.config import RestaurantConfig

        restaurant_config = RestaurantConfig(
            name="Test", platform="resy", venue_id="v1",
            party_size=2, target_dates=["2026-03-15"],
            preferred_times=["19:00-20:00"],
        )
        slots = [TimeSlot(time="19:30", slot_id="s1"), TimeSlot(time="19:45", slot_id="s2")]

        result = await orchestrator._try_book(
            "req-1", "user-1", platform, restaurant_config,
            slots, 2, "2026-03-15", datetime.now(),
        )

        assert result is True
        assert platform.book_slot.call_count == 2


# ---------------------------------------------------------------------------
# _get_platform
# ---------------------------------------------------------------------------


class TestGetPlatform:
    @pytest.mark.asyncio
    async def test_creates_and_caches(self, orchestrator, mock_repo):
        mock_repo.get_user_platform_account.return_value = {
            "encrypted_username": "enc-u",
            "encrypted_password": "enc-p",
            "encryption_iv": "iv1|iv2",
            "encryption_tag": "tag1|tag2",
        }

        with patch(
            "reservation_agent.core.multi_user_orchestrator.ResyPlatform"
        ) as MockResy:
            mock_instance = MagicMock()
            MockResy.return_value = mock_instance

            # Monkeypatch PLATFORM_CLASSES on the class
            orchestrator.PLATFORM_CLASSES = {"resy": MockResy}

            result = await orchestrator._get_platform("user-1", "resy")
            assert result is mock_instance

            # Second call should return cached
            result2 = await orchestrator._get_platform("user-1", "resy")
            assert result2 is mock_instance
            assert MockResy.call_count == 1  # Only created once

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_platform(self, orchestrator):
        result = await orchestrator._get_platform("user-1", "unknown_platform")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_account(self, orchestrator, mock_repo):
        mock_repo.get_user_platform_account.return_value = None
        result = await orchestrator._get_platform("user-1", "resy")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_decryption_error(self, orchestrator, mock_repo):
        mock_repo.get_user_platform_account.return_value = {"some": "data"}
        mock_repo.decrypt_credentials.side_effect = Exception("decrypt failed")

        result = await orchestrator._get_platform("user-1", "resy")
        assert result is None


# ---------------------------------------------------------------------------
# start / stop lifecycle
# ---------------------------------------------------------------------------


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start_initializes(self, orchestrator, mock_config):
        orchestrator.session_manager = None
        with patch(
            "reservation_agent.core.multi_user_orchestrator.SessionManager"
        ) as MockSM:
            mock_sm = AsyncMock()
            MockSM.return_value = mock_sm
            await orchestrator.start()
            mock_sm.start.assert_called_once()
            assert orchestrator._running is True

    @pytest.mark.asyncio
    async def test_stop_shuts_down(self, orchestrator):
        mock_sm = AsyncMock()
        orchestrator.session_manager = mock_sm
        orchestrator._running = True
        await orchestrator.stop()
        assert orchestrator._running is False
        mock_sm.stop.assert_called_once()
