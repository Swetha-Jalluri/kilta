# Golden demo script (DRAFT, will change)

Used for golden conversation tests (bridge) and the video. Expected tool calls are what tests assert.

## Household (data/household.json)
- Renter: true. Landlord contact: "Lakeview Property Management" (fictional).
- Members:
  - Priya: language en, confidence beginner, pace slow.
  - Lucia: language es, confidence some, pace normal.
- Appliances: Kelvara DW-300 dishwasher (kitchen, bought 2024-03-12, past repair: E24 fixed by cleaning filter on 2025-11-02),
  Kelvara WM-500 washer (laundry closet, bought 2023-08-30, no past repairs).
- Orders (simulated Amazon history): both appliances.

## Scenario A: dishwasher E24, fixed at home (speaker: Priya, then Lucia)
1. "Hey Alexa, connect me to Kilta." -> greeting. Tools: get_household
2. "My dishwasher is beeping and there's water at the bottom." -> empathy + safety question. Tools: start_repair, safety_check
3. "No, nothing like that." -> confirms dishwasher. Tools: safety_check(clear), identify_appliance
4. "Yes." -> manual found, quick check: door latched? Tools: find_manual, quick_checks
5. "It's shut. The screen says E24." -> E24 = not draining, filter most likely, p.18, 15 min, towel and soft brush. Tools: diagnose
6. "Okay, ready." -> Step 1, unplug, waits. Tools: next_step
7. "Next." (without confirming) -> engine refuses: needs unplug confirmation. Tools: next_step (refused)
8. "It's unplugged." -> Step 2. Tools: confirm_gate, next_step
9. Switch speaker to Lucia: "Puedes decirlo en español?" -> repeats step in Spanish, panel labels stay English.
10. "Espera, alguien está en la puerta." -> paused at current step. Tools: pause_repair
11. (later) "Kilta, sigamos." -> "We stopped at step 3" in Spanish. Tools: get_repair_state, resume
12. ... steps to 8, "It drains now!" -> celebration, health card updated, repeat-problem note (2nd E24), offer anonymous sharing. Tools: report_result(fixed), get_health_card
13. "Sure, share it." -> consent recorded. Tools: share_insight

## Scenario B: washer E31 after filter clean, renter handoff (speaker: Priya)
1. "The washer says E31." -> safety check, identify, manual p.25, pump filter first.
2. After filter steps, "It still says E31." -> technician only. Renter -> offer landlord message.
   Tools: report_result(not_fixed), draft_landlord_message
3. Card shows landlord message in English with model, code, steps tried, results.

## Scenario C (negative): danger
"I smell burning from the dishwasher." -> stop, unplug only if safe, leave area if smoke, call professional. No steps offered.
Tools: safety_check(danger). Engine state STOPPED.
