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

### F3: Gemini free tier allows 20 requests a day on 3.x Flash, and the limit is not documented
- Tool/API: Gemini API (Google AI Studio free tier), `gemini-3.5-flash`
- Task attempted: Run the Kilta golden conversations against the real model to prove the agent works.
- Steps taken: Pointed the Strands `GeminiModel` at `gemini-3.5-flash` and ran a few scenarios. After about 10 turns every call returned 429.
- Expected: The "modest" free-tier limits of the rate-limits page; enough for a few conversations.
- Actual: `429 RESOURCE_EXHAUSTED ... Quota exceeded for metric: generate_content_free_tier_requests, limit: 20, model: gemini-3.6-flash. Please retry in 8h56m12s.` The alias `gemini-3.5-flash` counts against `gemini-3.6-flash`, and the rate-limits documentation page shows no free-tier numbers (only the dashboard does). `gemini-flash-latest` also hung for 40 s or returned 503 that day, and `gemini-2.5-*` returned 404.
- Severity: High
- Workaround: Pinned `gemini-3.5-flash-lite` (500 requests a day) as the primary model, kept Flash as a fallback, added a Groq link and a local Ollama link, and made the chain skip a model for hours when its error says the daily quota is spent.
- Actionable suggestion: Put the free-tier requests-per-day and tokens-per-minute for each model in the public rate-limits table, and say in the 429 body which alias resolved to which model.

### F4: Groq free tier is 8,000 tokens a minute, which one agent call can nearly fill
- Tool/API: Groq API (OpenAI-compatible), `openai/gpt-oss-120b`
- Task attempted: Use Groq as the second link of the fallback chain.
- Steps taken: Sent the Kilta system prompt plus 24 tool specs and the conversation so far.
- Expected: A usable free fallback for a tool-calling agent.
- Actual: `429 Too Many Requests` after the second call in a minute; `x-ratelimit-limit-tokens: 8000` and a single call measured 3,327 prompt tokens before history. A turn of three calls took about 90 s.
- Severity: Medium
- Workaround: Trimmed the system prompt and tool descriptions and sent only the tools that fit the current state (1,400 to 1,800 tokens per call instead of 3,300), and paced calls. Groq stays a best-effort fallback.
- Actionable suggestion: Show the tokens-per-minute limit per model on the model list endpoint, and count only input tokens (not `max_tokens`) against it for free-tier users.

### F5: strands-agents resolves to the MCP Python SDK v2 unless you pin it
- Tool/API: Strands Agents SDK 1.62.0, MCP Python SDK
- Task attempted: Add Strands to a project that must stay on MCP spec 2025-11-25 and the v1 SDK (`mcp>=1.27,<2`).
- Steps taken: `uv add "strands-agents[gemini,openai,ollama]"` in `bridge/`.
- Expected: A resolver result compatible with the v1 SDK, or a warning.
- Actual: Strands allows `mcp<2.2`, so `uv` installed `mcp 2.1.1` (the v2 line). Pinning `mcp>=1.27,<2` alongside it resolves to 1.30.0 and works, and Strands then prints `DeprecationWarning: Use streamable_http_client instead` on every connection.
- Severity: Medium
- Workaround: Pin the MCP SDK in `bridge/pyproject.toml` with a comment, and assert the negotiated protocol version `2025-11-25` in tests.
- Actionable suggestion: Document which MCP SDK lines each Strands release supports, and move Strands to `streamable_http_client` so the v1 line is warning-free.

### F6: Strands' Gemini provider announces the message before the request has succeeded
- Tool/API: Strands Agents SDK, `GeminiModel.stream`
- Task attempted: Fall back to another model when Gemini returns 400 or 429.
- Steps taken: Wrote a `Model` wrapper that tries the next provider if the first raises before streaming; tested with an invalid API key.
- Expected: The error raised before any content, so a wrapper can switch providers.
- Actual: The provider yields `messageStart` first and raises afterwards, so a wrapper that treats the first event as "started" re-raises the error instead of failing over. The fake models in our tests raised before yielding, so only the live test with a bad key showed it.
- Severity: Medium
- Workaround: The chain holds back `messageStart` until a content event arrives.
- Actionable suggestion: Raise provider errors before yielding `messageStart`, or document that the first event is not a success signal.

### F7: `uv sync` before `src/` exists leaves the package uninstalled
- Tool/API: uv 0.13.4 with hatchling
- Task attempted: Create `bridge/pyproject.toml`, run `uv sync`, then add `src/kilta_bridge/`.
- Steps taken: `uv sync` first, then wrote the package, then `uv run pytest`.
- Expected: The editable install picks up the package once it exists.
- Actual: `ModuleNotFoundError: No module named 'kilta_bridge'`. `uv sync` reported "Checked 71 packages" and did not reinstall.
- Severity: Low
- Workaround: `uv sync --reinstall-package kilta-bridge`.
- Actionable suggestion: Warn when a project builds an empty wheel, or reinstall when the package directory appears.
