"""Rapid polling for release-window snipes."""

import asyncio
from typing import Any, Callable, Coroutine

from reservation_agent.utils.logging import get_logger

logger = get_logger(__name__)


class RapidPoller:
    """Handles rapid polling during release window."""

    def __init__(
        self,
        interval_ms: float = 500,
        duration_seconds: int = 10,
    ):
        self.interval = interval_ms / 1000
        self.duration = duration_seconds
        self._stop_event = asyncio.Event()

    async def poll(
        self,
        callback: Callable[..., Coroutine[Any, Any, bool]],
        **kwargs,
    ) -> bool:
        """Rapidly poll until success or timeout.

        Args:
            callback: Async function that returns True on success
            **kwargs: Arguments to pass to callback

        Returns:
            True if callback succeeded, False if timed out
        """
        self._stop_event.clear()
        end_time = asyncio.get_event_loop().time() + self.duration

        logger.info(
            "starting_rapid_poll",
            interval_ms=self.interval * 1000,
            duration_seconds=self.duration,
        )

        attempt = 0
        while asyncio.get_event_loop().time() < end_time:
            if self._stop_event.is_set():
                break

            attempt += 1
            try:
                success = await callback(**kwargs)
                if success:
                    logger.info("rapid_poll_success", attempt=attempt)
                    return True
            except Exception as e:
                logger.warning("rapid_poll_error", attempt=attempt, error=str(e))

            await asyncio.sleep(self.interval)

        logger.info("rapid_poll_timeout", attempts=attempt)
        return False

    def stop(self) -> None:
        """Stop the rapid polling."""
        self._stop_event.set()
