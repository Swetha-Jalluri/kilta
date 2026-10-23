# Kilta tools by repair state

State machine: SAFETY_CHECK -> IDENTIFY -> MANUAL -> QUICK_CHECKS -> DIAGNOSE -> PREPARE -> STEPS
(-> PAUSED) -> VERIFY -> FIXED, with STOPPED (danger), SAFETY_RECHECK (danger words in free text)
and HANDOFF (technician, landlord). Every tool returns a short speakable `content` and a
`structuredContent` card. Refusals are normal results with `refused: true` and a `reason`.

| State | Tools to use |
|---|---|
| any | `get_repair_state`, `safety_check` (the only way to report danger), `get_household` |
| no repair yet | `start_repair`, `list_appliances`, `lookup_orders`, `search_manual`, `get_health_card`, `check_warranty`, `get_insights` |
| SAFETY_CHECK / SAFETY_RECHECK | `safety_check` only (explicit boolean) |
| IDENTIFY | `identify_appliance`, `lookup_orders`, `list_appliances` |
| MANUAL | `find_manual` (returns the quick checks), `identify_appliance` to correct |
| QUICK_CHECKS / DIAGNOSE | `diagnose` (error code), `quick_checks` (re-show, or report a setting fixed it) |
| PREPARE | `next_step` (starts step 1), `diagnose` |
| STEPS | `next_step` (`repeat=true` to say it again), `confirm_gate`, `pause_repair`, `go_back`, `report_result` |
| PAUSED | `resume_repair`, `report_result` |
| VERIFY | `report_result` (`outcome`: `fixed` or `not_fixed`), `go_back` |
| FIXED | `share_insight` (consent), `get_health_card`, `build_parts_cart` (needs explicit confirmation) |
| HANDOFF / STOPPED | `create_technician_summary`, `draft_landlord_message` (renters), `check_warranty` |

Resource `kilta://manuals/{manual_id}` has the manual's sticker location, quick checks and error codes
with page numbers (never the step-by-step text). Prompt `start-repair` is a ready-made entry prompt.
