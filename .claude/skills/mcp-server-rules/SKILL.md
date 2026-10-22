---
name: mcp-server-rules
description: Use when creating or editing anything in server/ (the Kilta MCP server, repair engine, tools, resources, data contracts) or when testing MCP protocol behavior.
---
# Kilta MCP server rules

- Protocol: MCP spec 2025-11-25 only. Python SDK pinned `mcp>=1.27,<2`. FastMCP from the official SDK.
- Transport: Streamable HTTP only (`transport="streamable-http"`), port 8765, path `/mcp`. Never SSE.
- Must be runnable as a remote server (Alexa+ requirement): bind host configurable, default 127.0.0.1.
- Tool results: short speakable `content` text + `structuredContent` dict with a `card` object:
  `{"card": {"type": "...", "title": "...", ...}, "state": "...", "session_id": "..."}`.
- Step tools add `_meta.ui.resourceUri = "ui://kilta/step-card.html"` (Phase 5).
- Add tool annotations honestly (readOnlyHint for lookups; destructiveHint false unless it changes data).
- Engine is the source of truth. Tools are thin wrappers that call the engine. No safety logic in prompts only.
- Every step must carry `source = {"manual_id": ..., "page": ...}`; validation fails otherwise.
- Persist sessions to data/sessions/<id>.json after every change.
- Testing: unit-test the engine directly; integration-test via an MCP client over streamable HTTP.
  Use MCP Inspector (`npx @modelcontextprotocol/inspector`, see `--help` for CLI mode) to list tools and call them.
- Keep tool descriptions clear and specific: hosts like Alexa+ derive examples and routing from them.
