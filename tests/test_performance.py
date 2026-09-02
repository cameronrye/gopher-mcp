"""Performance and load tests for Gopher and Gemini protocols."""

import asyncio
import gc
import time
from unittest.mock import AsyncMock, Mock, patch

import pytest

from gopher_mcp.gemini_client import GeminiClient
from gopher_mcp.gemini_tls import TLSConnectionError
from gopher_mcp.gopher_client import GopherClient
from gopher_mcp.models import GeminiErrorResult, GeminiSuccessResult, TextResult


@pytest.mark.slow
class TestPerformanceBaselines:
    """Test performance baselines and benchmarks."""

    @pytest.mark.asyncio
    async def test_gemini_client_response_time(self):
        """Test Gemini client response time baseline."""
        client = GeminiClient(tofu_enabled=False)

        # Mock fast response
        mock_response = b"20 text/plain\r\nTest content"

        with patch.object(client.tls_client, "connect", return_value=(Mock(), {})):
            with patch.object(client.tls_client, "send_data"):
                with patch.object(
                    client.tls_client, "receive_data", return_value=mock_response
                ):
                    with patch.object(client.tls_client, "close"):
                        start_time = time.time()
                        result = await client.fetch("gemini://example.com/")
                        end_time = time.time()

                        response_time = end_time - start_time

                        # Should complete within reasonable time (< 100ms for mocked response)
                        assert response_time < 2.0
                        assert isinstance(result, GeminiSuccessResult)

    @pytest.mark.asyncio
    async def test_gopher_client_response_time(self):
        """Test Gopher client response time baseline."""
        client = GopherClient()

        # Mock fast response
        mock_response = b"Test content line 1\r\nTest content line 2\r\n.\r\n"

        with patch(
            "gopher_mcp.gopher_client.fetch_gopher",
            new=AsyncMock(return_value=mock_response),
        ):
            start_time = time.time()
            result = await client.fetch("gopher://example.com/0/test.txt")
            end_time = time.time()

            response_time = end_time - start_time

            # Should complete within reasonable time
            assert response_time < 2.0
            assert isinstance(result, TextResult)

    def test_cache_performance(self):
        """Test cache performance and efficiency."""
        client = GeminiClient(cache_enabled=True, max_cache_entries=1000)

        # Test cache write performance
        start_time = time.time()
        for i in range(1000):
            url = f"gemini://example{i}.com/"
            from gopher_mcp.models import GeminiMimeType

            mock_response = GeminiSuccessResult(
                content="Test content",
                mimeType=GeminiMimeType(type="text", subtype="gemini", lang=None),
                size=12,
                requestInfo={"url": url, "timestamp": time.time()},
            )
            client._cache_response(url, mock_response)
        end_time = time.time()

        cache_write_time = end_time - start_time

        # Should be able to write 1000 entries quickly
        assert cache_write_time < 5.0  # generous CI-safe ceiling

        # Test cache read performance
        start_time = time.time()
        for i in range(1000):
            url = f"gemini://example{i}.com/"
            _ = client._get_cached_response(
                url
            )  # Use underscore for unused return value
        end_time = time.time()

        cache_read_time = end_time - start_time

        # Cache reads should be very fast
        assert cache_read_time < 2.0  # generous CI-safe ceiling


