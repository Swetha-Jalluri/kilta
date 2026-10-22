# Hackathon rules: what Kilta must satisfy

Source: Build, Ship, Shape: Amazon Developer Hackathon official rules (amazonappdev2026.devpost.com).
Submission period ends **Fri Oct 23 2026, 12:00 PM Pacific**. No edits after that.

## Track: Alexa+
Build a working Agent Skill or a self-hosted MCP server implementing MCP spec **2025-11-25** (minimum) over
**Streamable HTTP**. A simulated Alexa+ experience in a web app is also allowed.
Kilta does all three: real MCP server + simulated Alexa+ web app + Agent Skill folder.

Runtime requirement: the repo must show the track technology imported AND actually called at runtime
(library import, entry point, or loaded MCP config), not just mentioned in the README.

## Mini challenge: AWS Builder
Any primary-track project that uses AWS services (Bedrock, AgentCore, Strands SDK, Kiro Crew, SageMaker, ...)
with documented integrations. Kilta uses the **Strands Agents SDK** as the agent loop. Describe it in product feedback.

## Mini challenge: Open Source (optional, stretch)
A new additional open-source project or contribution made during the hackathon window, alongside the primary
submission. Needs contribution URL, repo URL, GitHub username, and what/how/why description.
Kilta idea: publish the Alexa+ simulator as a separate reusable MIT repo.

## Submission checklist
- [ ] Text description of features and functionality (docs/submission.md)
- [ ] Public GitHub repo with open source license visible in the About section (MIT)
- [ ] Repo has all source, assets, and clear setup and run instructions (one command: `make dev`)
- [ ] Demo video under 3 minutes, public on YouTube or Vimeo, English, shows the project working
- [ ] No third-party trademarks, copyrighted music, or copyrighted footage in the video
- [ ] Product feedback for EACH tool/API/SDK used: what for, what worked, what needs work, onboarding, build again yes/no and why (docs/product-feedback.md)
- [ ] AWS services described inside the product feedback answer
- [ ] Track: Alexa+. Mini challenges: AWS Builder (+ Open Source if done)
- [ ] Optional feature requests: description, why it matters, priority (Critical / Important / Nice-to-have)
- [ ] Optional friction log entries: task, steps, expected vs actual, severity, workaround, suggestion (up to 10% bonus)
- [ ] Third-party APIs used within their terms

## Judging (equal weight)
1. Tech implementation: how well built, how well it uses the required tech (tie-breaker: this one first)
2. Design: complete, coherent experience; interaction model fits the device
3. Potential impact: credible, specific customer need; could serve real users
4. Quality of idea: creative, not obvious. For Alexa+, judges call out as creative: agentic workflows across
   services, context-aware state across sessions, purchasing, media support (cards, carousels), MCP Apps, Agent Skills.
   Obvious: single-turn Q&A bot, basic MCP wrapper around an API.
Stage 1 is pass/fail on fitting the theme and using the required tech.
Judges may judge from the video and description only, without running code.
