"""Tests for SupabaseRepository."""

import base64
import os
from unittest.mock import MagicMock, patch

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


@pytest.fixture(autouse=True)
def supabase_env(monkeypatch):
    """Set required environment variables."""
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-service-role-key")
    monkeypatch.setenv("ENCRYPTION_KEY", "test-master-key-for-encryption")


@pytest.fixture
def mock_supabase_client():
    """Create a mock Supabase client."""
    client = MagicMock()
    return client


@pytest.fixture
def repo(mock_supabase_client):
    """Create a SupabaseRepository with a mocked client."""
    with patch(
        "reservation_agent.db.supabase_client.create_client",
        return_value=mock_supabase_client,
    ):
        from reservation_agent.db.supabase_client import SupabaseRepository

        r = SupabaseRepository()
    r.client = mock_supabase_client
    return r


class TestDeriveKey:
    def test_deterministic(self, repo):
        """Same user_id always produces the same key."""
        k1 = repo._derive_key("user-123")
        k2 = repo._derive_key("user-123")
        assert k1 == k2

    def test_different_users_different_keys(self, repo):
        """Different user_ids produce different keys."""
        k1 = repo._derive_key("user-a")
        k2 = repo._derive_key("user-b")
        assert k1 != k2

    def test_key_length(self, repo):
        """Key is 32 bytes (AES-256)."""
        key = repo._derive_key("user-123")
        assert len(key) == 32


class TestDecryptField:
    def _encrypt(self, plaintext: str, key: bytes) -> tuple[str, str, str]:
        """Helper: encrypt a value and return (ciphertext_b64, iv_b64, tag_b64)."""
        aesgcm = AESGCM(key)
        iv = os.urandom(16)
        ct_with_tag = aesgcm.encrypt(iv, plaintext.encode(), None)
        # AESGCM appends 16-byte tag
        ct = ct_with_tag[:-16]
        tag = ct_with_tag[-16:]
        return (
            base64.b64encode(ct).decode(),
            base64.b64encode(iv).decode(),
            base64.b64encode(tag).decode(),
        )

    def test_roundtrip(self, repo):
        """Encrypt then decrypt returns original plaintext."""
        user_id = "user-roundtrip"
        key = repo._derive_key(user_id)
        ct_b64, iv_b64, tag_b64 = self._encrypt("hello-world", key)
        result = repo._decrypt_field(ct_b64, iv_b64, tag_b64, user_id)
        assert result == "hello-world"

    def test_wrong_key_fails(self, repo):
        """Decrypting with the wrong user_id fails."""
        key = repo._derive_key("user-a")
        ct_b64, iv_b64, tag_b64 = self._encrypt("secret", key)
        with pytest.raises(Exception):
            repo._decrypt_field(ct_b64, iv_b64, tag_b64, "user-b")


class TestDecryptCredentials:
    def test_splits_pipe_delimited_iv_and_tag(self, repo):
        """Verifies pipe-delimited IV/tag are correctly split for username and password."""
        user_id = "user-creds"
        key = repo._derive_key(user_id)
        aesgcm = AESGCM(key)

        results = {}
        for field in ("username", "password"):
            iv = os.urandom(16)
            ct_tag = aesgcm.encrypt(iv, f"test-{field}".encode(), None)
            ct, tag = ct_tag[:-16], ct_tag[-16:]
            results[field] = {
                "encrypted": base64.b64encode(ct).decode(),
                "iv": base64.b64encode(iv).decode(),
                "tag": base64.b64encode(tag).decode(),
            }

        account = {
            "encrypted_username": results["username"]["encrypted"],
            "encrypted_password": results["password"]["encrypted"],
            "encryption_iv": f"{results['username']['iv']}|{results['password']['iv']}",
            "encryption_tag": f"{results['username']['tag']}|{results['password']['tag']}",
        }

        username, password = repo.decrypt_credentials(account, user_id)
        assert username == "test-username"
        assert password == "test-password"