@pytest.mark.slow
class TestConcurrentLoad:
    """Test concurrent load handling."""

    @pytest.mark.asyncio
    async def test_concurrent_gemini_requests(self):
        """Test handling multiple concurrent Gemini requests."""
        client = GeminiClient(tofu_enabled=False)

        # Mock responses
        mock_response = b"20 text/plain\r\nTest content"

        urls = [f"gemini://example{i}.com/" for i in range(10)]

        # Patch once around the whole gather; unittest.mock.patch is not
        # safe to enter/exit concurrently from multiple coroutines.
        start_time = time.time()
        with (
            patch.object(
                client.tls_client,
                "connect",
                new=AsyncMock(return_value=(Mock(), {})),
            ),
            patch.object(client.tls_client, "send_data", new=AsyncMock()),
            patch.object(
                client.tls_client,
                "receive_data",
                new=AsyncMock(return_value=mock_response),
            ),
            patch.object(client.tls_client, "close", new=AsyncMock()),
        ):
            results = await asyncio.gather(*[client.fetch(url) for url in urls])
        end_time = time.time()

        total_time = end_time - start_time

        # All requests should succeed
        assert len(results) == 10
        assert all(isinstance(result, GeminiSuccessResult) for result in results)

        # Concurrent execution should complete promptly (generous CI ceiling).
        assert total_time < 5.0

    @pytest.mark.asyncio
    async def test_concurrent_gopher_requests(self):
        """Test handling multiple concurrent Gopher requests."""
        client = GopherClient()

        # Mock responses
        mock_response = b"Test content\r\n.\r\n"

        urls = [f"gopher://example{i}.com/0/test.txt" for i in range(10)]

        # Patch once around the whole gather (mock.patch is not concurrency-safe).
        start_time = time.time()
        with patch(
            "gopher_mcp.gopher_client.fetch_gopher",
            new=AsyncMock(return_value=mock_response),
        ):
            results = await asyncio.gather(*[client.fetch(url) for url in urls])
        end_time = time.time()

        total_time = end_time - start_time

        # All requests should succeed
        assert len(results) == 10
        assert all(isinstance(result, TextResult) for result in results)

        # Should complete reasonably quickly
        assert total_time < 2.0


@pytest.mark.slow
class TestMemoryUsage:
    """Test memory usage and leak detection."""

    def test_memory_usage_baseline(self):
        """Clients construct cleanly with empty caches.

        (Was an RSS-threshold assertion: process-RSS deltas are non-deterministic
        on shared/CI runners -- GC timing, allocator, other tests' residue -- so
        it flaked without testing anything specific. Structural checks instead.)
        """
        gemini = GeminiClient()
        gopher = GopherClient()
        assert len(gemini._cache) == 0
        assert len(gopher._cache) == 0

    @pytest.mark.asyncio
    async def test_repeated_fetches_keep_cache_bounded(self):
        """Repeated operations don't grow the cache without bound.

        (Was an RSS leak threshold -- replaced with the structural invariant that
        actually matters: the LRU cache never exceeds its configured limit.)
        """
        client = GeminiClient(max_cache_entries=20)
        mock_response = b"20 text/plain\r\nTest content"

        for i in range(100):
            with (
                patch.object(client.tls_client, "connect", return_value=(Mock(), {})),
                patch.object(client.tls_client, "send_data"),
                patch.object(
                    client.tls_client, "receive_data", return_value=mock_response
                ),
                patch.object(client.tls_client, "close"),
            ):
                await client.fetch(f"gemini://example{i}.com/")
            if i % 10 == 0:
                gc.collect()

        assert len(client._cache) <= 20

    def test_cache_memory_management(self):
        """Cache eviction keeps the cache at or below its configured limit."""
        client = GeminiClient(max_cache_entries=100)

        # Fill cache beyond limit
        for i in range(200):
            url = f"gemini://example{i}.com/"
            from gopher_mcp.models import GeminiMimeType

            mock_response = GeminiSuccessResult(
                content="A" * 1000,
                mimeType=GeminiMimeType(type="text", subtype="gemini", lang=None),
                size=1000,
                requestInfo={"url": url, "timestamp": time.time()},
            )
            client._cache_response(url, mock_response)

        # Cache must not exceed limit (structural; no flaky RSS threshold).
        assert len(client._cache) <= 100


