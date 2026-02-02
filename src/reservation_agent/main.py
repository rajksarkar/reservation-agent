"""Bootstrap module for the reservation agent."""

import asyncio
import signal
from pathlib import Path

from reservation_agent.core.config import load_config
from reservation_agent.core.orchestrator import Orchestrator
from reservation_agent.utils.logging import setup_logging, get_logger

logger = get_logger(__name__)


async def run_agent(config_path: str | Path | None = None, dry_run: bool = False) -> None:
    """Run the reservation agent.

    Args:
        config_path: Path to configuration file
        dry_run: If True, don't make actual bookings
    """
    # Load configuration
    config = load_config(config_path)
    if dry_run:
        config.dry_run = True

    # Set up logging
    setup_logging(config.log_level, config.log_dir)

    logger.info(
        "starting_agent",
        dry_run=config.dry_run,
        restaurants=len(config.restaurants),
    )

    # Create and start orchestrator
    orchestrator = Orchestrator(config)
    await orchestrator.start()

    # Set up signal handlers
    loop = asyncio.get_event_loop()
    shutdown_event = asyncio.Event()

    def handle_signal():
        logger.info("shutdown_signal_received")
        shutdown_event.set()

    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, handle_signal)

    # Run until shutdown
    try:
        await shutdown_event.wait()
    finally:
        await orchestrator.stop()

    logger.info("agent_stopped")


def main():
    """Synchronous entry point."""
    asyncio.run(run_agent())


if __name__ == "__main__":
    main()
