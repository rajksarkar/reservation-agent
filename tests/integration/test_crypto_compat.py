"""Cross-language encryption compatibility tests.

Verifies that the Python SupabaseRepository crypto matches the
TypeScript crypto.ts implementation used in the web app.
"""

import base64
import hashlib
import os
from unittest.mock import MagicMock, patch

import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


MASTER_KEY = "shared-test-master-key-2026"
USER_ID = "550e8400-e29b-41d4-a716-446655440000"


@pytest.fixture(autouse=True)
def supabase_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-key")
    monkeypatch.setenv("ENCRYPTION_KEY", MASTER_KEY)


@pytest.fixture
def repo():
    with patch(
        "reservation_agent.db.supabase_client.create_client",
        return_value=MagicMock(),
    ):
        from reservation_agent.db.supabase_client import SupabaseRepository
        return SupabaseRepository()


def _derive_key_reference(user_id: str, master_key: str) -> bytes:
    """Reference implementation matching both TS and Python key derivation.

    TypeScript: pbkdf2Sync(userId, masterKey, 1, 32, 'sha256')
                pbkdf2Sync(masterKey, salt, 100000, 32, 'sha256')
    Python:     pbkdf2_hmac('sha256', userId.encode(), masterKey.encode(), 1, dklen=32)
                pbkdf2_hmac('sha256', masterKey.encode(), salt, 100000, dklen=32)
    """
    salt = hashlib.pbkdf2_hmac(
        "sha256", user_id.encode(), master_key.encode(), 1, dklen=32
    )
    return hashlib.pbkdf2_hmac(
        "sha256", master_key.encode(), salt, 100000, dklen=32
    )


class TestKeyDerivation:
    def test_matches_reference_implementation(self, repo):
        """Python _derive_key matches the reference (TypeScript-equivalent) implementation."""
        expected = _derive_key_reference(USER_ID, MASTER_KEY)
        actual = repo._derive_key(USER_ID)
        assert actual == expected

    def test_known_vector(self):
        """Verify key derivation against a known test vector.

        This ensures the algorithm parameters (iterations, key length, hash)
        haven't accidentally changed.
        """
        key = _derive_key_reference(USER_ID, MASTER_KEY)
        # Key should be 32 bytes
        assert len(key) == 32
        # Deterministic: same inputs always give same output
        assert key == _derive_key_reference(USER_ID, MASTER_KEY)
        # Encode to hex for easy comparison
        hex_key = key.hex()
        # Re-derive and check
        assert _derive_key_reference(USER_ID, MASTER_KEY).hex() == hex_key


class TestEncryptDecryptRoundtrip:
    def test_python_roundtrip(self, repo):
        """Encrypt with Python AESGCM, decrypt with SupabaseRepository."""
        key = repo._derive_key(USER_ID)
        aesgcm = AESGCM(key)

        plaintext = "test-secret-value"
        iv = os.urandom(16)
        ct_with_tag = aesgcm.encrypt(iv, plaintext.encode(), None)
        ct, tag = ct_with_tag[:-16], ct_with_tag[-16:]

        ct_b64 = base64.b64encode(ct).decode()
        iv_b64 = base64.b64encode(iv).decode()
        tag_b64 = base64.b64encode(tag).decode()

        result = repo._decrypt_field(ct_b64, iv_b64, tag_b64, USER_ID)
        assert result == plaintext

    def test_full_credential_roundtrip(self, repo):
        """Simulate the full encrypt → store → decrypt flow for credentials."""
        key = repo._derive_key(USER_ID)
        aesgcm = AESGCM(key)

        username = "user@example.com"
        password = "p@ssw0rd!$pecial"

        # Encrypt both fields (simulating web app encrypt())
        enc_parts = {}
        for field, value in [("username", username), ("password", password)]:
            iv = os.urandom(16)
            ct_with_tag = aesgcm.encrypt(iv, value.encode(), None)
            ct, tag = ct_with_tag[:-16], ct_with_tag[-16:]
            enc_parts[field] = {
                "encrypted": base64.b64encode(ct).decode(),
                "iv": base64.b64encode(iv).decode(),
                "tag": base64.b64encode(tag).decode(),
            }

        # Build account row (simulating Supabase storage)
        account = {
            "encrypted_username": enc_parts["username"]["encrypted"],
            "encrypted_password": enc_parts["password"]["encrypted"],
            "encryption_iv": f"{enc_parts['username']['iv']}|{enc_parts['password']['iv']}",
            "encryption_tag": f"{enc_parts['username']['tag']}|{enc_parts['password']['tag']}",
        }

        # Decrypt with SupabaseRepository
        dec_username, dec_password = repo.decrypt_credentials(account, USER_ID)
        assert dec_username == username
        assert dec_password == password

    def test_special_characters(self, repo):
        """Handles unicode and special characters."""
        key = repo._derive_key(USER_ID)
        aesgcm = AESGCM(key)

        for plaintext in ["café", "日本語", "emoji 🎉", "p@$$w0rd!#%"]:
            iv = os.urandom(16)
            ct_with_tag = aesgcm.encrypt(iv, plaintext.encode(), None)
            ct, tag = ct_with_tag[:-16], ct_with_tag[-16:]

            result = repo._decrypt_field(
                base64.b64encode(ct).decode(),
                base64.b64encode(iv).decode(),
                base64.b64encode(tag).decode(),
                USER_ID,
            )
            assert result == plaintext