class TestGetActiveRequests:
    def test_returns_data(self, repo, mock_supabase_client):
        mock_result = MagicMock()
        mock_result.data = [{"id": "r1", "status": "active"}]
        (
            mock_supabase_client.table.return_value
            .select.return_value
            .eq.return_value
            .execute.return_value
        ) = mock_result

        result = repo.get_active_requests()
        assert result == [{"id": "r1", "status": "active"}]
        mock_supabase_client.table.assert_called_with("reservation_requests")

    def test_returns_empty_list_when_no_data(self, repo, mock_supabase_client):
        mock_result = MagicMock()
        mock_result.data = None
        (
            mock_supabase_client.table.return_value
            .select.return_value
            .eq.return_value
            .execute.return_value
        ) = mock_result

        result = repo.get_active_requests()
        assert result == []


class TestGetUserPlatformAccount:
    def test_found(self, repo, mock_supabase_client):
        mock_result = MagicMock()
        mock_result.data = [{"id": "acct-1", "platform": "resy"}]
        (
            mock_supabase_client.table.return_value
            .select.return_value
            .eq.return_value
            .eq.return_value
            .eq.return_value
            .limit.return_value
            .execute.return_value
        ) = mock_result

        result = repo.get_user_platform_account("user-1", "resy")
        assert result == {"id": "acct-1", "platform": "resy"}

    def test_not_found(self, repo, mock_supabase_client):
        mock_result = MagicMock()
        mock_result.data = []
        (
            mock_supabase_client.table.return_value
            .select.return_value
            .eq.return_value
            .eq.return_value
            .eq.return_value
            .limit.return_value
            .execute.return_value
        ) = mock_result

        result = repo.get_user_platform_account("user-1", "resy")
        assert result is None


class TestUpdateRequestStatus:
    def test_basic_update(self, repo, mock_supabase_client):
        repo.update_request_status("req-1", "booked")
        mock_supabase_client.table.assert_called_with("reservation_requests")

    def test_with_booking_details(self, repo, mock_supabase_client):
        repo.update_request_status(
            "req-1", "booked",
            booked_date="2026-03-01",
            booked_time="19:00",
            confirmation_number="CONF123",
        )
        mock_supabase_client.table.assert_called_with("reservation_requests")


class TestLogAttempt:
    def test_insert_payload(self, repo, mock_supabase_client):
        repo.log_attempt(
            request_id="req-1",
            attempt_type="cancellation_check",
            result="no_availability",
            slot_time="19:00",
            error_message=None,
            duration_ms=1500,
        )
        mock_supabase_client.table.assert_called_with("booking_attempts")
        call_args = (
            mock_supabase_client.table.return_value
            .insert.call_args[0][0]
        )
        assert call_args["request_id"] == "req-1"
        assert call_args["attempt_type"] == "cancellation_check"
        assert call_args["result"] == "no_availability"
        assert call_args["duration_ms"] == 1500


class TestLogActivity:
    def test_insert_payload(self, repo, mock_supabase_client):
        repo.log_activity(
            user_id="user-1",
            event_type="booking_success",
            title="Booked Test Restaurant!",
            description="2026-03-01 at 19:00",
            request_id="req-1",
        )
        mock_supabase_client.table.assert_called_with("activity_log")
        call_args = (
            mock_supabase_client.table.return_value
            .insert.call_args[0][0]
        )
        assert call_args["user_id"] == "user-1"
        assert call_args["event_type"] == "booking_success"
        assert call_args["request_id"] == "req-1"

    def test_minimal_payload(self, repo, mock_supabase_client):
        repo.log_activity(
            user_id="user-1",
            event_type="info",
            title="Something happened",
        )
        call_args = (
            mock_supabase_client.table.return_value
            .insert.call_args[0][0]
        )
        assert "description" not in call_args
        assert "request_id" not in call_args
