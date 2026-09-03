# Cross-platform Makefile for gopher-mcp
# Thin catch-all onto taskipy, whose table in pyproject.toml is the single
# definition of every task. There is no second task table to keep in sync:
# task.py used to hold a hand-maintained copy that nothing compared and that
# had already drifted from this one. Add tasks under
# [tool.taskipy.tasks] in pyproject.toml, not here.
# Usage: make <command>   (equivalently: uv run task <command>)

.DEFAULT_GOAL := help

# Catch-all target that passes any command straight to taskipy via uv
%:
	@uv run task $@
