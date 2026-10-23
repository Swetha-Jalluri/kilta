# Kilta

**"Hey Alexa, connect me to Kilta."** A warm, voice-first home appliance repair friend for Alexa+.

Kilta guides every member of a household through safe, step-by-step appliance repairs by voice, in their own
language, using their exact model's manual, and hands off cleanly to a technician or landlord when a job
isn't safe to do at home.

> Work in progress for the Build, Ship, Shape: Amazon Developer Hackathon (Alexa+ track, AWS Builder).
> Full README, quickstart, and demo coming in Phase 6.

## Run it (Phases 1 and 2)

Needs `uv` (Python 3.12+). Copy `.env.example` to `.env` and add `GEMINI_API_KEY` and `GROQ_API_KEY`
(both free tiers; optional, see below). Ollama is the offline fallback: `ollama pull qwen3:8b`.

```bash
make dev        # MCP server :8765/mcp (Streamable HTTP, spec 2025-11-25) and bridge :8000
make check      # ruff + all tests (no network, no API keys)
make test-live  # golden conversations with the real models (needs the keys; slow, paced)
make reset      # restore the demo data and clear sessions
```

The bridge is the Alexa+ stand-in: `POST /api/turn` (`{member_id, text, language}`), `GET /api/events`
(live tool-call log, server-sent events), `GET /api/health`, `POST /api/reset` (send `X-Kilta-Demo: 1`).
Model order: Gemini Flash-Lite, Groq, Gemini Flash, local Ollama. Force one with `KILTA_MODEL_ONLY`.

Inspect the server: `npx @modelcontextprotocol/inspector --cli http://localhost:8765/mcp --transport http --method tools/list`

License: MIT
