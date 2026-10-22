.PHONY: dev test reset check

# Server only for now; bridge and web are added in their phases.
dev:
	cd server && uv run kilta-server

test:
	cd server && uv run pytest -q
	@if [ -f bridge/pyproject.toml ]; then cd bridge && uv run pytest -q; fi
	@if [ -f web/package.json ]; then cd web && npm test --if-present; fi

# Back to the pristine demo: drop runtime sessions and repair history.
reset:
	rm -rf data/sessions data/state
	@echo "Demo data restored."

check:
	cd server && uv run ruff check . && uv run ruff format --check .
	@if [ -f bridge/pyproject.toml ]; then cd bridge && uv run ruff check . && uv run ruff format --check .; fi
	$(MAKE) test
	@if [ -f web/package.json ]; then cd web && npm run build; fi
