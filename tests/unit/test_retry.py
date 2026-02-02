"""Tests for retry utilities."""

import asyncio

import pytest

from reservation_agent.core.exceptions import CircuitBreakerOpenError
from reservation_agent.utils.retry import (
    AdaptiveRateLimiter,
    CircuitBreaker,
    CircuitState,
    RetryConfig,
    calculate_backoff,
    retry_with_backoff,
)


class TestCalculateBackoff:
    def test_first_attempt(self):
        config = RetryConfig(base_delay=1.0, exponential_base=2.0, jitter=0)
        delay = calculate_backoff(0, config)
        assert delay == 1.0

    def test_exponential_increase(self):
        config = RetryConfig(base_delay=1.0, exponential_base=2.0, jitter=0)
        delays = [calculate_backoff(i, config) for i in range(5)]
        assert delays == [1.0, 2.0, 4.0, 8.0, 16.0]

    def test_max_delay_cap(self):
        config = RetryConfig(base_delay=1.0, exponential_base=2.0, max_delay=5.0, jitter=0)
        delay = calculate_backoff(10, config)  # Would be 1024 without cap
        assert delay == 5.0

    def test_jitter_applied(self):
        config = RetryConfig(base_delay=1.0, jitter=0.5)
        delays = [calculate_backoff(0, config) for _ in range(100)]
        # With 50% jitter, delays should vary between 0.5 and 1.5
        assert any(d != 1.0 for d in delays)
        assert all(0.5 <= d <= 1.5 for d in delays)


class TestCircuitBreaker:
    @pytest.mark.asyncio
    async def test_closed_allows_calls(self):
        cb = CircuitBreaker(name="test", failure_threshold=3)

        async def success_func():
            return "success"

        result = await cb.call(success_func)
        assert result == "success"
        assert cb.state == CircuitState.CLOSED

    @pytest.mark.asyncio
    async def test_opens_after_threshold(self):
        cb = CircuitBreaker(name="test", failure_threshold=3)

        async def fail_func():
            raise ValueError("error")

        for _ in range(3):
            with pytest.raises(ValueError):
                await cb.call(fail_func)

        assert cb.state == CircuitState.OPEN

    @pytest.mark.asyncio
    async def test_open_rejects_calls(self):
        cb = CircuitBreaker(name="test", failure_threshold=1)

        async def fail_func():
            raise ValueError("error")

        with pytest.raises(ValueError):
            await cb.call(fail_func)

        assert cb.state == CircuitState.OPEN

        with pytest.raises(CircuitBreakerOpenError):
            await cb.call(fail_func)

    @pytest.mark.asyncio
    async def test_success_resets_failures(self):
        cb = CircuitBreaker(name="test", failure_threshold=3)

        async def fail_func():
            raise ValueError("error")

        async def success_func():
            return "ok"

        # Two failures
        for _ in range(2):
            with pytest.raises(ValueError):
                await cb.call(fail_func)

        assert cb.failure_count == 2

        # Success resets
        await cb.call(success_func)
        assert cb.failure_count == 0

    def test_reset(self):
        cb = CircuitBreaker(name="test", failure_threshold=1)
        cb.state = CircuitState.OPEN
        cb.failure_count = 5

        cb.reset()

        assert cb.state == CircuitState.CLOSED
        assert cb.failure_count == 0


class TestRetryWithBackoff:
    @pytest.mark.asyncio
    async def test_success_on_first_try(self):
        call_count = 0

        async def success_func():
            nonlocal call_count
            call_count += 1
            return "success"

        result = await retry_with_backoff(success_func)
        assert result == "success"
        assert call_count == 1

    @pytest.mark.asyncio
    async def test_retries_on_failure(self):
        call_count = 0

        async def fail_twice():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ValueError("not yet")
            return "success"

        config = RetryConfig(base_delay=0.01, max_retries=5)
        result = await retry_with_backoff(fail_twice, config=config)
        assert result == "success"
        assert call_count == 3

    @pytest.mark.asyncio
    async def test_raises_after_max_retries(self):
        async def always_fail():
            raise ValueError("always fails")

        config = RetryConfig(base_delay=0.01, max_retries=2)
        with pytest.raises(ValueError):
            await retry_with_backoff(always_fail, config=config)

    @pytest.mark.asyncio
    async def test_only_retries_specified_exceptions(self):
        async def raise_type_error():
            raise TypeError("wrong type")

        config = RetryConfig(base_delay=0.01, max_retries=3)
        with pytest.raises(TypeError):
            await retry_with_backoff(
                raise_type_error,
                config=config,
                retry_exceptions=(ValueError,),
            )


class TestAdaptiveRateLimiter:
    @pytest.mark.asyncio
    async def test_respects_delay(self):
        limiter = AdaptiveRateLimiter(initial_delay=0.1)

        start = asyncio.get_event_loop().time()
        await limiter.acquire()
        await limiter.acquire()
        elapsed = asyncio.get_event_loop().time() - start

        assert elapsed >= 0.1

    def test_decreases_on_success(self):
        limiter = AdaptiveRateLimiter(initial_delay=1.0, success_decrease=0.5)
        initial = limiter.delay

        limiter.on_success()

        assert limiter.delay < initial

    def test_increases_on_failure(self):
        limiter = AdaptiveRateLimiter(initial_delay=1.0, failure_increase=2.0)
        initial = limiter.delay

        limiter.on_failure()

        assert limiter.delay > initial

    def test_respects_bounds(self):
        limiter = AdaptiveRateLimiter(
            initial_delay=1.0,
            min_delay=0.5,
            max_delay=2.0,
        )

        # Try to go below min
        for _ in range(10):
            limiter.on_success()
        assert limiter.delay >= 0.5

        # Try to go above max
        limiter.reset()
        for _ in range(10):
            limiter.on_failure()
        assert limiter.delay <= 2.0