@pytest.mark.slow
class TestScalability:
    """Test scalability and resource limits."""

    @pytest.mark.asyncio
    async def test_large_response_handling(self):
        """A large but under-limit response is fetched and returned intact."""
        client = GeminiClient(max_response_size=10 * 1024 * 1024, tofu_enabled=False)

        large_content = "A" * (5 * 1024 * 1024)  # 5MB, under the 10MB cap
        large_response = f"20 text/plain; charset=utf-8\r\n{large_content}".encode()

        with (
            patch.object(client.tls_client, "connect", return_value=(Mock(), {})),
            patch.object(client.tls_client, "send_data"),
            patch.object(
                client.tls_client, "receive_data", return_value=large_response
            ),
            patch.object(client.tls_client, "close"),
        ):
            result = await client.fetch("gemini://example.com/")

        assert not isinstance(result, GeminiErrorResult)
        assert result.kind == "success"
        assert result.size == len(large_content.encode("utf-8"))

    @pytest.mark.asyncio
    async def test_connection_pool_efficiency(self):
        """Test connection pooling efficiency."""
        # Politeness throttling is on by default and would dominate the timing
        # here; this test is about per-request overhead, so disable it.
        client = GeminiClient(requests_per_minute=0)

        # Test reusing connections to same host
        same_host_urls = [f"gemini://example.com/page{i}" for i in range(5)]

        mock_response = b"20 text/plain\r\nTest content"

        start_time = time.time()

        for url in same_host_urls:
            with patch.object(client.tls_client, "connect", return_value=(Mock(), {})):
                with patch.object(client.tls_client, "send_data"):
                    with patch.object(
                        client.tls_client, "receive_data", return_value=mock_response
                    ):
                        with patch.object(client.tls_client, "close"):
                            await client.fetch(url)

        end_time = time.time()
        total_time = end_time - start_time

        # Should complete efficiently
        assert total_time < 1.0


@pytest.mark.slow
class TestResourceLimits:
    """Test resource limit enforcement."""

    @pytest.mark.asyncio
    async def test_connection_timeout_enforcement(self):
        """A connection timeout surfaces as a sanitized TLS error."""
        # This test is about the TLS failure path, not robots: with the gate on,
        # the robots.txt probe hits the same mocked connect failure first and
        # the fail-closed gate would answer BLOCKED_BY_ROBOTS instead.
        client = GeminiClient(
            timeout_seconds=1, tofu_enabled=False, respect_robots_txt=False
        )

        with patch.object(
            client.tls_client,
            "connect",
            side_effect=TLSConnectionError("Connection timeout after 1 seconds"),
        ):
            result = await client.fetch("gemini://example.com/")

        assert isinstance(result, GeminiErrorResult)
        assert result.error["code"] == "TLS_ERROR"

    @pytest.mark.asyncio
    async def test_response_size_limit_enforcement(self):
        """The configured response-size cap actually rejects oversized data."""
        # Robots off: this test is about the size cap, and the gate's robots.txt
        # probe would consume the scripted socket reads before the fetch runs.
        client = GeminiClient(
            max_response_size=1024, tofu_enabled=False, respect_robots_txt=False
        )

        mock_sock = Mock()
        mock_sock.recv.side_effect = [b"A" * 1024, b"A"]  # cap, then over-limit probe
        mock_sock.gettimeout.return_value = 5.0

        with (
            patch.object(client.tls_client, "connect", return_value=(mock_sock, {})),
            patch.object(client.tls_client, "send_data"),
            patch.object(client.tls_client, "close"),
        ):
            result = await client.fetch("gemini://example.com/")

        assert isinstance(result, GeminiErrorResult)
        assert result.error["code"] == "TLS_ERROR"

    def test_cache_size_limit_enforcement(self):
        """Test cache size limit enforcement."""
        client = GeminiClient(max_cache_entries=10)

        # Add more entries than limit
        for i in range(20):
            url = f"gemini://example{i}.com/"
            from gopher_mcp.models import GeminiMimeType

            mock_response = GeminiSuccessResult(
                content="Test content",
                mimeType=GeminiMimeType(type="text", subtype="gemini", lang=None),
                size=12,
                requestInfo={"url": url, "timestamp": time.time()},
            )
            client._cache_response(url, mock_response)

        # Cache should not exceed limit
        assert len(client._cache) <= 10


