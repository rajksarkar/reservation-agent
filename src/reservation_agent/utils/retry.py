"""Retry utilities with exponential backoff and circuit breaker."""

import asyncio
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from functools import wraps
from typing import Any, Callable, Coroutine, TypeVar

from reservation_agent.core.exceptions import CircuitBreakerOpenError, RateLimitError
from reservation_agent.utils.logging import get_logger

logger = get_logger(__name__)

T = TypeVar("T")


@dataclass
class RetryConfig:
    """Configuration for retry behavior."""

    max_retries: int = 5
    base_delay: float = 1.0  # seconds
    max_delay: float = 300.0  # seconds
    exponential_base: float = 2.0
    jitter: float = 0.1  # 10% jitter


class CircuitState(Enum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, reject requests
    HALF_OPEN = "half_open"  # Testing if recovered


@dataclass
class CircuitBreaker:
    """Circuit breaker to prevent cascading failures."""

    name: str
    failure_threshold: int = 5
    recovery_timeout: float = 60.0  # seconds
    half_open_max_calls: int = 1

    # State
    state: CircuitState = field(default=CircuitState.CLOSED)
    failure_count: int = field(default=0)
    last_failure_time: float = field(default=0.0)
    half_open_calls: int = field(default=0)

    def __post_init__(self):
        self._lock = asyncio.Lock()

    async def call(
        self,
        func: Callable[..., Coroutine[Any, Any, T]],
        *args,
        **kwargs,
    ) -> T:
        """Execute function with circuit breaker protection."""
        async with self._lock:
            self._check_state()

            if self.state == CircuitState.OPEN:
                raise CircuitBreakerOpenError(
                    self.name, self.last_failure_time + self.recovery_timeout
                )

            if self.state == CircuitState.HALF_OPEN:
                if self.half_open_calls >= self.half_open_max_calls:
                    raise CircuitBreakerOpenError(
                        self.name, self.last_failure_time + self.recovery_timeout
                    )
                self.half_open_calls += 1

        try:
            result = await func(*args, **kwargs)
            await self._on_success()
            return result
        except Exception as e:
            await self._on_failure()
            raise

    def _check_state(self) -> None:
        """Update state based on recovery timeout."""
        if self.state == CircuitState.OPEN:
            if time.time() - self.last_failure_time >= self.recovery_timeout:
                logger.info(
                    "circuit_half_open",
                    name=self.name,
                )
                self.state = CircuitState.HALF_OPEN
                self.half_open_calls = 0

    async def _on_success(self) -> None:
        """Handle successful call."""
        async with self._lock:
            if self.state == CircuitState.HALF_OPEN:
                logger.info("circuit_closed", name=self.name)
                self.state = CircuitState.CLOSED
            self.failure_count = 0

    async def _on_failure(self) -> None:
        """Handle failed call."""
        async with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.time()

            if self.state == CircuitState.HALF_OPEN:
                logger.warning("circuit_reopened", name=self.name)
                self.state = CircuitState.OPEN
            elif self.failure_count >= self.failure_threshold:
                logger.warning(
                    "circuit_opened",
                    name=self.name,
                    failures=self.failure_count,
                )
                self.state = CircuitState.OPEN

    def reset(self) -> None:
        """Manually reset the circuit breaker."""
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.half_open_calls = 0
        logger.info("circuit_reset", name=self.name)


def calculate_backoff(
    attempt: int,
    config: RetryConfig,
) -> float:
    """Calculate delay with exponential backoff and jitter."""
    delay = config.base_delay * (config.exponential_base ** attempt)
    delay = min(delay, config.max_delay)

    # Add jitter
    jitter_range = delay * config.jitter
    jitter = random.uniform(-jitter_range, jitter_range)
    delay += jitter

    return max(0, delay)


async def retry_with_backoff(
    func: Callable[..., Coroutine[Any, Any, T]],
    *args,
    config: RetryConfig | None = None,
    retry_exceptions: tuple = (Exception,),
    on_retry: Callable[[int, Exception, float], None] | None = None,
    **kwargs,
) -> T:
    """Execute function with exponential backoff retry.

    Args:
        func: Async function to execute
        *args: Positional arguments for func
        config: Retry configuration
        retry_exceptions: Tuple of exceptions to retry on
        on_retry: Callback called before each retry (attempt, exception, delay)
        **kwargs: Keyword arguments for func

    Returns:
        Result of successful function call

    Raises:
        The last exception if all retries fail
    """
    config = config or RetryConfig()
    last_exception: Exception | None = None

    for attempt in range(config.max_retries + 1):
        try:
            return await func(*args, **kwargs)
        except retry_exceptions as e:
            last_exception = e

            # Check for rate limit with specific retry time
            if isinstance(e, RateLimitError) and e.retry_after:
                delay = e.retry_after
            else:
                delay = calculate_backoff(attempt, config)

            if attempt < config.max_retries:
                logger.warning(
                    "retrying",
                    attempt=attempt + 1,
                    max_retries=config.max_retries,
                    delay=delay,
                    error=str(e),
                )

                if on_retry:
                    on_retry(attempt + 1, e, delay)

                await asyncio.sleep(delay)
            else:
                logger.error(
                    "max_retries_exceeded",
                    attempts=attempt + 1,
                    error=str(e),
                )

    raise last_exception  # type: ignore


def with_retry(
    config: RetryConfig | None = None,
    retry_exceptions: tuple = (Exception,),
):
    """Decorator for adding retry behavior to async functions."""

    def decorator(func: Callable[..., Coroutine[Any, Any, T]]) -> Callable[..., Coroutine[Any, Any, T]]:
        @wraps(func)
        async def wrapper(*args, **kwargs) -> T:
            return await retry_with_backoff(
                func,
                *args,
                config=config,
                retry_exceptions=retry_exceptions,
                **kwargs,
            )

        return wrapper

    return decorator


class AdaptiveRateLimiter:
    """Rate limiter that adapts based on success/failure."""

    def __init__(
        self,
        initial_delay: float = 1.0,
        min_delay: float = 0.5,
        max_delay: float = 60.0,
        success_decrease: float = 0.9,
        failure_increase: float = 1.5,
    ):
        self.delay = initial_delay
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.success_decrease = success_decrease
        self.failure_increase = failure_increase
        self._last_call = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait for rate limit before proceeding."""
        async with self._lock:
            now = time.time()
            elapsed = now - self._last_call
            wait_time = max(0, self.delay - elapsed)

            if wait_time > 0:
                await asyncio.sleep(wait_time)

            self._last_call = time.time()

    def on_success(self) -> None:
        """Decrease delay on success."""
        self.delay = max(self.min_delay, self.delay * self.success_decrease)

    def on_failure(self) -> None:
        """Increase delay on failure."""
        self.delay = min(self.max_delay, self.delay * self.failure_increase)

    def reset(self) -> None:
        """Reset to initial delay."""
        self.delay = self.min_delay
