"""Pytest configuration and fixtures."""

import asyncio
import os
import tempfile
from pathlib import Path

import pytest
import pytest_asyncio
import yaml

from reservation_agent.core.config import AgentConfig, load_config
from reservation_agent.db.models import init_database, get_session_factory
from reservation_agent.db.repository import Repository


@pytest.fixture(scope="session")
def event_loop():
    """Create an instance of the default event loop for the test session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest.fixture
def sample_config_dict():
    """Sample configuration dictionary."""
    return {
        "smtp": {
            "host": "smtp.example.com",
            "port": 587,
            "username": "test@example.com",
            "password": "test_password",
            "to_addresses": ["recipient@example.com"],
        },
        "credentials": [
            {
                "platform": "resy",
                "username": "resy@example.com",
                "password": "resy_pass",
            }
        ],
        "restaurants": [
            {
                "name": "Test Restaurant",
                "platform": "resy",
                "venue_id": "test-restaurant",
                "party_size": 2,
                "target_dates": ["2026-03-15"],
                "preferred_times": ["19:00-20:00"],
                "release_time": "09:00",
                "release_days_ahead": 30,
            }
        ],
        "database_url": "sqlite+aiosqlite:///:memory:",
        "dry_run": True,
    }


@pytest.fixture
def sample_config(sample_config_dict):
    """Sample AgentConfig instance."""
    return AgentConfig(**sample_config_dict)


@pytest.fixture
def config_file(sample_config_dict):
    """Create a temporary config file."""
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", delete=False
    ) as f:
        yaml.dump(sample_config_dict, f)
        f.flush()
        yield f.name
    os.unlink(f.name)


@pytest_asyncio.fixture
async def db_engine():
    """Create an in-memory database engine."""
    engine = await init_database("sqlite+aiosqlite:///:memory:")
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def repository(db_engine):
    """Create a repository with in-memory database."""
    session_factory = get_session_factory(db_engine)
    return Repository(session_factory)


@pytest.fixture
def temp_dir():
    """Create a temporary directory."""
    with tempfile.TemporaryDirectory() as d:
        yield Path(d)
