"""Supabase repository for multi-user web worker mode."""

import os
import base64
import hashlib
from datetime import datetime
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from supabase import create_client, Client

from reservation_agent.utils.logging import get_logger

logger = get_logger(__name__)


class SupabaseRepository:
    """Repository for interacting with Supabase in multi-user worker mode."""

    def __init__(self):
        url = os.environ["SUPABASE_URL"]
        key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
        self.client: Client = create_client(url, key)
        self._encryption_key = os.environ["ENCRYPTION_KEY"]

    def _derive_key(self, user_id: str) -> bytes:
        """Derive a user-specific AES-256 key matching the Next.js implementation."""
        master = self._encryption_key.encode()
        salt = hashlib.pbkdf2_hmac("sha256", user_id.encode(), master, 1, dklen=32)
        return hashlib.pbkdf2_hmac("sha256", master, salt, 100000, dklen=32)

    def _decrypt_field(self, encrypted_b64: str, iv_b64: str, tag_b64: str, user_id: str) -> str:
        """Decrypt a single field using AES-256-GCM."""
        key = self._derive_key(user_id)
        aesgcm = AESGCM(key)
        iv = base64.b64decode(iv_b64)
        ciphertext = base64.b64decode(encrypted_b64)
        tag = base64.b64decode(tag_b64)
        # GCM: ciphertext + tag concatenated
        plaintext = aesgcm.decrypt(iv, ciphertext + tag, None)
        return plaintext.decode("utf-8")

    def decrypt_credentials(self, account: dict, user_id: str) -> tuple[str, str]:
        """Decrypt username and password from a platform_accounts record."""
        iv_parts = account["encryption_iv"].split("|")
        tag_parts = account["encryption_tag"].split("|")

        username = self._decrypt_field(
            account["encrypted_username"], iv_parts[0], tag_parts[0], user_id
        )
        password = self._decrypt_field(
            account["encrypted_password"], iv_parts[1], tag_parts[1], user_id
        )
        return username, password

    def get_active_requests(self) -> list[dict[str, Any]]:
        """Fetch all active reservation requests with restaurant info."""
        result = (
            self.client.table("reservation_requests")
            .select("*, restaurants(*)")
            .eq("status", "active")
            .execute()
        )
        return result.data or []

    def get_user_platform_account(self, user_id: str, platform: str) -> dict | None:
        """Fetch encrypted credentials for a user+platform."""
        result = (
            self.client.table("platform_accounts")
            .select("*")
            .eq("user_id", user_id)
            .eq("platform", platform)
            .eq("is_connected", True)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None

    def update_request_status(
        self,
        request_id: str,
        status: str,
        booked_date: str | None = None,
        booked_time: str | None = None,
        confirmation_number: str | None = None,
    ) -> None:
        """Update a reservation request's status."""
        updates: dict[str, Any] = {"status": status}
        if booked_date:
            updates["booked_date"] = booked_date
        if booked_time:
            updates["booked_time"] = booked_time
        if confirmation_number:
            updates["confirmation_number"] = confirmation_number

        self.client.table("reservation_requests").update(updates).eq("id", request_id).execute()
        logger.info("updated_request_status", request_id=request_id, status=status)

    def log_attempt(
        self,
        request_id: str,
        attempt_type: str,
        result: str,
        slot_time: str | None = None,
        error_message: str | None = None,
        duration_ms: int | None = None,
    ) -> None:
        """Log a booking attempt."""
        self.client.table("booking_attempts").insert({
            "request_id": request_id,
            "attempt_type": attempt_type,
            "result": result,
            "slot_time": slot_time,
            "error_message": error_message,
            "duration_ms": duration_ms,
        }).execute()

    def log_activity(
        self,
        user_id: str,
        event_type: str,
        title: str,
        description: str | None = None,
        request_id: str | None = None,
    ) -> None:
        """Add an entry to the user's activity log."""
        entry: dict[str, Any] = {
            "user_id": user_id,
            "event_type": event_type,
            "title": title,
        }
        if description:
            entry["description"] = description
        if request_id:
            entry["request_id"] = request_id

        self.client.table("activity_log").insert(entry).execute()

    def update_session_data(self, user_id: str, platform: str, session_data: dict) -> None:
        """Store browser session data (cookies/localStorage) for a platform account."""
        self.client.table("platform_accounts").update(
            {"session_data": session_data}
        ).eq("user_id", user_id).eq("platform", platform).execute()
        logger.info("updated_session_data", platform=platform, user=user_id[:8])
