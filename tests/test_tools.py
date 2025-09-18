"""Tests for gopher_mcp.tools module."""

from mcp.types import Tool

from gopher_mcp.tools import create_gopher_fetch_tool, create_gemini_fetch_tool


class TestCreateGopherFetchTool:
    """Test the create_gopher_fetch_tool function."""

    def test_create_gopher_fetch_tool_returns_tool(self):
        """Test that create_gopher_fetch_tool returns a Tool instance."""
        tool = create_gopher_fetch_tool()

        assert isinstance(tool, Tool)

    def test_create_gopher_fetch_tool_name(self):
        """Test that the tool has the correct name."""
        tool = create_gopher_fetch_tool()

        assert tool.name == "gopher.fetch"

    def test_create_gopher_fetch_tool_description(self):
        """Test that the tool has a proper description."""
        tool = create_gopher_fetch_tool()

        assert tool.description is not None
        assert len(tool.description) > 0
        assert "Fetch Gopher menus or text by URL" in tool.description
        assert "Supports all standard Gopher item types" in tool.description
        assert "structured JSON responses" in tool.description

    def test_create_gopher_fetch_tool_input_schema(self):
        """Test that the tool has the correct input schema."""
        tool = create_gopher_fetch_tool()

        assert tool.inputSchema is not None
        assert tool.inputSchema["type"] == "object"
        assert "url" in tool.inputSchema["required"]
        assert "url" in tool.inputSchema["properties"]

        url_property = tool.inputSchema["properties"]["url"]
        assert url_property["type"] == "string"
        assert url_property["format"] == "uri"
        assert url_property["pattern"] == "^gopher://"

    def test_create_gopher_fetch_tool_url_property_details(self):
        """Test the URL property has proper description and examples."""
        tool = create_gopher_fetch_tool()

        url_property = tool.inputSchema["properties"]["url"]

        assert "description" in url_property
        assert "Full Gopher URL to fetch" in url_property["description"]
        assert "examples" in url_property

        examples = url_property["examples"]
        assert len(examples) >= 3
        assert any("gopher://gopher.floodgap.com/1/" in example for example in examples)
        assert any("gopher://gopher.floodgap.com/0/" in example for example in examples)
        assert any("search" in example for example in examples)

    def test_create_gopher_fetch_tool_no_additional_properties(self):
        """Test that the input schema doesn't allow additional properties."""
        tool = create_gopher_fetch_tool()

        assert tool.inputSchema["additionalProperties"] is False

    def test_create_gopher_fetch_tool_examples_are_valid_gopher_urls(self):
        """Test that all examples are valid Gopher URLs."""
        tool = create_gopher_fetch_tool()

        examples = tool.inputSchema["properties"]["url"]["examples"]

        for example in examples:
            assert example.startswith("gopher://")
            assert "://" in example
            # Basic URL structure validation
            parts = example.split("://", 1)
            assert len(parts) == 2
            assert parts[0] == "gopher"

    def test_create_gopher_fetch_tool_description_mentions_types(self):
        """Test that the description mentions supported Gopher types."""
        tool = create_gopher_fetch_tool()

        description = tool.description
        assert "type 1" in description  # menus
        assert "type 0" in description  # text files
        assert "type 7" in description  # search servers
        assert "binary files" in description

    def test_create_gopher_fetch_tool_description_mentions_llm_optimization(self):
        """Test that the description mentions LLM optimization."""
        tool = create_gopher_fetch_tool()

        description = tool.description
        assert "optimized for LLM consumption" in description

    def test_create_gopher_fetch_tool_url_description_has_examples(self):
        """Test that the URL description includes inline examples."""
        tool = create_gopher_fetch_tool()

        url_description = tool.inputSchema["properties"]["url"]["description"]

        # Should have inline examples in the description
        assert "gopher://gopher.floodgap.com/1/" in url_description
        assert "gopher://gopher.floodgap.com/0/" in url_description
        assert "search" in url_description

    def test_create_gopher_fetch_tool_consistent_examples(self):
        """Test that examples in description match examples array."""
        tool = create_gopher_fetch_tool()

        url_property = tool.inputSchema["properties"]["url"]
        description = url_property["description"]
        examples_array = url_property["examples"]

        # Examples mentioned in description should be in examples array
        for example in examples_array:
            if "gopher.floodgap.com" in example:
                assert example in description or any(
                    part in description for part in example.split("/")
                )


class TestCreateGeminiFetchTool:
    """Test the create_gemini_fetch_tool function."""

    def test_create_gemini_fetch_tool_returns_tool(self):
        """Test that create_gemini_fetch_tool returns a Tool instance."""
        tool = create_gemini_fetch_tool()

        assert isinstance(tool, Tool)

    def test_create_gemini_fetch_tool_name(self):
        """Test that the tool has the correct name."""
        tool = create_gemini_fetch_tool()

        assert tool.name == "gemini.fetch"

    def test_create_gemini_fetch_tool_description(self):
        """Test that the tool has a proper description."""
        tool = create_gemini_fetch_tool()

        assert tool.description is not None
        assert len(tool.description) > 0
        assert "Fetch Gemini content by URL" in tool.description
        assert "TLS" in tool.description
        assert "TOFU certificate validation" in tool.description
        assert "gemtext parsing" in tool.description

    def test_create_gemini_fetch_tool_input_schema(self):
        """Test that the tool has the correct input schema."""
        tool = create_gemini_fetch_tool()

        assert tool.inputSchema is not None
        assert tool.inputSchema["type"] == "object"
        assert "url" in tool.inputSchema["required"]
        assert "url" in tool.inputSchema["properties"]

        url_property = tool.inputSchema["properties"]["url"]
        assert url_property["type"] == "string"
        assert url_property["format"] == "uri"
        assert url_property["pattern"] == "^gemini://"

    def test_create_gemini_fetch_tool_examples_are_valid(self):
        """Test that all examples are valid Gemini URLs."""
        tool = create_gemini_fetch_tool()

        examples = tool.inputSchema["properties"]["url"]["examples"]

        for example in examples:
            assert example.startswith("gemini://")
            assert "://" in example
            # Basic URL structure validation
            parts = example.split("://", 1)
            assert len(parts) == 2
            assert parts[0] == "gemini"

    def test_create_gemini_fetch_tool_no_additional_properties(self):
        """Test that the input schema doesn't allow additional properties."""
        tool = create_gemini_fetch_tool()

        assert tool.inputSchema["additionalProperties"] is False
