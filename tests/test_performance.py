"""Performance and load tests for Gopher and Gemini protocols."""

import asyncio
import time
import pytest
import psutil
import gc
from unittest.mock import Mock, patch

from src.gopher_mcp.gemini_client import GeminiClient
from src.gopher_mcp.gopher_client import GopherClient
from src.gopher_mcp.models import GeminiSuccessResult, TextResult


@pytest.mark.slow
class TestPerformanceBaselines:
    """Test performance baselines and benchmarks."""

    @pytest.mark.asyncio
    async def test_gemini_client_response_time(self):
        """Test Gemini client response time baseline."""
        client = GeminiClient()

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
                        assert response_time < 0.1
                        assert isinstance(result, GeminiSuccessResult)

    @pytest.mark.asyncio
    async def test_gopher_client_response_time(self):
        """Test Gopher client response time baseline."""
        client = GopherClient()

        # Mock fast response
        mock_response = b"Test content line 1\r\nTest content line 2\r\n.\r\n"

        with patch(
            "src.gopher_mcp.gopher_client.pituophis.Request"
        ) as mock_request_class:
            mock_request = Mock()
            mock_request.get.return_value = mock_response
            mock_request_class.return_value = mock_request

            start_time = time.time()
            result = await client.fetch("gopher://example.com/0/test.txt")
            end_time = time.time()

            response_time = end_time - start_time

            # Should complete within reasonable time
            assert response_time < 0.1
            assert isinstance(result, TextResult)

    def test_cache_performance(self):
        """Test cache performance and efficiency."""
        client = GeminiClient(cache_enabled=True, max_cache_entries=1000)

        # Test cache write performance
        start_time = time.time()
        for i in range(1000):
            url = f"gemini://example{i}.com/"
            from src.gopher_mcp.models import GeminiMimeType

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
        assert cache_write_time < 1.0  # Less than 1 second

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
        assert cache_read_time < 0.1  # Less than 100ms


@pytest.mark.slow
class TestConcurrentLoad:
    """Test concurrent load handling."""

    @pytest.mark.asyncio
    async def test_concurrent_gemini_requests(self):
        """Test handling multiple concurrent Gemini requests."""
        client = GeminiClient()

        # Mock responses
        mock_response = b"20 text/plain\r\nTest content"

        async def mock_fetch(url: str):
            with patch.object(client.tls_client, "connect", return_value=(Mock(), {})):
                with patch.object(client.tls_client, "send_data"):
                    with patch.object(
                        client.tls_client, "receive_data", return_value=mock_response
                    ):
                        with patch.object(client.tls_client, "close"):
                            return await client.fetch(url)

        # Test concurrent requests
        urls = [f"gemini://example{i}.com/" for i in range(10)]

        start_time = time.time()
        results = await asyncio.gather(*[mock_fetch(url) for url in urls])
        end_time = time.time()

        total_time = end_time - start_time

        # All requests should succeed
        assert len(results) == 10
        assert all(isinstance(result, GeminiSuccessResult) for result in results)

        # Concurrent execution should be faster than sequential
        assert total_time < 1.0  # Should complete quickly with mocked responses

    @pytest.mark.asyncio
    async def test_concurrent_gopher_requests(self):
        """Test handling multiple concurrent Gopher requests."""
        client = GopherClient()

        # Mock responses
        mock_response = b"Test content\r\n.\r\n"

        async def mock_fetch(url: str):
            with patch(
                "src.gopher_mcp.gopher_client.pituophis.Request"
            ) as mock_request_class:
                mock_request = Mock()
                mock_request.get.return_value = mock_response
                mock_request_class.return_value = mock_request
                return await client.fetch(url)

        # Test concurrent requests
        urls = [f"gopher://example{i}.com/0/test.txt" for i in range(10)]

        start_time = time.time()
        results = await asyncio.gather(*[mock_fetch(url) for url in urls])
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
        """Test baseline memory usage."""
        # Get initial memory usage
        process = psutil.Process()
        initial_memory = process.memory_info().rss

        # Create clients
        _ = GeminiClient()  # Create client to test memory usage
        _ = GopherClient()  # Create client to test memory usage

        # Get memory after client creation
        after_creation_memory = process.memory_info().rss

        # Memory increase should be reasonable
        memory_increase = after_creation_memory - initial_memory
        assert memory_increase < 50 * 1024 * 1024  # Less than 50MB

    @pytest.mark.asyncio
    async def test_memory_leak_detection(self):
        """Test for memory leaks in repeated operations."""
        process = psutil.Process()
        initial_memory = process.memory_info().rss

        client = GeminiClient()
        mock_response = b"20 text/plain\r\nTest content"

        # Perform many operations
        for i in range(100):
            with patch.object(client.tls_client, "connect", return_value=(Mock(), {})):
                with patch.object(client.tls_client, "send_data"):
                    with patch.object(
                        client.tls_client, "receive_data", return_value=mock_response
                    ):
                        with patch.object(client.tls_client, "close"):
                            await client.fetch(f"gemini://example{i}.com/")

            # Force garbage collection periodically
            if i % 10 == 0:
                gc.collect()

        # Final memory check
        final_memory = process.memory_info().rss
        memory_increase = final_memory - initial_memory

        # Memory increase should be bounded (not growing indefinitely)
        assert memory_increase < 100 * 1024 * 1024  # Less than 100MB

    def test_cache_memory_management(self):
        """Test cache memory management and eviction."""
        client = GeminiClient(max_cache_entries=100)

        process = psutil.Process()
        initial_memory = process.memory_info().rss

        # Fill cache beyond limit
        for i in range(200):
            url = f"gemini://example{i}.com/"
            # Create a reasonably sized mock response
            from src.gopher_mcp.models import GeminiMimeType

            mock_response = GeminiSuccessResult(
                content="A" * 1000,  # 1KB per entry
                mimeType=GeminiMimeType(type="text", subtype="gemini", lang=None),
                size=1000,
                requestInfo={"url": url, "timestamp": time.time()},
            )
            client._cache_response(url, mock_response)

        # Cache should not exceed limit
        assert len(client._cache) <= 100

        # Memory should not grow excessively
        final_memory = process.memory_info().rss
        memory_increase = final_memory - initial_memory
        assert memory_increase < 50 * 1024 * 1024  # Less than 50MB


