# Phase 2 progress (bridge + Strands agent)

Status: work in progress. `make check` passes (server 93 tests, bridge 53 tests, ruff clean).
Blocked on free-tier model quota: the live golden scenarios A, B, C have not run end to end.

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

## Since the first note (2026-10-22)
- `make dev` starts server :8765 and bridge :8000; `make test-live` (`ARGS='-k scenario_c'` picks one);
  the bridge is in CI.
- Host guard in the bridge: a turn may not both ask the user something (safety question, gate) and
  answer it. Found live: gpt-oss on Groq answered the safety question itself ("No, there's no burning")
  in the same turn it asked it. The bridge now cancels `safety_check(false)` and `confirm_gate(true)`
  after a question or gate was presented in that turn; reporting danger is always allowed. The server
  cannot enforce this because MCP has no notion of a user turn.
- Chain: a spent daily quota ("Please retry in 8h56m") is not retried, and the model is skipped for up to
  6 hours.
- Live results so far (Gemini 3.5 Flash answering): the four danger answers all produced the right
  `danger_reported` boolean (yes/sí -> true -> STOPPED; no/no huele a nada -> false -> carried on). The
  bad-Gemini-key proof passed: Groq answered, the Gemini failure was recorded as non-retryable.

## Blocking finding: the Gemini free tier is about 20 requests per day
`gemini-3.5-flash` resolves to `gemini-3.6-flash`, whose free-tier limit is **20 requests per day per
model** ("limit: 20 ... Please retry in 8h56m"). One Kilta turn makes 2 to 4 model calls, so one
conversation exhausts it. Groq is capped at 8,000 tokens per minute (about one call a minute). Flash-Lite
still answered at the last check; its daily limit is not published and not yet measured.

## Left
1. Decide how to get unthrottled models (see the options in the Phase 2 report), then run the live
   scenarios A, B, C and paste the output as the "Done when" evidence.
2. Optional: shrink the per-call token load (tool schemas about 3,500 tokens, system prompt about 1,400).
3. Your `.env` may still set `KILTA_MODEL_PRIMARY=gemini-flash-latest`; update it to the IDs in `.env.example`.
4. Reviewer subagent on the Phase 2 diff, fix correctness/safety findings, final commit.
5. Log `/friction` (Gemini 20 requests/day, Groq 8k TPM, `uv sync` before `src/` exists) and `/feedback`
   (Strands, Gemini, Groq).
