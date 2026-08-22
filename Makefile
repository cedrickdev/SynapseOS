# SynapseOS — developer commands (Phase 1)
# Run `make help` to list available targets.

.DEFAULT_GOAL := help
VENV ?= .venv
BIN := $(VENV)/bin

.PHONY: help venv install dev test lint format typecheck check up down clean

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

venv: ## Create a local Python 3.12 virtualenv (uses uv if available)
	uv venv --python 3.12 $(VENV) || python3 -m venv $(VENV)

install: ## Install the project with dev dependencies into the venv
	uv pip install --python $(VENV) -e ".[dev]" || $(BIN)/pip install -e ".[dev]"

dev: ## Run the API locally with autoreload
	$(BIN)/uvicorn apps.api.main:app --reload --host 0.0.0.0 --port 8000

test: ## Run the test suite
	$(BIN)/pytest

lint: ## Run the Ruff linter
	$(BIN)/ruff check .

format: ## Format the code with Ruff
	$(BIN)/ruff format .

typecheck: ## Run the mypy type checker
	$(BIN)/mypy .

check: lint typecheck test ## Run lint + typecheck + tests

up: ## Start API + PostgreSQL via Docker Compose
	docker compose up --build

down: ## Stop and remove Docker Compose services
	docker compose down

clean: ## Remove virtualenv and tooling caches
	rm -rf $(VENV) .pytest_cache .mypy_cache .ruff_cache
