# Kilta: Devpost submission

## Name
Kilta

## Tagline
Your home repair friend in Alexa+. Safe, patient, step-by-step help in your own language.

## Inspiration / problem
When a dishwasher beeps E24 at 9 pm, the options are a ten-minute video that fixes a different model, a
manual nobody can find, or a service call. People who rent, who are new to fixing things, or who are more
comfortable in another language have it hardest. Worse, a confident but wrong answer can turn a clogged filter
into an electric shock: appliances need unplugging before anything else happens.

Kilta ("guild" in Finnish: the people who always knew how to fix things) is a calm friend on the kitchen floor.
You say "Hey Alexa, connect me to Kilta", and it walks you through the repair one step at a time, from your
exact model's manual, in your language, and tells you honestly when a job is not safe to do at home.

## What it does
- **Safety first, every time.** Before anything else it asks about burning, gas, smoke, sparks and water near
  outlets. A "yes" at any moment, even mid-repair, stops everything and gives only stop instructions.
- **Knows the household.** Two members with different languages and confidence (Priya, English, beginner;
  Lucia, Spanish). Either can continue the same repair; a repair can be paused and resumed ("we stopped at
  step 3").
- **Follows the manual, with page numbers.** Simple checks first (is the door latched?), then the error code
  (E24: water not draining, page 18), then the fix in small voice-sized steps with the time and tools needed.
- **Waits for you.** Steps that need safety ("is it unplugged?") do not advance until you say so. One step
  even stays hidden until you confirm the power is off.
- **Hands off when it should.** Technician-only work (a failed pump, heaters, gas, refrigerant, wiring) is
  never guided. Kilta writes a technician summary and, for renters, a message to the landlord with the model,
  the error and what was already tried. Both are always in English.
- **Remembers.** Updates the appliance's health card, notices a repeat problem ("second time E24 on this
  dishwasher"), and offers to share what worked anonymously.

## How we built it
- **A real Alexa+-ready MCP server** (`server/`): Python, the official MCP SDK v1 (`mcp>=1.27,<2`), MCP spec
  **2025-11-25 over Streamable HTTP** at `/mcp`. 24 tools, a manual resource, and a prompt. Every tool returns
  short speakable `content` plus `structuredContent` for a visual card. Verified with MCP Inspector and with a
  client test that asserts the negotiated protocol version.
- **A repair engine, not a prompt.** The rules live in a deterministic, safety-gated state machine (13 states):
  no step before the safety check, gated steps cannot advance, danger words trigger a recheck that only an
  explicit answer clears, technician-only codes go to a handoff, every step cites its manual and page, and
  sessions are saved after every change. The model only phrases what the engine decides. 121 server tests.
- **An Alexa+ stand-in** (`bridge/`): a FastAPI bridge running a **Strands Agents** agent that calls the Kilta
  MCP server live over Streamable HTTP. It adds guards a real host would need: a turn that has just asked the
  user something cannot go on to answer it, danger words in the user's message hold every other call, and the
  engine's own words are spoken for safety stops. Models: Gemini Flash-Lite, Groq, Gemini Flash, then local
  Ollama, with retry, cooldown, per-turn time budget and quota handling. 125 bridge tests, plus golden
  conversations replayed against real models.
- **A simulator** (`web/`): React, TypeScript, Tailwind. A smart-display frame, push-to-talk and spoken replies
  (Chrome Web Speech, a Spanish voice for Spanish), a card for every answer, light and dark mode, and a
  "behind the scenes" panel that shows each MCP tool call and the engine state live. Browser tests (Playwright)
  type the demo scenarios and screenshot every card.
- **An Agent Skill** (`skill/kilta/SKILL.md`, agentskills.io format) that teaches any agent when to use Kilta,
  the tool order, the safety rules and the voice rules.
- **Fictional data only:** "Kelvara" appliances and manuals we wrote ourselves. No real brands or personal data.

Where the track technology runs: the MCP server uses the MCP SDK (`server/src/kilta/server.py`); the bridge's
Strands agent calls the server's tools at runtime (`bridge/src/kilta_bridge/agent.py`); the panel in the app
shows every call as it happens. Strands (the AWS Builder challenge) is used as the agent loop, MCP client and
hook system. No hosted AWS service is used.

## What makes it different
- **Safety is in code, not in a prompt.** Models make mistakes. We saw one answer "No, there's no burning" on
  the user's behalf, one confirm a gate when the user only said "next", and one congratulate a user for a fix the
  engine had refused to record. Each is caught by the engine or the host, and each has a test.
- **It is a real MCP server**, not a wrapper around an API: state across sessions and speakers, gated steps,
  refusals as normal results, consent for anything that leaves the home, a health card, and handoff documents.
- **Honest about limits**: it stops, hands off, and says so kindly.

## Challenges
- **Free-tier limits.** Gemini 3.x Flash allows 20 requests a day, Flash-Lite 500 a day, and Groq 8,000 tokens a
  minute. We built the fallback chain, shrank every call (fixed prompt cost 3,327 tokens down to 1,387 to 1,783
  by sending only the tools that fit the current state), and tested a local model for unlimited runs.
- **Small models skip ahead.** They answer the safety question themselves, confirm gates for the user, or take
  five steps in one turn. The engine folds the steps they drop (an appliance named in the first message, the quick
  checks inside the manual lookup) and the bridge holds the turn once the user has been asked something.
- **A fallback bug only a live test found:** Gemini announces the message before a request has succeeded, so a
  bad key looked like a started stream until we held the announcement back.
- **Version drift:** Strands allows the newer MCP SDK; we pin the one that speaks spec 2025-11-25.

## Accomplishments
- A complete, safe repair conversation in two languages, from greeting to fixed or handed off, driven by a
  real MCP server and a Strands agent.
- Golden conversations for three scenarios (dishwasher E24 fixed at home with a speaker switch and a Spanish
  stretch; washer E31 handed to a landlord; a burning smell that stops everything) that passed with a real model
  (Gemini Flash-Lite) and with a local one for the safety cases, and replay deterministically in CI.
- The claims above map to tests, logs and screenshots in the repository. 7 friction-log entries and product
  feedback for every tool we used.

## What we learned
Put the rules where models cannot argue with them. A server that refuses is worth more than a prompt that asks
nicely, and a tool-calling agent needs a host that knows when the user has actually spoken. MCP has no notion of
a user turn; a real host (Alexa+) is where that belongs, and we would like the protocol to say so.

## Limits (we would rather say so)
- Not tested on a real Alexa+ device. We did not request Private Preview access (it needs approval, which was not
  practical in a short build window), so our simulator plays Alexa+'s role. The server is unchanged for a real host.
- The repair-step MCP App (`ui://`) and an explainer animation were planned and not built.
- Orders, warranty, parts cart and insights are simulated with fictional data. Nothing is bought or sent.
- Speech recognition needs Chrome; the text box always works. The last live re-run of the golden scenarios on a
  real model happened before the final small fixes (the fixes are covered by scripted tests).

## What's next
Connect to real Alexa+ through the MCP Toolkit once Private Preview is open; ship the step card as an MCP App;
real manual search over a manufacturer's PDF; recall and warranty lookups; more languages; and a protocol-level
way for a host to say which words came from the user.

## Track and challenges
- **Track:** Alexa+ (MCP server on spec 2025-11-25 over Streamable HTTP, a simulated Alexa+ experience, and an
  Agent Skill).
- **Mini challenge:** AWS Builder (Strands Agents SDK; described in `docs/product-feedback.md`).
- Open Source mini challenge: not entered.

## Data, terms and attribution
All appliances, manuals, people and orders are fictional ("Kelvara" is a made-up brand). Gemini and Groq are used
on their free tiers with fictional data only. No third-party logos, music or footage. Icons are Lucide (open
source); the Kilta mark is original.

## Links
- Repository: https://github.com/Swetha-Jalluri/kilta (public, MIT)
- Demo video: [ADD YOUTUBE URL BEFORE SUBMITTING]
- Run it: see the README (`make dev`, then open http://localhost:5173)