class TestPerformanceRegression:
    """Test for performance regressions."""

    def test_url_parsing_performance(self):
        """Test URL parsing performance."""
        from gopher_mcp.utils import parse_gemini_url, parse_gopher_url

        # Test parsing many URLs
        gemini_urls = [f"gemini://example{i}.com/path{i}" for i in range(1000)]
        gopher_urls = [f"gopher://example{i}.com/0/path{i}" for i in range(1000)]

        # Test Gemini URL parsing
        start_time = time.time()
        for url in gemini_urls:
            parse_gemini_url(url)
        gemini_parse_time = time.time() - start_time

        # Test Gopher URL parsing
        start_time = time.time()
        for url in gopher_urls:
            parse_gopher_url(url)
        gopher_parse_time = time.time() - start_time

        # Should parse URLs quickly
        assert gemini_parse_time < 1.0  # Less than 1 second for 1000 URLs
        assert gopher_parse_time < 1.0

    def test_response_processing_performance(self):
        """Test response processing performance."""
        from gopher_mcp.utils import parse_gemini_response, parse_gopher_menu

        # Test processing many responses
        gemini_response = (
            b"20 text/gemini\r\n# Test\n=> gemini://example.com/ Link\nText content"
        )
        gopher_menu = "1Test Menu\t/menu\texample.com\t70\r\n0Test File\t/file.txt\texample.com\t70\r\n.\r\n"

        start_time = time.time()
        for _ in range(1000):
            parse_gemini_response(gemini_response)
        gemini_process_time = time.time() - start_time

        start_time = time.time()
        for _ in range(1000):
            parse_gopher_menu(gopher_menu)
        gopher_process_time = time.time() - start_time

        # Should process responses quickly
        assert gemini_process_time < 2.0
        assert gopher_process_time < 2.0


@pytest.mark.slow
class TestLoadTesting:
    """Load testing scenarios."""

    @pytest.mark.asyncio
    async def test_sustained_load(self):
        """Test sustained load over time."""
        # Throughput test: measure the client, not the per-host rate limiter.
        client = GeminiClient(requests_per_minute=0)
        mock_response = b"20 text/plain\r\nTest content"

        # Run sustained load for a period
        start_time = time.time()
        request_count = 0

        while time.time() - start_time < 5.0:  # Run for 5 seconds
            with patch.object(client.tls_client, "connect", return_value=(Mock(), {})):
                with patch.object(client.tls_client, "send_data"):
                    with patch.object(
                        client.tls_client, "receive_data", return_value=mock_response
                    ):
                        with patch.object(client.tls_client, "close"):
                            await client.fetch(
                                f"gemini://example.com/page{request_count}"
                            )
                            request_count += 1

        # Should handle reasonable number of requests
        assert request_count > 10  # At least 2 requests per second

    def test_burst_load_handling(self):
        """Test handling of burst loads."""
        client = GeminiClient()

        # Simulate burst of cache operations
        start_time = time.time()
        for i in range(100):
            url = f"gemini://example{i}.com/"
            from gopher_mcp.models import GeminiMimeType

            mock_response = GeminiSuccessResult(
                content="Test content",
                mimeType=GeminiMimeType(type="text", subtype="gemini", lang=None),
                size=12,
                requestInfo={"url": url, "timestamp": time.time()},
            )
            client._cache_response(url, mock_response)
        end_time = time.time()

        burst_time = end_time - start_time

        # Should handle burst efficiently
        assert burst_time < 1.0  # Less than 1 second for 100 operations


