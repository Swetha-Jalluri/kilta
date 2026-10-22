# Build phases

Run one phase per Claude Code session: `/clear`, then `/phase N`. Plan first, build, prove, review, commit.

## Phase 1: MCP server, repair engine, data, CI (Wed night)
Goal: the real product works and is proven by tests.
- `server/` with uv, Python 3.12+, `mcp>=1.27,<2`, FastMCP, `streamable-http` on port 8765, path `/mcp`.
- Repair engine state machine per docs/architecture.md section 6. Pydantic models.
- Data files in `data/` from docs/fictional-manuals.md and docs/demo-script.md.
- All tools from architecture section 5 (simulated ones return fictional data).
- Tool annotations (readOnlyHint etc.) where accurate. Contract: `content` + `structuredContent`.
- pytest: safety-first, gates enforced, technician-only -> handoff, danger -> STOPPED, resume works, every step has manual ref.
- In-process MCP client test (list tools, call a tool) over streamable HTTP.
- Makefile (dev, test, reset, check), ruff, GitHub Actions CI running `make check` for the server.
Done when: tests green (show output), Inspector lists tools, CI file exists, committed.

## Phase 2: Bridge + Strands agent (Thu morning)
Goal: a full conversation works through an API.
- `bridge/` FastAPI app: POST /api/turn {member_id, text, language} -> {speech, card, tool_calls, state}; SSE /api/events for live tool-call log; GET /api/health; POST /api/reset.
- Strands agent connected to KILTA_MCP_URL with its MCP client over streamable HTTP.
- System prompt built from docs/conversation-design.md (use the kilta-voice skill).
- Model chain: Gemini primary -> Gemini fallback -> Ollama local, with retry/backoff on 429 and timeouts.
- Golden conversation tests replaying docs/demo-script.md scenarios A, B, C, asserting tool order and engine state (not exact wording).
Done when: golden tests green with the real model at least once (show output), fallback proven by forcing an error.

## Phase 3: Simulator UI (Thu afternoon)
Goal: the full demo works by voice in Chrome.
- `web/` Vite + React + TypeScript + Tailwind + Motion + Lucide.
- Smart-display device frame (original design, no Amazon logos), listening ring, waveform, transcript strip.
- Push-to-talk with Web Speech API (recognition lang follows member language), speech output with speechSynthesis.
- Text input fallback always visible. Member selector. Language toggle.
- Card renderer for every structuredContent type. Behind-the-scenes panel with live tool calls and state.
- Light and dark mode, large type, keyboard accessible.
Done when: Playwright runs scenario A by text end to end and screenshots each card; screenshots reviewed and fixed.

## Phase 4: Explainer animation, health card, handoffs, insights, Demo Mode (Thu evening)
- 25-second skippable explainer (home, breakdown, "Hey Alexa, connect me to Kilta", guided fix, handoff, guild closing).
- Health card view, technician summary and landlord message views.
- Insights dashboard concept with consent screen (synthetic data, clearly labeled).
- Demo Mode: seeded data, one-click reset (calls /api/reset).
Done when: Playwright screenshots of every view look right.

## Phase 5: MCP App + Agent Skill (Thu, before 10 PM freeze)
- `ui://kilta/step-card.html` MCP App with @modelcontextprotocol/ext-apps, linked from step tools via `_meta.ui.resourceUri`.
- `skill/kilta/SKILL.md` per agentskills.io spec: when to use Kilta, tool order, safety rules, voice rules.
Done when: all tests still green, resource listed by Inspector, skill validates.

## Phase 6: Fresh-clone test, docs, submission (Fri morning)
- Clone into a temp folder, follow README exactly, fix anything missing.
- README: hero, demo GIF/screenshot, architecture diagram (Mermaid), quickstart, how Kilta meets the Alexa+ track, AWS Builder (Strands) section, license.
- docs/submission.md, docs/product-feedback.md, docs/friction-log.md final pass.
- Check every item in docs/hackathon-rules.md and report gaps.
Done when: checklist all green.
