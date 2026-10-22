---
name: phase
description: Run a Kilta build phase from docs/phases.md.
disable-model-invocation: true
---
Run build phase $ARGUMENTS for Kilta.

1. Read docs/phases.md (phase $ARGUMENTS only), CLAUDE.md, and the architecture sections it references.
2. Check the current repo state (git status, existing files) so you build on what exists.
3. Present a concise implementation plan: files to create or change, tests and checks you will run,
   and anything ambiguous. STOP and wait for my approval before editing files.
4. After approval, implement step by step. Run the checks as you go and fix failures at the root cause.
5. Finish with evidence: test output, command output, or Playwright screenshots, mapped to the phase's
   "Done when" list.
6. Use the reviewer subagent on the diff against docs/architecture.md and docs/hackathon-rules.md.
   Fix gaps that affect correctness, safety, or the rules. Ignore style nitpicks.
7. Commit with a descriptive message. Suggest any /friction or /feedback entries worth logging.
