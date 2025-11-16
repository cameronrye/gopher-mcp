# Usage Examples

This guide provides practical examples of using the Gopher & Gemini MCP Server with AI assistants.

## Gopher Protocol Examples

### Browsing Gopher Menus

Ask your AI assistant:

> "Browse the main Gopher menu at gopher.floodgap.com"

This will fetch and display the menu structure from the classic Floodgap Gopher server.

**Example URL:**

```
gopher://gopher.floodgap.com/1/
```

### Reading Text Files

Ask your AI assistant:

> "Show me the welcome text from Floodgap's Gopher server"

**Example URL:**

```
gopher://gopher.floodgap.com/0/gopher/welcome
```

### Searching Gopher

Ask your AI assistant:

> "Search for 'python' on the Veronica-2 search server"

**Example URL:**

```
gopher://gopher.floodgap.com/7/v2/vs?python
```

### Exploring Directories

Ask your AI assistant:

> "What's available in the Gopher community directory?"

**Example URL:**

```
gopher://gopher.floodgap.com/1/gopher
```

## Gemini Protocol Examples

### Browsing Gemini Pages

Ask your AI assistant:

> "Fetch the Gemini protocol homepage"

**Example URL:**

```
gemini://geminiprotocol.net/
```

### Reading Gemini Content

Ask your AI assistant:

> "Show me the software directory on geminiprotocol.net"

**Example URL:**

```
gemini://geminiprotocol.net/software/
```

### Exploring Gemlogs

Ask your AI assistant:

> "Browse the latest posts from the Antenna gemlog aggregator"

**Example URL:**

```
gemini://warmedal.se/~antenna/
```

### Gemini Search

Ask your AI assistant:

> "Search for content on Kennedy's Gemini search"

**Example URL:**

```
gemini://kennedy.gemi.dev/
```

## Advanced Examples

### Comparing Protocols

Ask your AI assistant:

> "What's the difference between Gopher and Gemini protocols? Show me examples from both."

### Content Discovery

Ask your AI assistant:

> "Find interesting content on Gopherspace related to vintage computing"

### Protocol Features

Ask your AI assistant:

> "Demonstrate the different Gopher item types available on gopher.floodgap.com"

## Common Use Cases

### Research and Learning

- Exploring historical internet protocols
- Learning about alternative internet communities
- Researching vintage computing and early internet culture

### Content Discovery

- Finding unique content not available on the modern web
- Discovering minimalist, text-focused resources
- Exploring decentralized and privacy-focused content

### Development and Testing

- Testing MCP server implementations
- Developing Gopher/Gemini clients
- Experimenting with protocol features

## Popular Gopher Servers

| Server      | URL                               | Description                                  |
| ----------- | --------------------------------- | -------------------------------------------- |
| Floodgap    | `gopher://gopher.floodgap.com/1/` | Classic Gopher server with extensive content |
| Quux.org    | `gopher://quux.org/1/`            | Long-running Gopher server                   |
| Gopher Lawn | `gopher://gopherlawn.net/1/`      | Community Gopher server                      |

## Popular Gemini Servers

| Server          | URL                              | Description                   |
| --------------- | -------------------------------- | ----------------------------- |
| Gemini Protocol | `gemini://geminiprotocol.net/`   | Official Gemini protocol site |
| Antenna         | `gemini://warmedal.se/~antenna/` | Gemlog aggregator             |
| Kennedy         | `gemini://kennedy.gemi.dev/`     | Gemini search engine          |

## Tips for AI Interactions

### Be Specific

Instead of: "Browse Gopher"
Try: "Browse the main menu at gopher://gopher.floodgap.com/1/"

### Ask for Explanations

"Explain what this Gopher menu item type means"
"What is the structure of this Gemini page?"

### Request Comparisons

"Compare the content structure between Gopher and Gemini"
"Show me how the same content looks in both protocols"

### Explore Incrementally

Start with main menus, then drill down into specific directories or pages.

## Troubleshooting Examples

If you encounter issues, ask:

- "Why can't I access this Gopher server?"
- "What does this Gemini status code mean?"
- "How do I handle this certificate error?"

See the [Troubleshooting](Troubleshooting) guide for more details.

---

Made with ❤️ by [Cameron Rye](https://rye.dev/)
