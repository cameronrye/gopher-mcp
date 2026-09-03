#!/usr/bin/env bash
#
# Post-build guard for the documentation site.
#
# Why this exists: `mkdocs build --strict` does not check that anything
# rendered *correctly*, only that nothing warned. mkdocs.yml registers the
# mermaid diagram fence through pymdownx.superfences with the YAML tag
# `format: !!python/name:pymdownx.superfences.fence_code_format`. If that tag
# is ever re-quoted into a plain string -- which is exactly what happened, and
# shipped the landing page's architecture diagram as a wall of literal
# `graph TB` markup for a year -- pymdownx silently declines to register the
# custom fence and emits an ordinary `<code>` block instead. The build stays
# green, the site stays broken, and only a human looking at the page notices.
#
# So assert the rendered output rather than the config: the landing page must
# contain a real mermaid block and must not contain the raw-text fallback.
#
# Usage: scripts/check-docs-render.sh [site-dir]   (default: site)

set -euo pipefail

site_dir="${1:-site}"
index="${site_dir}/index.html"

if [[ ! -f "${index}" ]]; then
  echo "check-docs-render: ${index} not found - build the docs first" >&2
  exit 1
fi

status=0

if ! grep -q '<pre class="mermaid">' "${index}"; then
  echo "::error file=mkdocs.yml::${index} contains no rendered '<pre class=\"mermaid\">' block. The architecture diagram on the landing page has regressed to literal text. Check that markdown_extensions.pymdownx.superfences.custom_fences still sets 'format: !!python/name:pymdownx.superfences.fence_code_format' as an unquoted YAML tag, not a quoted string." >&2
  status=1
fi

if grep -q '<code>mermaid' "${index}"; then
  echo "::error file=mkdocs.yml::${index} contains a literal '<code>mermaid' block, i.e. a mermaid fence rendered as source text instead of a diagram." >&2
  status=1
fi

if [[ ${status} -eq 0 ]]; then
  echo "check-docs-render: landing-page mermaid diagram rendered correctly"
fi

exit "${status}"
