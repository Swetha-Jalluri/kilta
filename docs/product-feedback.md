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

`npx @modelcontextprotocol/inspector` in CLI mode.

1. **What we used it for.** The Phase 1 check Amazon recommends: start the server, list its tools (`--method tools/list`) and call one (`--method tools/call --tool-name start_repair --tool-arg ...`) over Streamable HTTP, and confirm `GET /sse` is not served.
2. **What worked well.** CLI mode prints plain JSON, so the result is easy to paste as evidence: 24 tools listed, and a `start_repair` call returned both `content` and `structuredContent`.
3. **What needs work.** The CLI does not show the negotiated protocol version, so we assert `2025-11-25` in our own client tests. The `--transport http` flag name is easy to miss. We used only the CLI, not the browser UI.
4. **Onboarding.** Two minutes with `npx -y`.
5. **Would we use it again?** Yes, as a smoke test in the build loop.

## Alexa+ MCP Toolkit docs and Private Preview

1. **What we used it for.** The documentation shaped the server: Streamable HTTP, spec 2025-11-25, a remotely reachable URL, tools whose descriptions the host can route from, and `content` that works when spoken. We did not request Private Preview access during the hackathon (see 4), so we never ran Kilta on a real Alexa+ host.
2. **What worked well.** The requirements were clear enough to build against without access, and an ordinary MCP SDK server needed no Alexa-specific code.
3. **What needs work.** Preview approval gates all real testing for a short project like ours, so the end-to-end path (a real Alexa+ device calling Kilta) could not be tried. A hosted MCP test console, or a documented simulator of the host's tool-calling behaviour, would let developers test the part that matters most. MCP has no way for a server to know which words the user actually said; hosts are where that belongs, and the docs do not say what they guarantee.
4. **Onboarding.** We read the documentation and built to it, but we did not request Private Preview access. The preview requires approval, which was not practical in a short build window, so we built a simulated Alexa+ host (a Strands agent behind a small API, plus a web simulator) that calls the same MCP server a real host would call. Nothing in the server is specific to the simulator.
5. **Would we build for it again?** Yes. The server is unchanged for a real host; only access is missing.

## Agent Skills (agentskills.io)

1. **What we used it for.** `skill/kilta/SKILL.md` teaches any agent when to use Kilta, the tool order, the safety rules and the voice rules, with a per-state tool reference in `references/`.
2. **What worked well.** The format is small and clear: required `name` and `description`, optional fields, a body in plain Markdown, and optional folders for progressive disclosure. The rule that the name must match the directory caught a typo early.
3. **What needs work.** We found no official validator to run, so we wrote our own test (`server/tests/test_skill.py`): frontmatter limits per the specification, and every tool the skill names must exist on the server. We also have not run the skill inside an agent host, so we cannot say how well a host follows it.
4. **Onboarding.** About ten minutes from the specification page to a valid skill.
5. **Would we build with it again?** Yes. It is the cheapest way to hand an agent the rules of a domain.

## AWS: Strands Agents SDK (AWS Builder mini challenge: describe exactly how Strands is used)

Version: `strands-agents` 1.62.0 with the `gemini`, `openai` and `ollama` extras. Strands is the AWS-originated, open-source agent SDK, which the hackathon rules name as qualifying for the AWS Builder challenge. It runs locally inside the bridge. No hosted AWS service (Bedrock, AgentCore, S3) is called and no AWS account is needed, so the project has no AWS bill.

