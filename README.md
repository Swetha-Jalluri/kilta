# Kilta

**"Hey Alexa, connect me to Kilta."** A warm, voice-first home appliance repair friend for Alexa+.

Kilta guides every member of a household through safe, step-by-step appliance repairs by voice, in their own
language, using their exact model's manual, and hands off cleanly to a technician or landlord when a job
isn't safe to do at home.

> Work in progress for the Build, Ship, Shape: Amazon Developer Hackathon (Alexa+ track, AWS Builder).
> Full README, quickstart, and demo coming in Phase 6.

## Run it

Needs `uv` (Python 3.12+). Copy `.env.example` to `.env` and add `GEMINI_API_KEY` and `GROQ_API_KEY`
(both free tiers; optional, see below). Ollama is the offline fallback: `ollama pull qwen3:8b`.

```bash
make dev        # MCP server :8765/mcp (Streamable HTTP, spec 2025-11-25), bridge :8000, web app :5173
make check      # ruff + all tests (no network, no API keys)
make test-e2e   # browser test: scenarios A, B, C typed into the web app, fake model, screenshots
make test-live  # golden conversations with the real models (needs the keys; slow, paced)
make reset      # restore the demo data and clear sessions
```

The bridge is the Alexa+ stand-in: `POST /api/turn` (`{member_id, text, language}`), `GET /api/events`
(live tool-call log, server-sent events), `GET /api/health`, `POST /api/reset` (send `X-Kilta-Demo: 1`).
Model order: Gemini Flash-Lite, Groq, Gemini Flash, local Ollama. Force one with `KILTA_MODEL_ONLY`.

Open http://localhost:5173 for the simulator: a smart-display frame with push-to-talk (Chrome), a text box,
a Priya/Lucia selector, an EN/ES toggle, a card for every kind of answer, and a "behind the scenes" panel with
the live MCP tool calls and the repair engine's state. `make test-e2e` needs `cd web && npx playwright install
chromium` once; it never uses a real model.

`skill/kilta/SKILL.md` is the Agent Skill (agentskills.io format) that teaches any agent how to use the
Kilta server safely.

Inspect the server: `npx @modelcontextprotocol/inspector --cli http://localhost:8765/mcp --transport http --method tools/list`

License: MIT
