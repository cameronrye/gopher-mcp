# Cross-platform Makefile for gopher-mcp
# Unified Python task runner - passes all commands to task.py
# Usage: make <command>

.DEFAULT_GOAL := help

# Catch-all target that passes any command to the Python task runner
%:
	@python task.py $@