1. **What we used it for.** The agent loop of the Alexa+ stand-in (`bridge/`). One `Agent` per household conversation, with `MCPClient(url=...)` connecting to the Kilta MCP server over Streamable HTTP (spec 2025-11-25) so every Kilta tool is a live MCP call. We also use:
   - **Hooks:** `BeforeToolCallEvent` to cancel a tool call (`cancel_tool`) and to replace invented arguments, and `AfterToolCallEvent` to capture each call's `structuredContent` for the card, the state and the live tool-call log.
   - **Custom model:** a `Model` subclass (`FallbackModel`) that wraps `GeminiModel`, `OpenAIModel` (pointed at Groq's OpenAI-compatible endpoint) and `OllamaModel` into one fallback chain, and filters the tool specs on every model call.
   - **History:** `SlidingWindowConversationManager` and direct edits of `agent.messages` to roll back a failed turn.
2. **What worked well.**
   - `MCPClient` keeps `structuredContent` in the tool result, so the card the server sends reaches our hook untouched.
   - The `Model.stream()` interface is small and well suited to wrapping: our fallback chain, per-call tool filtering and test fakes were each under 100 lines.
   - `cancel_tool` on `BeforeToolCallEvent` was exactly the hook we needed to stop a model answering a safety question for the user.
   - Switching between Gemini, Groq and a local Ollama model took one line each.
3. **What needs work.**
   - `strands-agents` 1.62 allows `mcp<2.2`, so an unpinned install resolves the MCP Python SDK **v2** (2.1.1). Kilta must stay on 2025-11-25 and v1, so we pin `mcp>=1.27,<2` ourselves. A resolver-safe default (or a documented v1 extra) would avoid that surprise.
   - Strands still uses the deprecated `streamablehttp_client` and prints a `DeprecationWarning` on every connection.
   - `Agent(...)` loads and starts MCP tools in its constructor, so a down MCP server raises there, not on the first `invoke`. `MCPClient.stop` after a failed start also leaves a "coroutine was never awaited" `RuntimeWarning`.
   - The Gemini provider yields `messageStart` before the request has succeeded, so a bad key or a 429 arrives after the stream has "started". A simple failover wrapper then cannot tell it from a mid-stream failure. We had to hold back `messageStart` to fix this.
   - The OpenAI provider logs "reasoningContent is not supported in multi-turn conversations" for every call with a reasoning model (gpt-oss).
   - There is no built-in per-call tool selection or provider failover; both are common needs and we wrote them ourselves.
4. **Onboarding (zero to hello world).** About an hour to a working agent that calls our MCP server, mostly reading source because the docs show Bedrock first. The MCP client, hooks and model interfaces are easy once found.
5. **Would we build with it again?** Yes. It stayed out of the way, and the hooks and the `Model` interface made the safety guards and the fallback chain straightforward. We would pin the MCP SDK from day one.

## Google Gemini API (free tier)

Models used: `gemini-3.5-flash-lite` (primary) and `gemini-3.5-flash` (fallback), through Strands' `GeminiModel` (`google-genai` 2.32). Fictional data only, because free-tier inputs may be used to improve Google products.

1. **What we used it for.** The language model of the Alexa+ stand-in: it picks Kilta's tool calls and phrases the replies, in English and Spanish. The repair engine decides everything that matters.
2. **What worked well.**
   - Tool calling is accurate and fast: Flash-Lite answered in about 0.6 s on a simple call, and a full turn with several tool calls took 8 to 12 s including our pacing.
   - Spanish worked with no extra prompting.
   - The error text of a spent quota says which model, which limit and how long to wait ("limit: 20 ... Please retry in 8h56m"), which let us skip a dead model instead of retrying it.
3. **What needs work.**
   - **The free tier is thin for a conversation.** `gemini-3.5-flash` resolves to `gemini-3.6-flash`, whose free limit is **20 requests per day**. One Kilta turn makes 2 to 4 model calls, so a single scenario exhausts it. `gemini-3.5-flash-lite` allows **500 requests per day**, which was enough for several full runs of our three golden scenarios (about 8 s per turn, one transient 429) before it ran out too, with "Please retry in 1h22m". The limits are only visible in the error text and the dashboard, not in the rate-limit documentation.
   - The `gemini-flash-latest` alias hung for 40 s or returned 503 "high demand" on 2026-10-21, and `gemini-2.5-*` returned 404 for a new key. Pinned model IDs were the only stable option.
   - `count_tokens` on the Developer API rejects `system_instruction` and `tools`, so the real prompt size could not be measured with Gemini.
   - Once, a conversation containing tool calls made by another provider was rejected with "Function call is missing a thought_signature" on the overloaded alias. We could not reproduce it on the pinned models.
4. **Onboarding.** Minutes: key from AI Studio, one environment variable.
5. **Would we build with it again?** Yes, but on a paid tier for anything beyond a demo clip. On the free tier we treat it as one link in a fallback chain.

## Groq API (free tier, OpenAI-compatible)

Model: `openai/gpt-oss-120b`, through Strands' `OpenAIModel` with `base_url=https://api.groq.com/openai/v1`.

1. **What we used it for.** The second link of the model fallback chain, so a Gemini rate limit does not end the conversation. A live test proves it: with an invalid Gemini key, Groq answered both turns and the Gemini failure was recorded as non-retryable.
2. **What worked well.** Tool calling works with no changes to our tools (`gpt-oss-120b` and `qwen3.8-27b` both passed a tool-call probe), the endpoint is OpenAI-compatible, and a short call returns in under a second.
3. **What needs work.**
   - The free tier allows **8,000 tokens per minute per model**. One Kilta call (system prompt, tool specs, history) is 1,400 to 3,300 tokens, so Groq answers about one call a minute and returns 429 in between. A single turn took about 90 seconds.
   - In our tests `gpt-oss-120b` followed the flow less strictly than Gemini: it answered the safety question itself ("No, there's no burning") in the same turn it asked it. Our host now blocks that.
   - The model list endpoint does not say which models support tool calling.
4. **Onboarding.** Minutes. The key worked immediately, and the rate-limit headers are clear (`x-ratelimit-remaining-tokens`).
5. **Would we build with it again?** Yes as a fallback, not as the primary model on the free tier.

## Ollama (local fallback model)

Ollama 0.40.9 with `qwen3:8b` (5.2 GB), on a 16 GB Apple M4 Mac, through Strands' `OllamaModel`.

1. **What we used it for.** The last link of the chain, and unlimited local testing: the live golden tests can run with `KILTA_LIVE_MODEL=ollama` without using any cloud quota.
2. **What worked well.**
   - Install and `ollama pull` were one command each, and the model answered tool calls on the first try.
   - Scenario C (burning smell) and all four danger answers, in English and Spanish, passed on it: 5 of 5, with the right `danger_reported` boolean each time.
   - A direct call returned in 8 to 15 s per turn when the machine was idle.
3. **What needs work.**
   - The default context window (4,096 tokens) silently truncates our prompt and tools; we set `num_ctx` to 12,288.
   - qwen3 returns an empty reply now and then, and with `think` left on it spends its time reasoning. We pass `think: False` and retry an empty reply once.
   - An 8B model is not reliable enough to follow the whole flow: it skips tool calls, echoes the user's words as its own, and in scenario B it stalled at turn 4 of 15 by calling `quick_checks` instead of `diagnose`.
   - Under memory pressure turns took 28 to 34 s, and once the server restarted in the middle of a run ("peer closed connection").
4. **Onboarding.** Minutes. The only surprise was the context size.
5. **Would we build with it again?** Yes for offline fallback and testing. It is not the model for the demo recording.

## Web Speech API (Chrome)

1. **What we used it for.** Push-to-talk speech recognition (language follows the selected person: en-US or es-ES) and spoken replies with `speechSynthesis`, picking an es-ES voice for Spanish, then es-MX, then any Spanish voice.
2. **What worked well.** No keys, no install, and voices in many languages. Voice selection is a few lines of code and a browser test with stubbed voices proves the es-ES choice.
3. **What needs work.** `getVoices()` can be empty until the `voiceschanged` event. Recognition needs Chrome, the microphone permission and (in Chrome) a network connection, and it cannot be exercised in headless tests, so we test the text path and stub the voices. `SpeechSynthesisUtterance.voice` throws if given anything but a real voice object, which broke our first stub. There is no reliable "is it listening" signal across browsers.
4. **Onboarding.** An hour including the Spanish voice choice.
5. **Would we build with it again?** Yes for a demo, with a text box always on screen.

## Dev tooling: Playwright, Vite, React, Tailwind CSS, Motion

Versions: `@playwright/test` 1.64, Vite 8.3, React 19.3, TypeScript 7.0, Tailwind CSS 4.3, Motion 14.6.

1. **What we used it for.** The simulator web app (`web/`) and its browser tests. Playwright types the three golden scenarios into the app against a scripted fake model, checks the engine state and tool log on screen, and screenshots every card at 1280x720 and 1920x1080.
2. **What worked well.**
   - Vite 8 and TypeScript 7 worked on the first try (`tsc --noEmit` plus a 0.6 s build), so nothing needed pinning. React 19 had no surprises.
   - Tailwind 4's CSS-first setup (`@theme` tokens and `@custom-variant dark`) made light and dark mode a few lines.
   - Motion's `AnimatePresence` gave simple card transitions in a few lines.
   - Playwright's `webServer` list starts the fake-model bridge and Vite together, and `addInitScript` let us stub the speech voices to test the es-ES choice.
3. **What needs work.**
   - Playwright 1.64 wanted a newer browser than the one cached from an earlier install; `npx playwright install chromium --only-shell` fixed it, but the failure message is long for a one-line fix.
   - A fade-out/fade-in card transition made early screenshots catch half-faded cards; we wait 650 ms after each turn. A Playwright option to wait for CSS animations to finish would help.
   - Headless Chromium cannot exercise real speech recognition, so that path stays a manual check.
4. **Onboarding.** Under an hour for the app shell and the first passing browser test.
5. **Would we build with it again?** Yes. It is a light stack, and the browser test was cheap to keep running on a laptop (one worker, headless).

## Feature requests (optional)
Format: description, why it matters to Kilta, priority (Critical / Important / Nice-to-have)

1. **MCP: tell the server which text came from the user.** A request field (or a turn identifier) that marks user-spoken text versus model-generated arguments. Kilta's safety answers and gate confirmations must come from the user, and a server cannot tell today whether a model answered "no, nothing is burning" itself. We had to enforce this in our host. Priority: Critical.
2. **Gemini API: publish the free-tier limits per model.** Requests per day and tokens per minute in the public rate-limits table (we found 20 a day for 3.x Flash only in an error message). Priority: Important.
3. **Strands Agents: provider failover and per-call tool selection as built-in options.** Both needed small custom code in our chain. Also raise provider errors before the first `messageStart`. Priority: Important.
4. **Alexa+: a hosted MCP test console for developers without Private Preview.** Priority: Nice-to-have.
