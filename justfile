# Zipy tasks. Running just with no arguments lists them.

set shell := ["bash", "-euo", "pipefail", "-c"]

compose := "docker compose -f deploy/compose.yml"

default:
    @just --list --unsorted

# ---------- first run ----------

# Check required tools, the repo setup, secrets and services
doctor:
    ./scripts/doctor.sh

# Everything a fresh clone needs: .env, git hooks, dependencies, the website's too
bootstrap: env hooks setup web-setup
    @echo "ready: fill .env, then 'just up', 'just migrate', 'just serve'"

# Install every app
setup:
    uv sync --locked --all-packages

# Re-resolve uv.lock after changing dependencies in any pyproject.toml
lock:
    uv lock

# Print a new Fernet key for ZIPY_DATA__FERNET_KEY
fernet-key:
    uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

[private]
env:
    @[ -f .env ] && echo ".env exists" || { cp .env.example .env && echo "created .env"; }

[private]
hooks:
    git config core.hooksPath .githooks

# ---------- the gate ----------

# The gate: the Python apps and the website. CI and the hook run the half that changed.
check: check-python check-website
    @echo "ok"

# Format check, lint, layering, types, tests for the engine and the console
check-python: fmt-check lint deps types test check-workflows

# actionlint over every workflow
check-workflows:
    uvx --from actionlint-py actionlint

# eslint and tsc over the website
check-website:
    cd apps/website && npm run lint && npm run typecheck

# Format in place
fmt:
    uvx ruff format .
    uvx ruff check --fix .
    cd apps/website && npx eslint . --fix

# Tests without services; MODE=integration runs the ones that need postgres and redis
test MODE="":
    #!/usr/bin/env bash
    set -euo pipefail
    case "{{MODE}}" in
      "") uv run pytest -q -m "not integration" ;;
      integration)
        # These tests drop every table of this database, so it is never the one zipy runs against.
        if [ -z "${ZIPY_TEST_DATABASE_URL:-}" ]; then
          echo "set ZIPY_TEST_DATABASE_URL to a throwaway database, for example"
          echo "  createdb zipy_test && export ZIPY_TEST_DATABASE_URL=postgresql+asyncpg://zipy:zipy@127.0.0.1:5432/zipy_test"
          exit 1
        fi
        uv run pytest -q -m integration -rs ;;
      *) echo "MODE is integration"; exit 1 ;;
    esac

[private]
fmt-check:
    uvx ruff format --check .

[private]
lint:
    uvx ruff check .

[private]
deps:
    ./scripts/check-deps.sh

[private]
types:
    uv run mypy

# ---------- the engine ----------

# Every enabled platform, the HTTP server and the workers, in one process
serve *ARGS:
    uv run zipy serve {{ARGS}}

# Talk to Zipy in this terminal through the local platform; no chat app needed
chat *ARGS:
    uv run zipy chat {{ARGS}}

# The newest request traces, or one request's events in order
traces *ARGS:
    uv run zipy traces {{ARGS}}

# Apply database migrations up to head
migrate *ARGS="upgrade head":
    uv run zipy db {{ARGS}}

# A new migration generated from the models
revision MESSAGE:
    uv run zipy db revision "{{MESSAGE}}"

# Every platform, provider and tool plugin, checked against zipy.toml
plugins:
    uv run zipy plugins

# The resolved configuration, or one table of it
config *ARGS:
    uv run zipy config {{ARGS}}

# Any zipy command
zipy *ARGS:
    uv run zipy {{ARGS}}

# ---------- the services ----------

# Start compose services: postgres and redis by default; langfuse, prometheus, grafana, uptime-kuma by name
up *SERVICES="postgres redis":
    {{compose}} --profile '*' up -d {{SERVICES}}

# Stop compose services by name, or every one of them
stop *SERVICES:
    {{compose}} --profile '*' stop {{SERVICES}}

# Stop and remove every compose service
down:
    {{compose}} --profile '*' down

# Follow the logs of compose services, all of them by default
logs *SERVICES:
    {{compose}} --profile '*' logs -f --tail 200 {{SERVICES}}

# ---------- the model layer ----------

# llama-server for chat (:8000) and embeddings (:8001) on the CPU; GGUFs download on first run
model *ARGS:
    {{compose}} --profile model up -d {{ARGS}} chat embed

# The same two servers on an NVIDIA card, with every layer offloaded to it
model-gpu *ARGS:
    ZIPY_CHAT_NGL="${ZIPY_CHAT_NGL:-99}" ZIPY_EMBED_NGL="${ZIPY_EMBED_NGL:-99}" \
      {{compose}} -f deploy/compose.gpu.yml --profile model up -d {{ARGS}} chat embed

# Stop and remove the model servers, keeping the downloaded GGUFs
model-down:
    {{compose}} --profile model rm -sf chat embed

# ---------- deployment ----------

# Production: the published image and every service, from the prod overlay
prod-up:
    {{compose}} -f deploy/compose.prod.yml --profile '*' up -d

prod-down:
    {{compose}} -f deploy/compose.prod.yml --profile '*' down

# ---------- website ----------

# Install the website's dependencies
web-setup:
    cd apps/website && npm ci

# The website's dev server at http://localhost:3000
web:
    cd apps/website && npm run dev

# The website's production build
web-build:
    cd apps/website && npm run build

# Build, then serve the production website
web-preview: web-build
    cd apps/website && npm run start

# Regenerate the website's logo animation from apps/cli/assets
web-frames:
    ./scripts/sync-ascii-frames.py

# ---------- console, docs and deploy ----------

# Developer console: run recipes, stream their logs, chat with Zipy, watch its metrics
console:
    uv run console

alias cli := console

# Processes and CPU in htop, full screen
htop:
    htop

# Render every mermaid diagram in the docs, so a broken one fails here and not on GitHub
diagrams:
    #!/usr/bin/env bash
    set -euo pipefail
    d=$(mktemp -d)
    for doc in docs/*.md README.md; do
      awk -v d="$d" -v n="$(basename "$doc" .md)" '/^```mermaid/{i++; f=d"/"n"-"i".mmd"; next} /^```/{f=""; next} f{print > f}' "$doc"
    done
    shopt -s nullglob
    for f in "$d"/*.mmd; do npx -y @mermaid-js/mermaid-cli@11 -i "$f" -o "${f%.mmd}.svg" -q && echo "ok $(basename "$f")"; done

# Build the zipy image
image:
    docker build -f deploy/Dockerfile --build-arg GIT_SHA=$(git rev-parse --short HEAD) -t zipy:dev .

# ---------- repository and releases ----------

# Branch rules and repository settings from .github: show the difference, or apply it
github MODE="plan":
    ./scripts/github.sh {{MODE}}

# Open a release: branch release/vVERSION with every version set and release notes to edit
release VERSION:
    ./scripts/release.sh bump {{VERSION}}

# After the release pull request is merged: tag main with its version and push the tag
tag:
    ./scripts/release.sh tag

clean:
    rm -rf .venv .mypy_cache .pytest_cache .ruff_cache .import_linter_cache
    find . -name '*.egg-info' -type d -prune -exec rm -rf {} +
    find . -name __pycache__ -type d -prune -exec rm -rf {} +
    rm -rf apps/website/node_modules apps/website/.next
