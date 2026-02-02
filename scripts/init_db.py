#!/usr/bin/env python3
"""Database initialization script."""

import asyncio
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from reservation_agent.core.config import load_config
from reservation_agent.db.models import init_database


async def main():
    """Initialize the database."""
    try:
        config = load_config()
    except FileNotFoundError:
        # Use default database URL if no config
        database_url = "sqlite+aiosqlite:///data/reservation_agent.db"
    else:
        database_url = config.database_url

    # Ensure data directory exists
    Path("data").mkdir(exist_ok=True)

    print(f"Initializing database: {database_url}")
    await init_database(database_url)
    print("Database initialized successfully!")


if __name__ == "__main__":
    asyncio.run(main())
