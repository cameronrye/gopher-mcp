# GitHub Wiki Content

This directory contains the content for the Gopher & Gemini MCP Server GitHub Wiki.

## Setup Instructions

### Step 1: Enable Wiki

1. Go to your repository on GitHub: <https://github.com/cameronrye/gopher-mcp>
2. Click on "Settings"
3. Scroll down to "Features"
4. Ensure "Wikis" is checked (it should already be enabled)

### Step 2: Create Initial Wiki Page

1. Go to the Wiki tab: <https://github.com/cameronrye/gopher-mcp/wiki>
2. Click "Create the first page"
3. Copy the content from `Home.md` in this directory
4. Paste it into the wiki editor
5. Click "Save Page"

### Step 3: Clone Wiki Repository

Once the first page is created, you can clone the wiki repository:

```bash
# Clone the wiki repository
git clone https://github.com/cameronrye/gopher-mcp.wiki.git

# Navigate to the wiki directory
cd gopher-mcp.wiki
```

### Step 4: Add All Wiki Pages

Copy all the markdown files from this directory to the wiki repository:

```bash
# From the gopher-mcp directory
cp wiki-content/*.md ../gopher-mcp.wiki/

# Navigate to wiki repository
cd ../gopher-mcp.wiki

# Add all files
git add .

# Commit
git commit -m "Add comprehensive wiki documentation"

# Push to GitHub
git push origin master
```

### Step 5: Verify

Visit your wiki at: <https://github.com/cameronrye/gopher-mcp/wiki>

## Wiki Pages

The following pages are included:

1. **Home.md** - Main wiki homepage with navigation
2. **Installation.md** - Complete installation guide
3. **Configuration.md** - Configuration options and examples
4. **API-Reference.md** - Complete API documentation
5. **Contributing.md** - Contributing guidelines
6. **Usage-Examples.md** - Practical usage examples
7. **Troubleshooting.md** - Common issues and solutions
8. **Architecture.md** - System architecture overview
9. **Gopher-Protocol.md** - Gopher protocol guide
10. **Gemini-Protocol.md** - Gemini protocol guide
11. **Security-Features.md** - Security features documentation
12. **Advanced-Features.md** - Advanced configuration and features

## Page Naming Convention

GitHub Wiki uses the filename (without .md extension) as the page title and URL:

- `Home.md` → Home page
- `Installation.md` → Installation page
- `API-Reference.md` → API-Reference page (note the hyphen)

## Updating Wiki Pages

To update wiki pages:

```bash
# Navigate to wiki repository
cd gopher-mcp.wiki

# Make your changes to the markdown files

# Commit and push
git add .
git commit -m "Update wiki documentation"
git push origin master
```

## Wiki Features

- **Markdown Support**: Full GitHub Flavored Markdown
- **Automatic Linking**: `[[Page Name]]` creates links between pages
- **Table of Contents**: Automatically generated from headings
- **Search**: Built-in search functionality
- **History**: Full revision history for all pages

## Customization

The wiki pages follow these conventions:

- No emoji except ❤️ in the footer
- Footer format: "Made with ❤️ by [Cameron Rye](https://rye.dev/)"
- Consistent heading structure
- Code blocks with language specification
- Tables for structured data
- Links to external resources

## Maintenance

To keep the wiki up to date:

1. Update wiki-content files in the main repository
2. Copy updated files to the wiki repository
3. Commit and push changes
4. Verify changes on GitHub

## Alternative: Manual Upload

If you prefer to create pages manually through the GitHub web interface:

1. Go to <https://github.com/cameronrye/gopher-mcp/wiki>
2. Click "New Page"
3. Enter the page title (e.g., "Installation")
4. Copy content from the corresponding .md file
5. Click "Save Page"
6. Repeat for all pages

## Links Between Pages

The wiki uses standard markdown links:

```markdown
[Installation](Installation)
[API Reference](API-Reference)
[Configuration](Configuration)
```

GitHub Wiki automatically converts these to proper wiki links.

---

Made with ❤️ by [Cameron Rye](https://rye.dev/)
