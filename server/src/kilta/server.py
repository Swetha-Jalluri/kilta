"""Kilta MCP server: MCP spec 2025-11-25 over Streamable HTTP, at /mcp.

Tools are thin wrappers. The repair engine owns every rule; the model only phrases things.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Annotated

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import Field

from .data import DataStore
from .engine import Engine
from .models import Outcome

DEFAULT_PORT = 8765

INSTRUCTIONS = """\
Kilta is a warm repair friend for home appliances. Follow this order: start_repair, then
safety_check, identify_appliance, find_manual, quick_checks, diagnose, next_step (with
confirm_gate when a step has a safety gate). Never skip the safety check. If the engine refuses a
call, say what it says; do not work around it. Technician-only work goes to a handoff.
"""

SessionId = Annotated[
    str | None,
    Field(description="Repair session id from start_repair. Leave out to use the active repair."),
]

READ_ONLY = ToolAnnotations(readOnlyHint=True, openWorldHint=False)
WRITES = ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=False)
WRITES_IDEMPOTENT = ToolAnnotations(
    readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False
)


def as_result(outcome: Outcome) -> CallToolResult:
    """Speakable `content` plus `structuredContent` for the card. Refusals are normal results
    (isError stays false) so the host can speak the explanation."""
    return CallToolResult(
        content=[TextContent(type="text", text=outcome.say)],
        structuredContent=outcome.structured(),
    )


def create_server(
    data_dir: Path | None = None, host: str = "127.0.0.1", port: int = DEFAULT_PORT
) -> FastMCP:
    store = DataStore(data_dir)
    engine = Engine(store)
    svc = engine.services

    allowed_hosts = [h for h in os.environ.get("KILTA_ALLOWED_HOSTS", "").split(",") if h]
    security = None
    if host in ("127.0.0.1", "localhost", "::1") or allowed_hosts:
        security = TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*", *allowed_hosts],
            allowed_origins=[
                "http://127.0.0.1:*",
                "http://localhost:*",
                "http://[::1]:*",
                *[f"https://{h}" for h in allowed_hosts],
            ],
        )
    mcp = FastMCP(
        "Kilta",
        instructions=INSTRUCTIONS,
        host=host,
        port=port,
        streamable_http_path="/mcp",
        transport_security=security,
    )

    # --- household and appliances ---------------------------------------------------------

    @mcp.tool(annotations=READ_ONLY)
    def get_household(
        member_id: Annotated[
            str | None, Field(description="Who is speaking: priya or lucia. Leave out if unknown.")
        ] = None,
    ) -> CallToolResult:
        """Greet the speaker and return the household: members with their language and
        confidence, whether they rent, and the appliances Kilta knows about. Call this first."""
        return as_result(svc.get_household(member_id))

    @mcp.tool(annotations=READ_ONLY)
    def list_appliances() -> CallToolResult:
        """List the household's appliances with room, model code and repair count."""
        return as_result(svc.list_appliances())

    @mcp.tool(annotations=READ_ONLY)
    def get_health_card(
        appliance_id: Annotated[
            str, Field(description="Appliance id, for example dishwasher or washer.")
        ],
    ) -> CallToolResult:
        """Show an appliance's health card: purchase date, repair history, repeat problems and
        an estimated warranty status."""
        return as_result(svc.get_health_card(appliance_id))

    @mcp.tool(annotations=WRITES_IDEMPOTENT)
    def identify_appliance(
        session_id: SessionId = None,
        appliance_id: Annotated[str | None, Field(description="Known appliance id.")] = None,
        model_code: Annotated[
            str | None,
            Field(description="Model code read from the sticker, for example DW-300-K7S2."),
        ] = None,
        appliance_type: Annotated[
            str | None, Field(description="What the user called it: dishwasher or washer.")
        ] = None,
    ) -> CallToolResult:
        """Work out which appliance is broken, from its id, a spoken model code or its type. Only
        works after the safety check is clear. If it is ambiguous it asks which one."""
        return as_result(
            engine.identify_appliance(session_id, appliance_id, model_code, appliance_type)
        )

    @mcp.tool(annotations=READ_ONLY)
    def lookup_orders(
        consent: Annotated[
            bool,
            Field(
                description="True only if the user agreed to a look through their order history."
            ),
        ] = False,
    ) -> CallToolResult:
        """Simulated order history, appliances only. Needs the user's permission first. Fictional
        data, not connected to any store."""
        return as_result(svc.lookup_orders(consent))

    # --- manuals --------------------------------------------------------------------------

    @mcp.tool(annotations=WRITES_IDEMPOTENT)
    def find_manual(
        session_id: SessionId = None,
        manual_id: Annotated[
            str | None, Field(description="Manual id to confirm, for example kelvara-dw300.")
        ] = None,
    ) -> CallToolResult:
        """Confirm the right manual for the identified appliance, with where the model sticker is
        and the manual sections with page numbers. Moves the repair on to the quick checks."""
        return as_result(engine.find_manual(session_id, manual_id))

    @mcp.tool(annotations=READ_ONLY)
    def search_manual(
        query: Annotated[str, Field(description="What to look for, for example 'not draining'.")],
        appliance_id: Annotated[str | None, Field(description="Limit to this appliance.")] = None,
    ) -> CallToolResult:
        """Search the manuals. Returns matching sections with page numbers, never step-by-step
        instructions; those only come through the repair flow after the safety check."""
        return as_result(svc.search_manual(query, appliance_id=appliance_id))

    # --- safety and repair flow ------------------------------------------------------------

    @mcp.tool(annotations=WRITES)
    def start_repair(
        member_id: Annotated[
            str | None, Field(description="Who is speaking: priya or lucia.")
        ] = None,
        description: Annotated[
            str, Field(description="What the user said is wrong, in their words.")
        ] = "",
    ) -> CallToolResult:
        """Start a new repair session and get the safety question to ask first. If the description
        mentions burning, smoke, sparks, gas or shock, the repair is stopped straight away."""
        return as_result(engine.start_repair(member_id, description))

    @mcp.tool(annotations=WRITES_IDEMPOTENT)
    def safety_check(
        danger_reported: Annotated[
            bool,
            Field(
                description="Required, no default. True if the user reports burning, gas, "
                "smoke, sparks, shock or similar; False only if they said none of those."
            ),
        ],
        session_id: SessionId = None,
        details: Annotated[str, Field(description="What the user said, in their words.")] = "",
    ) -> CallToolResult:
        """Record the answer to the safety question. Danger stops the repair and returns stop
        instructions; all clear unlocks the next step. Can be called again at any point if danger
        appears mid-repair."""
        return as_result(engine.safety_check(session_id, danger_reported, details))

    @mcp.tool(annotations=READ_ONLY)
    def get_repair_state(session_id: SessionId = None) -> CallToolResult:
        """Where the repair stands: state, current step, and what to say next. Use it to resume
        a repair that was paused or left earlier."""
        return as_result(engine.get_repair_state(session_id))

    @mcp.tool(annotations=WRITES_IDEMPOTENT)
    def resume_repair(session_id: SessionId = None) -> CallToolResult:
        """Resume a paused repair at the step where it stopped. Safety gates already passed are
        asked again, because things may have changed while the user was away."""
        return as_result(engine.resume_repair(session_id))

    @mcp.tool(annotations=WRITES_IDEMPOTENT)
    def quick_checks(
        session_id: SessionId = None,
        setting_fixed: Annotated[
            bool | None,
            Field(
                description="Leave out to show the checks. True if one of them fixed it, "
                "False if none did."
            ),
        ] = None,
        note: Annotated[str, Field(description="Which setting was the cause, if one was.")] = "",
    ) -> CallToolResult:
        """The simple checks to try before any tools (latched door, delay start, child lock and
        similar), with page numbers. Report the outcome with setting_fixed."""
        return as_result(engine.quick_checks(session_id, setting_fixed, note))

    @mcp.tool(annotations=WRITES_IDEMPOTENT)
    def diagnose(
        session_id: SessionId = None,
        error_code: Annotated[
            str | None,
            Field(
                description="Code on the display, for example E24. Read it back to the user first."
            ),
        ] = None,
        symptoms: Annotated[str, Field(description="Symptoms in the user's words.")] = "",
    ) -> CallToolResult:
        """Turn an error code or symptoms into a likely cause, grounded in the manual with a page
        number. Needs the quick checks first. Technician-only problems go to a handoff instead."""
        return as_result(engine.diagnose(session_id, error_code, symptoms))

    @mcp.tool(annotations=WRITES)
    def next_step(
        session_id: SessionId = None,
        repeat: Annotated[bool, Field(description="True to hear the current step again.")] = False,
    ) -> CallToolResult:
        """Give the next repair step, one at a time. Refuses while a safety gate is unconfirmed;
        say what the refusal says and wait for confirm_gate."""
        return as_result(engine.next_step(session_id, repeat))

    @mcp.tool(annotations=WRITES_IDEMPOTENT)
    def confirm_gate(
        confirmed: Annotated[
            bool,
            Field(
                description="Required, no default. True only if the user clearly said the "
                "safety condition is met."
            ),
        ],
        session_id: SessionId = None,
    ) -> CallToolResult:
        """Record that the user confirmed a safety gate, such as 'the dishwasher is unplugged'.
        Never confirm on the user's behalf."""
        return as_result(engine.confirm_gate(session_id, confirmed))

    @mcp.tool(annotations=WRITES_IDEMPOTENT)
    def pause_repair(session_id: SessionId = None) -> CallToolResult:
        """Pause the repair at the current step, for example when the user has to step away."""
        return as_result(engine.pause_repair(session_id))

    @mcp.tool(annotations=WRITES)
    def go_back(session_id: SessionId = None) -> CallToolResult:
        """Go back one step and read it out again, for example when the user missed it or wants to
        redo something. Safety gates already confirmed stay confirmed."""
        return as_result(engine.go_back(session_id))

    @mcp.tool(annotations=WRITES)
    def report_result(
        outcome: Annotated[str, Field(description="'fixed' or 'not_fixed'.")],
        session_id: SessionId = None,
        notes: Annotated[str, Field(description="Anything the user said about the result.")] = "",
    ) -> CallToolResult:
        """Record whether the repair worked. Fixed updates the appliance's health card and notices
        repeat problems. Not fixed tries the next likely cause, or hands off to a technician."""
        if outcome.strip().lower() not in ("fixed", "not_fixed"):
            return as_result(
                Outcome(
                    say="I need to know if it's fixed or not fixed.",
                    card={"type": "invalid_outcome"},
                    refused=True,
                    reason="invalid_outcome",
                    session=engine.store.active_session(),
                )
            )
        return as_result(
            engine.report_result(session_id, outcome.strip().lower() == "fixed", notes)
        )

    # --- handoffs -------------------------------------------------------------------------

    @mcp.tool(annotations=READ_ONLY)
    def create_technician_summary(session_id: SessionId = None) -> CallToolResult:
        """Write an English summary for a technician: appliance, model code, error, what was
        tried and the manual page. Only after a handoff or a safety stop."""
        return as_result(engine.create_technician_summary(session_id))

    @mcp.tool(annotations=READ_ONLY)
    def draft_landlord_message(session_id: SessionId = None) -> CallToolResult:
        """Draft an English message to the landlord asking for a technician. Renters only, and
        only after a handoff or a safety stop."""
        return as_result(engine.draft_landlord_message(session_id))

    # --- simulated services -------------------------------------------------------------------

    @mcp.tool(annotations=READ_ONLY)
    def check_warranty(
        appliance_id: Annotated[str, Field(description="Appliance id, for example dishwasher.")],
    ) -> CallToolResult:
        """Estimate warranty status from the purchase date. An estimate only; fictional terms."""
        return as_result(svc.check_warranty(appliance_id))

    @mcp.tool(annotations=WRITES)
    def build_parts_cart(
        appliance_id: Annotated[str, Field(description="Appliance id, for example dishwasher.")],
        skus: Annotated[
            list[str] | None, Field(description="Part SKUs. Leave out to list parts that fit.")
        ] = None,
        confirm: Annotated[
            bool, Field(description="True only after the user explicitly agreed to the cart.")
        ] = False,
    ) -> CallToolResult:
        """Build a mock parts cart. Without explicit confirmation nothing is created. Simulated:
        nothing is ever bought."""
        return as_result(svc.build_parts_cart(appliance_id, skus or [], confirm))

    @mcp.tool(annotations=WRITES_IDEMPOTENT)
    def share_insight(
        session_id: SessionId = None,
        consent: Annotated[
            bool, Field(description="True only if the user agreed to share anonymously.")
        ] = False,
    ) -> CallToolResult:
        """After a fix, share the appliance model, error code and fix anonymously, with the user's
        consent. Shares no names or addresses."""
        return as_result(engine.share_insight(session_id, consent))

    @mcp.tool(annotations=READ_ONLY)
    def get_insights(
        model: Annotated[
            str | None, Field(description="Appliance model, for example DW-300.")
        ] = None,
    ) -> CallToolResult:
        """Anonymous, aggregated repair trends. Synthetic demo data plus anything shared locally."""
        return as_result(svc.get_insights(model))

    # --- resources and prompts ------------------------------------------------------------------

    @mcp.resource("kilta://manuals/{manual_id}", mime_type="application/json")
    def manual_resource(manual_id: str) -> str:
        """A fictional Kelvara manual as readable JSON: sticker, quick checks and error codes with
        page references. Step-by-step procedures are left out; they only come through the repair
        flow, after the safety check."""
        manual = store.manuals.get(manual_id)
        if manual is None:
            raise ValueError(f"unknown manual: {manual_id}")
        public = manual.model_dump(mode="json", exclude={"procedures", "parts"})
        public["procedures"] = [
            {"id": p.id, "title": p.title, "page": p.source.page, "minutes": p.minutes}
            for p in manual.procedures
        ]
        return json.dumps(public, indent=2)

    @mcp.prompt(name="start-repair")
    def start_repair_prompt(appliance: str = "appliance", problem: str = "") -> str:
        """Entry prompt for hosts that support prompts."""
        said = f" The {appliance}: {problem}." if problem else ""
        return (
            f"Help me fix my {appliance} with Kilta.{said} Start with the safety question, and "
            "go one step at a time."
        )

    return mcp


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Kilta MCP server (Streamable HTTP, /mcp)")
    parser.add_argument("--host", default=os.environ.get("KILTA_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.environ.get("KILTA_PORT", DEFAULT_PORT)))
    args = parser.parse_args(argv)
    create_server(host=args.host, port=args.port).run(transport="streamable-http")


if __name__ == "__main__":
    main()
