# Phase 2 progress (bridge + Strands agent)

Status: work in progress. `make check` passes (server 93 tests, bridge 48 tests, ruff clean).
The live golden tests have not yet run green end to end.

## Done
- `bridge/` uv project, committed `uv.lock`. Pins `mcp>=1.27,<2` (strands-agents 1.62 allows mcp 2.x, so
  an unpinned install pulls the v2 SDK) and `strands-agents[gemini,openai,ollama]`.
- FastAPI app (`app.py`): `POST /api/turn`, `GET /api/events` (SSE, optional `?replay=N`),
  `GET /api/health`, `POST /api/reset` (demo mode only; deletes `data/sessions` and `data/state`).
- `agent.py`: one Strands agent on the Kilta MCP server (Streamable HTTP). Each turn gets a context line
  (speaker, language, confidence, pace, active session). Tool calls are captured by hooks and streamed
  as SSE events. Card, state and session id come from the tool results, never from model text. A failed
  turn restores the conversation and answers with a spoken apology.
- `chain.py`: `FallbackModel` with order Gemini -> Groq -> Gemini Flash-Lite -> Ollama. Backoff retries
  for 429/5xx/timeouts, immediate skip for other errors (bad key), per-link first-token timeout, pacing
  (`KILTA_MODEL_MIN_INTERVAL`), and a cooldown so a dead model costs one wait, not one per model call.
- `prompt.py`: system prompt = operating rules + `docs/conversation-design.md`.
- Tests (always on): 48. Golden scenarios A, B, C replay through the real bridge and the real server
  (scripted model) and assert tool order, exact engine state and card facts. Also: chain retry/fallback/
  cooldown, SSE, reset, speaker switch, MCP server down, all models failing.
- Live tests written (`tests/test_live.py`, marker `live`): scenarios A, B, C, four danger answers (EN/ES,
  true/false), the withheld before-gate step not being spoken, and a bad-Gemini-key proof answered by Groq.
- `.env.example` updated with Groq and the new settings.

## Found along the way
- Gemini sends `messageStart` before a request has really succeeded, so a bad key or a 429 arrives after
  it. The chain treated that as "started" and could not fall back. Found by the first live run; fixed,
  with tests.
- On 2026-10-21 `gemini-flash-latest` hung or returned 503 under load, and `gemini-2.5-*` returned 404.
  `gemini-3.5-flash` (about 1.6 s) and `gemini-3.5-flash-lite` (about 0.6 s) work with tools. Defaults
  and `.env.example` are now pinned to those.
- Groq free tier is 8,000 tokens per minute per model. One Kilta model call is about 5,000 tokens (system
  prompt about 1,400, 24 tool schemas about 3,500, plus history), so Groq answers roughly one call a
  minute and 429s in between (a turn took about 90 s). It works as a rescue link, not a fast one.
- Gemini 3.x can reject history containing tool calls from another model ("missing a thought_signature").
  Seen once on `gemini-flash-latest`; a simple foreign-history probe passed on 3.5/3.6. Not yet reproduced
  on the pinned models.
- Strands still uses the deprecated `streamablehttp_client`.

## Left
1. Run the live tests and fix what they show: bad-key proof, danger answers, scenarios A, B, C. Keep them
   paced (`KILTA_LIVE_PACE`, default 4 s). Paste the output as the "Done when" evidence.
2. `make dev` should also start the bridge on :8000; add `make test-live`; add the bridge to CI
   (`uv sync --frozen` in `bridge/`).
3. Decide whether to shrink the per-call token load (compact tool schemas, shorter prompt) so Groq is
   more than a rescue link.
4. Your `.env` may still set `KILTA_MODEL_PRIMARY=gemini-flash-latest` (it overrides the new defaults);
   update it to the IDs in `.env.example`.
5. Reviewer subagent on the diff, fix correctness/safety findings, final commit.
6. Log: `/friction` (uv sync before `src/` exists leaves the package uninstalled; `gemini-flash-latest`
   overloaded; Groq 8k TPM) and `/feedback` (Strands, Gemini, Groq).
