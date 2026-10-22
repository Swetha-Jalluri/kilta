# Friction log

Format per entry (required by the hackathon for the bonus):
### F<n>: <short title>
- Tool/API: 
- Task attempted: 
- Steps taken: 
- Expected: 
- Actual: 
- Severity: Critical / High / Medium / Low
- Workaround: 
- Actionable suggestion: 

### F1: Alexa+ MCP Toolkit requires Private Preview approval
- Tool/API: Alexa+ MCP Toolkit, Alexa AI CLI
- Task attempted: Connect the Kilta MCP server to real Alexa+ during the hackathon.
- Steps taken: Read the MCP Toolkit overview and quickstart; requested Private Preview access.
- Expected: Hackathon participants could test their MCP server on Alexa+ (or a public simulator).
- Actual: (fill in: approval status by deadline)
- Severity: High
- Workaround: Built a simulated Alexa+ host (Strands agent + web simulator) that uses the same MCP server unchanged.
- Actionable suggestion: Give hackathon registrants fast-track preview access or a hosted Alexa+ MCP test console.

### F2: `uv run` warns about VIRTUAL_ENV mismatch when pyenv or conda is active
- Tool/API: uv 0.13.4 (`uv run`, `uv sync`)
- Task attempted: Run the Kilta server tests and linter through `uv run` inside `server/`, which has its own `.venv`.
- Steps taken: On macOS with pyenv active (`VIRTUAL_ENV=/Users/Admin/.pyenv/versions/3.12.0`), ran `cd server && uv sync`, then `uv run python -c "import mcp"`, `uv run ruff check .` and `uv run pytest -q`.
- Expected: `uv run` uses the project's `.venv` quietly. An unrelated environment variable from the shell should not matter.
- Actual: Every `uv run` call prints "warning: `VIRTUAL_ENV=/Users/Admin/.pyenv/versions/3.12.0` does not match the project environment path `.venv` and will be ignored; use `--active` to target the active environment instead". It repeats on every call, including those from `make test` and `make check`, and mixes into test and lint output (I had to pipe through `grep -v VIRTUAL` to read results).
- Severity: Low
- Workaround: Filter the line with `grep -v VIRTUAL_ENV` locally, or `unset VIRTUAL_ENV` before running make. CI is not affected because it has no pre-activated environment.
- Actionable suggestion: Print this warning once per shell session, or only when `--active` or `--verbose` is set, since uv already ignores the variable. If it stays, add a `UV_NO_ENV_WARNING`-style switch (or a `[tool.uv]` setting) so a Makefile can silence it for contributors who use pyenv or conda.
