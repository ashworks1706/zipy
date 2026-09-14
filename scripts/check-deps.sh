#!/usr/bin/env bash
# The dependency rule: apps never import each other, and inside the engine
# core <- telemetry <- data <- {memory, tools, llm, auth} <- agent <- gateway <- {platforms, api, workers}
# <- wiring <- commands. Plugin isolation is apps/engine/tests/test_plugins.py.
# Contracts live in pyproject.toml [tool.importlinter]. Adding an edge means editing them and
# docs/ARCHITECTURE.md in the same change.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
uv run lint-imports --config pyproject.toml