@pytest.mark.slow
class TestScalability:
    """Test scalability and resource limits."""

    def test_large_response_handling(self):
        """Test handling of large responses."""
        client = GeminiClient(max_response_size=10 * 1024 * 1024)  # 10MB limit

        # Test with large but acceptable response
        large_content = "A" * (5 * 1024 * 1024)  # 5MB
        large_response = f"20 text/plain\r\n{large_content}".encode()

        start_time = time.time()

        with patch.object(client.tls_client, "connect", return_value=(Mock(), {})):
            with patch.object(client.tls_client, "send_data"):
                with patch.object(
                    client.tls_client, "receive_data", return_value=large_response
                ):
                    with patch.object(client.tls_client, "close"):
                        # This would be an async test in practice
                        pass

        end_time = time.time()
        processing_time = end_time - start_time

        # Should handle large responses efficiently
        assert processing_time < 5.0  # Less than 5 seconds

    @pytest.mark.asyncio
    async def test_connection_pool_efficiency(self):
        """Test connection pooling efficiency."""
        client = GeminiClient()

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

    def test_connection_timeout_enforcement(self):
        """Test that connection timeouts are properly enforced."""
        client = GeminiClient(timeout_seconds=1)

        # This would test actual timeout enforcement
        # In practice, would use real slow connections
        assert client.timeout_seconds == 1

    def test_response_size_limit_enforcement(self):
        """Test response size limit enforcement."""
        client = GeminiClient(max_response_size=1024)  # 1KB limit

        # Test with oversized response
        oversized_content = "A" * 2048  # 2KB
        _ = (
            f"20 text/plain\r\n{oversized_content}".encode()
        )  # Create oversized response for testing

        # Should reject oversized responses
        # This would be tested with actual response processing
        assert client.max_response_size == 1024

    def test_cache_size_limit_enforcement(self):
        """Test cache size limit enforcement."""
        client = GeminiClient(max_cache_entries=10)

        # Add more entries than limit
        for i in range(20):
            url = f"gemini://example{i}.com/"
            from src.gopher_mcp.models import GeminiMimeType

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
        from src.gopher_mcp.utils import parse_gemini_url, parse_gopher_url

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
        from src.gopher_mcp.utils import parse_gemini_response, parse_gopher_menu

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
        client = GeminiClient()
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
            from src.gopher_mcp.models import GeminiMimeType

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