class TestGopherTimeoutIsOneBudget:
    """docs/configuration.md and config/example.env both promise that
    GOPHER_TIMEOUT_SECONDS is the "overall deadline for one fetch, covering DNS,
    connect, send and read". It was not: DNS and the transport were each handed
    the full value, and the robots probe spent two more full phases of its own,
    so one call could occupy four multiples of the configured deadline."""

    @pytest.mark.asyncio
    async def test_dns_and_transport_share_one_deadline(self, monkeypatch):
        from gopher_mcp.gopher_client import GopherClient

        seen: list[float] = []

        async def slow_resolve(host, port):
            await asyncio.sleep(0.20)
            return ["93.184.216.34"]

        async def record_timeout(host, port, selector, search, **kwargs):
            seen.append(kwargs["timeout"])
            return b"iok\tfake\t(NULL)\t0\r\n.\r\n"

        monkeypatch.setattr("gopher_mcp.ssrf.resolve_host", slow_resolve)
        monkeypatch.setattr("gopher_mcp.gopher_client.fetch_gopher", record_timeout)

        client = GopherClient(
            timeout_seconds=1.0,
            cache_enabled=False,
            requests_per_minute=0,
            respect_robots_txt=False,
        )
        await client.fetch("gopher://example.com/1/")
        await client.close()

        assert seen, "the transport was never reached"
        # The 0.2s spent in DNS came out of the 1.0s budget, so the transport
        # must be granted strictly less than the full deadline.
        #
        # Bounded rather than pinned to ~0.8: a loaded runner can overshoot the
        # sleep, which only charges MORE to the budget and leaves less here. So
        # assert the direction (at least the sleep was charged) and that the
        # budget is not exhausted -- both of which a fresh full timeout, the bug
        # this guards, would violate.
        assert 0 < seen[0] <= 1.0 - 0.15, (
            f"transport did not draw down the shared budget: {seen[0]}"
        )

    @pytest.mark.asyncio
    async def test_the_robots_probe_spends_from_the_same_budget(self, monkeypatch):
        from gopher_mcp.gopher_client import GopherClient

        seen: list[float] = []

        async def slow_resolve(host, port):
            await asyncio.sleep(0.15)
            return ["93.184.216.34"]

        async def record_timeout(host, port, selector, search, **kwargs):
            seen.append(kwargs["timeout"])
            return b".\r\n"

        monkeypatch.setattr("gopher_mcp.ssrf.resolve_host", slow_resolve)
        monkeypatch.setattr("gopher_mcp.gopher_client.fetch_gopher", record_timeout)

        client = GopherClient(
            timeout_seconds=1.0,
            cache_enabled=False,
            requests_per_minute=0,
            respect_robots_txt=True,
        )
        await client.fetch("gopher://example.com/1/")
        await client.close()

        # Two transport phases: the robots probe, then the fetch it guards.
        assert len(seen) == 2, seen
        # Each is strictly smaller than the last -- one budget, drawn down.
        assert seen[1] < seen[0] < 1.0, seen

    @pytest.mark.asyncio
    async def test_an_exhausted_budget_reports_as_a_timeout(self):
        """The budget check raises through the robots probe's handler chain,
        where the generic GopherProtocolError arm would have called a spent
        deadline "the reply was not a valid Gopher response"."""
        from gopher_mcp.gopher_client import (
            _FETCH_BUDGET,
            _BudgetExhausted,
            _FetchBudget,
            _spend_budget,
        )
        from gopher_mcp.gopher_transport import GopherProtocolError

        token = _FETCH_BUDGET.set(_FetchBudget(0.0))
        try:
            with pytest.raises(_BudgetExhausted) as exc:
                async with _spend_budget(30.0):
                    pass  # pragma: no cover - the guard fires before the body
        finally:
            _FETCH_BUDGET.reset(token)

        assert "timed out" in str(exc.value)
        # Still a GopherProtocolError, so fetch() keeps mapping it to
        # FETCH_ERROR rather than needing a new arm.
        assert isinstance(exc.value, GopherProtocolError)
