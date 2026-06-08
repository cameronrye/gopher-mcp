"""Tests for the per-host outbound rate limiter."""

from unittest.mock import AsyncMock

import pytest

from gopher_mcp.ratelimit import RateLimiter


class _FakeClock:
    """A controllable monotonic clock."""

    def __init__(self, t: float = 100.0) -> None:
        self.t = t

    def __call__(self) -> float:
        return self.t


class TestRateLimiterConfig:
    def test_interval_from_requests_per_minute(self):
        assert RateLimiter(60).min_interval == 1.0
        assert RateLimiter(120).min_interval == 0.5

    def test_zero_means_disabled(self):
        assert RateLimiter(0).min_interval == 0.0


@pytest.mark.asyncio
class TestRateLimiterAcquire:
    async def test_disabled_never_sleeps(self):
        sleep = AsyncMock()
        rl = RateLimiter(0, sleep=sleep)
        await rl.acquire("example.org")
        await rl.acquire("example.org")
        sleep.assert_not_awaited()

    async def test_first_request_to_host_is_immediate(self):
        sleep = AsyncMock()
        rl = RateLimiter(60, clock=_FakeClock(100.0), sleep=sleep)
        await rl.acquire("a.example")
        sleep.assert_not_awaited()

    async def test_second_request_same_host_waits_one_interval(self):
        clock = _FakeClock(100.0)
        sleep = AsyncMock()
        rl = RateLimiter(60, clock=clock, sleep=sleep)  # 1s interval
        await rl.acquire("a.example")  # schedules next at 101
        await rl.acquire("a.example")  # clock still 100 -> must wait ~1s
        sleep.assert_awaited_once()
        assert sleep.await_args.args[0] == pytest.approx(1.0)

    async def test_different_hosts_do_not_throttle_each_other(self):
        sleep = AsyncMock()
        rl = RateLimiter(60, clock=_FakeClock(100.0), sleep=sleep)
        await rl.acquire("a.example")
        await rl.acquire("b.example")
        sleep.assert_not_awaited()

    async def test_penalize_forces_a_backoff_even_when_disabled(self):
        clock = _FakeClock(100.0)
        sleep = AsyncMock()
        rl = RateLimiter(0, clock=clock, sleep=sleep)  # otherwise unlimited
        rl.penalize("slow.example", 5)
        await rl.acquire("slow.example")
        sleep.assert_awaited_once()
        assert sleep.await_args.args[0] == pytest.approx(5.0)
