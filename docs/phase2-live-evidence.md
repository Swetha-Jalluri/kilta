# Phase 2 live evidence

Golden conversations replayed through the real bridge, the real Strands agent and the real Kilta MCP
server over Streamable HTTP, with real models. Per turn: model, seconds, engine state after the turn,
and the tools called. Assertions are an ordered subsequence of tools plus the exact engine state; wording
is never asserted. Raw output files: see the commit message. Run with `make test-live` and
`KILTA_LIVE_MODEL=primary|groq|fallback|ollama|chain`.

These runs were made while the code was still changing (the commits are listed in docs/phase2-progress.md).
The reviewer fixes after them are covered by the scripted tests; a final live re-run needs the free-tier
quota to reset (Gemini Flash-Lite: 500 requests a day, spent on 2026-10-23).

## Scenario A, dishwasher E24 fixed at home (Priya, then Lucia in Spanish): PASS on Gemini 3.5 Flash-Lite

```
   1. [gemini:gemini-3.5-flash-lite]   4.9s -              get_household
   2. [gemini:gemini-3.5-flash-lite]   8.0s SAFETY_CHECK   start_repair
   3. [gemini:gemini-3.5-flash-lite]  11.9s MANUAL         safety_check > get_repair_state > identify_appliance
   4. [gemini:gemini-3.5-flash-lite]   8.0s QUICK_CHECKS   identify_appliance > find_manual
   5. [gemini:gemini-3.5-flash-lite]   8.1s PREPARE        quick_checks > diagnose
   6. [gemini:gemini-3.5-flash-lite]   7.8s STEPS          next_step
   7. [gemini:gemini-3.5-flash-lite]   4.2s STEPS          (no tools)
   8. [gemini:gemini-3.5-flash-lite]   8.0s STEPS          confirm_gate > next_step
   9. [gemini:gemini-3.5-flash-lite]   8.0s STEPS          next_step
  10. [gemini:gemini-3.5-flash-lite]   8.1s PAUSED         pause_repair
  11. [gemini:gemini-3.5-flash-lite]   8.0s STEPS          resume_repair > next_step
  12. [gemini:gemini-3.5-flash-lite]   8.0s STEPS          confirm_gate > next_step
  13. [gemini:gemini-3.5-flash-lite]   9.0s STEPS          next_step
  14. [gemini:gemini-3.5-flash-lite]   7.1s STEPS          next_step
  15. [gemini:gemini-3.5-flash-lite]   8.0s STEPS          next_step
  16. [gemini:gemini-3.5-flash-lite]   7.7s STEPS          confirm_gate > next_step
  17. [gemini:gemini-3.5-flash-lite]   8.0s STEPS          next_step
  18. [gemini:gemini-3.5-flash-lite]   8.2s VERIFY         next_step
  19. [gemini:gemini-3.5-flash-lite]   7.8s FIXED          report_result
  20. [gemini:gemini-3.5-flash-lite]  12.2s FIXED          share_insight

1 passed, 106 deselected, 1 warning in 163.33s (0:02:43)
```

## Scenario B, washer E31, renter handoff to the landlord: PASS on Gemini 3.5 Flash-Lite

```
   1. [gemini:gemini-3.5-flash-lite]   8.9s SAFETY_CHECK   get_household > start_repair
   2. [gemini:gemini-3.5-flash-lite]   7.9s MANUAL         safety_check > get_repair_state
   3. [gemini:gemini-3.5-flash-lite]  12.3s QUICK_CHECKS   identify_appliance > find_manual > diagnose
   4. [gemini:gemini-3.5-flash-lite]   7.8s PREPARE        quick_checks > diagnose
   5. [gemini:gemini-3.5-flash-lite]   8.1s STEPS          next_step
   6. [gemini:gemini-3.5-flash-lite]  11.9s STEPS          confirm_gate > next_step
   7. [gemini:gemini-3.5-flash-lite]  12.0s STEPS          confirm_gate > next_step
   8. [gemini:gemini-3.5-flash-lite]   7.9s STEPS          next_step
   9. [gemini:gemini-3.5-flash-lite]   8.1s STEPS          next_step
  10. [gemini:gemini-3.5-flash-lite]   8.0s STEPS          next_step
  11. [gemini:gemini-3.5-flash-lite]   7.9s STEPS          next_step
  12. [gemini:gemini-3.5-flash-lite]   8.1s STEPS          next_step
  13. [gemini:gemini-3.5-flash-lite]   7.8s VERIFY         report_result
  14. [gemini:gemini-3.5-flash-lite]   9.0s HANDOFF        report_result
  15. [gemini:gemini-3.5-flash-lite]   7.1s HANDOFF        draft_landlord_message

1 passed, 103 deselected, 1 warning in 135.10s (0:02:15)
```

## Scenario C, danger (burning smell) and the four safety answers: PASS on Gemini 3.5 Flash-Lite

```
   1. [gemini:gemini-3.5-flash-lite]   9.1s SAFETY_RECHECK get_household > start_repair
   1. [gemini:gemini-3.5-flash-lite]   7.8s STOPPED        safety_check

1 passed, 101 deselected, 1 warning in 19.01s
```

## Safety answers, English and Spanish, and the fallback proof (full live suite on Flash-Lite)

```
Safety answer 'Yes, I smell burning.' -> danger_reported=True
  [{'danger_reported': True, 'details': 'Yes, I smell burning.'}] -> STOPPED
Safety answer 'Sí, huele a quemado.' -> danger_reported=True
  [{'danger_reported': True, 'details': 'Sí, huele a quemado.'}] -> STOPPED
Safety answer "No, I don't smell anything." -> danger_reported=False
  [{'details': "No, I don't smell anything.", 'danger_reported': False}] -> MANUAL
Safety answer 'No, no huele a nada.' -> danger_reported=False
  [{'danger_reported': False, 'details': 'No, no huele a nada.', 'session_id': 'r-ab371cb3'}] -> MANUAL
Fallback proof: invalid Gemini key, Groq answers
  2. [groq:openai/gpt-oss-120b] Take your time. Let me know if you notice any burning smell, smoke, sparks, or water near the power cord. (Waiting for your safety check response.)
```

Result of that full run: 7 passed, 1 failed. The failure was scenario A at its last two turns: on "next" the
model called `report_result(fixed)`; the engine refused (it asks "did it work?" first, nothing was recorded),
but the model congratulated the user anyway, then skipped `report_result` on "It drains now!". The engine
held; the bridge now speaks the engine's question after such a refusal. Scenario A had passed in the run above.

## Ollama (qwen3:8b, local, no quota)

- Scenario C and the four safety answers: 5 of 5 passed, 30 to 34 s per turn on a busy 16 GB Mac.
- Scenario B: got through turns 1 to 3, then stalled at turn 4 (the model called `quick_checks` instead of
  `diagnose`). An earlier run got through 12 of 15 turns at 7 to 15 s each before the model answered the
  "done" turn without a tool call. Scenario A on Ollama was not completed (a run was lost when the Ollama
  server restarted mid-run).

## Gemini quota

- `gemini-3.5-flash`: 20 requests a day (spent after about 10 turns).
- `gemini-3.5-flash-lite`: 500 requests a day. It served all runs above (several full A and B runs, C, the
  safety answers) with one transient 429, then reported "Please retry in 1h22m" on 2026-10-23.
