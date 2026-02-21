"""Pytest configuration and shared fixtures."""

import sys
from unittest.mock import MagicMock

# Mock the supabase module before any application imports that depend on it.
# The real `supabase` Python SDK may not be installed in the test environment.
if "supabase" not in sys.modules or not hasattr(sys.modules["supabase"], "create_client"):
    _mock_supabase = MagicMock()
    _mock_supabase.create_client = MagicMock()
    _mock_supabase.Client = MagicMock
    sys.modules["supabase"] = _mock_supabase
