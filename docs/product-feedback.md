# Product feedback (one section per tool, API, or SDK used)

Answer for each: 1) What we used it for 2) What worked well 3) What needs work 4) Onboarding (zero to hello world)
5) Would we build with it again? Yes/No and why.

## MCP specification 2025-11-25 + MCP Python SDK (v1)

Versions: `mcp` 1.30.0 (pinned `>=1.27,<2`), spec 2025-11-25, Streamable HTTP only.

1. **What we used it for.** The whole Kilta server: `FastMCP` with 24 tools, one resource template (`kilta://manuals/{manual_id}`), one prompt, served at `/mcp` over `streamable-http`. The tests use the SDK's own client (`ClientSession` plus `streamable_http_client`) against a real server process.
2. **What worked well.**
   - `mcp.types.LATEST_PROTOCOL_VERSION` is `2025-11-25`, so pinning the v1 line gives the spec Alexa+ names, and our integration test asserts the negotiated `protocolVersion` is exactly that.
   - Returning a `CallToolResult` straight from a tool gives us both speakable `content` and a card in `structuredContent` with no output schema to maintain. Our tools are thin wrappers around a rules engine, so we control the payload shape ourselves.
   - Tool annotations (`ToolAnnotations`) and `Annotated[..., Field(description=...)]` parameter descriptions flow into `tools/list` as expected, which matters because hosts like Alexa+ route from descriptions.
   - `FastMCP(..., host=, port=, streamable_http_path=)` made the server remotely runnable (configurable bind host) in a few lines.
3. **What needs work.**
   - Two client helpers exist side by side: `streamablehttp_client` (headers, timeout, auth arguments) and `streamable_http_client` (takes a pre-built `httpx.AsyncClient`). Most examples we found use the old name. Say which one is current in the docs, and add a note on how to migrate headers and timeouts.
   - Returning `CallToolResult` directly skips output-schema validation and gives no `outputSchema` in `tools/list`. That is a good fit for us, but the tradeoff (you validate your own payload) is not spelled out where tool return types are described.
   - Binding to a non-loopback host or serving behind a tunnel needs the DNS-rebinding settings (`TransportSecuritySettings` with `allowed_hosts` and `allowed_origins`). We exposed this as a `KILTA_ALLOWED_HOSTS` environment variable. We have not yet tested it against a real Cloudflare tunnel, so we cannot say yet whether the defaults block a tunnel hostname. A documented recipe for "serve behind a tunnel or reverse proxy" would help, since Alexa+ requires a remote URL.
   - Our test for tool descriptions found one that was too thin to route from. A built-in lint or warning for very short tool descriptions would help.
4. **Onboarding (zero to hello world).** Quick, about 20 minutes to a working server with tests, mostly reading the SDK source and type signatures (`inspect.signature(FastMCP.__init__)`) to confirm the v1 API and options, because the docs and blog posts cover several protocol revisions and the v2 line. A page "the v1 line, spec 2025-11-25, Streamable HTTP" would have saved that.
5. **Would we build with it again?** Yes. The v1 SDK matched the required spec exactly, left the engine in plain Python, and was easy to test end to end. The doc gaps above are the main cost.
## MCP Inspector
## MCP Apps extension (@modelcontextprotocol/ext-apps)
## Alexa+ MCP Toolkit docs and Private Preview
## Agent Skills (agentskills.io)
## AWS: Strands Agents SDK (AWS Builder mini challenge: describe exactly how Strands is used)
## Google Gemini API (free tier)
## Ollama (local fallback model)
## Web Speech API (Chrome)

## Feature requests (optional)
Format: description, why it matters to Kilta, priority (Critical / Important / Nice-to-have)
