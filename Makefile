# Cross-platform Makefile for gopher-mcp
# Unified Python task runner - passes all commands to task.py via uv
# Usage: make <command>

.DEFAULT_GOAL := help

# Catch-all target that passes any command to the Python task runner via uv
%:
	@uv run python task.py $@
