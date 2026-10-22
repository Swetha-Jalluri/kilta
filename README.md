# Kilta

**"Hey Alexa, connect me to Kilta."** A warm, voice-first home appliance repair friend for Alexa+.

Kilta guides every member of a household through safe, step-by-step appliance repairs by voice, in their own
language, using their exact model's manual, and hands off cleanly to a technician or landlord when a job
isn't safe to do at home.

> Work in progress for the Build, Ship, Shape: Amazon Developer Hackathon (Alexa+ track, AWS Builder).
> Full README, quickstart, and demo coming in Phase 6.

## Run the MCP server (Phase 1)

```bash
make dev      # Kilta MCP server at http://127.0.0.1:8765/mcp (Streamable HTTP, spec 2025-11-25)
make check    # ruff + tests
make reset    # restore the demo data and clear sessions
```

Inspect it: `npx @modelcontextprotocol/inspector --cli http://localhost:8765/mcp --transport http --method tools/list`

License: MIT
