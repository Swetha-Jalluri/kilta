# Kilta

Kilta is a warm, voice-first appliance repair friend for Alexa+ ("Hey Alexa, connect me to Kilta").
Built for the Build, Ship, Shape: Amazon Developer Hackathon (Alexa+ track, plus AWS Builder mini challenge).
Solo developer on macOS. Deadline: Fri Oct 23 2026, 12:00 PM Pacific. Feature freeze: Thu 10:00 PM Eastern.

Always read before large changes: @docs/architecture.md and @docs/hackathon-rules.md
Read on demand (do not preload): docs/product-plan.md, docs/conversation-design.md, docs/demo-script.md,
docs/fictional-manuals.md, docs/phases.md

## Repo layout
- `server/`  Kilta MCP server + repair engine (Python, uv). The real product.
- `bridge/`  FastAPI + Strands agent. Stands in for Alexa+ as the MCP client.
- `web/`     Kilta simulator UI (Vite, React, TypeScript, Tailwind, Motion).
- `skill/kilta/`  Agent Skill (agentskills.io format).
- `data/`    Fictional data only. `data/sessions/` is runtime state (gitignored).
- `docs/`    Plans, rules, logs.

## Commands (create in Phase 1, keep working)
- `make dev`    start server :8765, bridge :8000, web :5173
- `make test`   run all tests (server, bridge, web)
- `make reset`  restore demo data and clear sessions
- `make check`  ruff + tests + web build (what CI runs)

## Hard rules
- IMPORTANT: The MCP server targets MCP spec **2025-11-25** over **Streamable HTTP**. Pin `mcp>=1.27,<2`. Never use the SSE transport. Never move to SDK v2 or the 2026 protocol.
- IMPORTANT: Safety lives in the repair engine (server code), never only in prompts. Safety check comes first, gated steps cannot advance without confirmation, technician-only work routes to handoff.
- Every repair step cites its source: manual id + page.
- Fictional data only. Appliance brand is "Kelvara". No real brands, logos, manuals, people, or personal data.
- Every tool returns short speakable `content` plus `structuredContent` for the card. Step tools also set `_meta.ui.resourceUri`.
- Secrets live in `.env` (gitignored). Keep `.env.example` current.
- Use current stable library versions; verify before adding a dependency. Prefer few dependencies.

## Workflow
- Prove work with evidence: paste test output, command output, or Playwright screenshots. "Looks done" is not done.
- Commit small, after each working step, with descriptive messages.
- Painful moment (docs gap, confusing error, workaround)? Run `/friction`.
- Used a tool/SDK/API in a new way? Run `/feedback`.
- When compacting, preserve: current phase, files changed, failing tests, run commands, open decisions.
- Git: never add Claude as co-author or contributor. No Co-Authored-By, Claude-Session, or 'Generated with Claude Code' lines in commits or PRs.
