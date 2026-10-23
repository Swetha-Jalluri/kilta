# Phase 2: bridge + Strands agent (status)

Status: done except one live re-run (see "Left"). `make check`: server 117 tests, bridge 125 tests, ruff clean.
Live evidence: `docs/phase2-live-evidence.md`.

## What exists
- `bridge/` (uv project, `uv.lock` committed, pins `mcp>=1.27,<2` because `strands-agents` also allows MCP SDK v2).
- FastAPI app: `POST /api/turn`, `GET /api/events` (SSE, `?replay=N`), `GET /api/health`,
  `POST /api/reset` (demo mode only, needs `X-Kilta-Demo: 1`, deletes only `data/sessions` and `data/state`).
- `agent.py`: Strands agent on the Kilta MCP server (Streamable HTTP). Per-turn context line (speaker, language,
  confidence, pace, session), hooks that log every tool call, card/state/session taken from the tool results.
  Host guards: after a turn has asked the user something it may not move on (a model answered the safety
  question itself, and once cleared, identified, diagnosed and started step 1 in one turn); danger words in
  the user's own message hold every advancing call until `safety_check` is called; invented session ids are
  replaced; an empty model reply is retried once; a safety stop and a refused "fixed" are spoken by the engine.
- `chain.py`: Gemini Flash-Lite -> Groq gpt-oss-120b -> Gemini Flash -> Ollama qwen3:8b. Backoff on 429/5xx,
  straight to the next model on other errors (bad key) or a slow first token, a cooldown per failed model,
  a spent daily quota skips the model for hours, a per-turn time budget shared among the remaining models,
  `messageStart` held back until content arrives, `KILTA_MODEL_ONLY` to use one model.
- `tools.py`: each model call sees only the tools that fit the engine state (`safety_check`,
  `get_repair_state`, `get_household` always; `start_repair` only when no repair is under way).
  Measured with Groq (fixed cost per call, history excluded): 3,327 tokens before, 2,806 with all tools after
  trimming the prompt and descriptions, 1,387 to 1,783 filtered by state.
- Engine changes made for this phase (server): an appliance named in the first message is confirmed after the
  safety check; `find_manual` returns the quick checks; "fixed" is only recorded after the verify question;
  appliance matching accepts ids, manual ids, model names and codes; starting over cannot wash away a safety
  stop or an unanswered danger question; Spanish danger words.

## Done-when
- Golden tests green with a real model: A, B, C passed on Gemini Flash-Lite; the four safety answers
  (EN/ES, true/false) and scenario C also passed on Ollama. See the evidence file.
- Fallback proven by forcing an error: scripted tests (429 retry, timeout, bad key, all failing, cooldown,
  budget) and a live run where an invalid Gemini key was answered by Groq.

## Left
1. A final live re-run of A, B, C on Flash-Lite once its daily quota resets (500 requests a day, spent on
   2026-10-23). The last reviewer fixes are covered by scripted tests only.
2. Scenario A on Ollama was never completed; B stalls around turn 4 (qwen3:8b is weak at the flow).
3. `quick_checks(setting_fixed=true)` still records "fixed" from a model boolean, without a verify question.
4. Web UI (Phase 3) must send `X-Kilta-Demo: 1` on reset and should not rely on `step_id` while a step is withheld.
