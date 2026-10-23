.PHONY: dev test test-live reset check

DATA_DIR ?= data

# Server :8765 and bridge :8000 (web joins in Phase 3). Ctrl-C stops both.
dev:
	@trap 'kill 0' INT TERM EXIT; \
	if [ -f .env ]; then set -a; . ./.env; set +a; fi; \
	(cd server && uv run kilta-server) & \
	(cd bridge && uv run kilta-bridge) & \
	wait

test:
	cd server && uv run pytest -q
	@if [ -f bridge/pyproject.toml ]; then cd bridge && uv run pytest -q; fi
	@if [ -f web/package.json ]; then cd web && npm test --if-present; fi

# Golden conversations with the real models (needs GEMINI_API_KEY and GROQ_API_KEY in .env).
# Slow on purpose: calls are paced for free-tier limits. Pass ARGS='-k scenario_a' to pick one.
test-live:
	cd bridge && uv run pytest -m live -s -q $(ARGS)

# Back to the pristine demo: drop runtime sessions and repair history.
reset:
	rm -rf $(DATA_DIR)/sessions $(DATA_DIR)/state
	@echo "Demo data restored."

check:
	cd server && uv run ruff check . && uv run ruff format --check .
	@if [ -f bridge/pyproject.toml ]; then cd bridge && uv run ruff check . && uv run ruff format --check .; fi
	$(MAKE) test
	@if [ -f web/package.json ]; then cd web && npm run build; fi
