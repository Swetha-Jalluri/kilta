"""Integration tests: a real server process, a real MCP client, Streamable HTTP."""

import asyncio
import json
import shutil
import socket
import subprocess
import sys
import time
from collections.abc import Awaitable, Callable

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from tests.conftest import REPO_DATA

PROTOCOL_VERSION = "2025-11-25"

EXPECTED_TOOLS = {
    "get_household", "list_appliances", "get_health_card", "identify_appliance", "lookup_orders",
    "find_manual", "search_manual", "safety_check", "start_repair", "get_repair_state",
    "resume_repair", "quick_checks", "diagnose", "next_step", "confirm_gate", "pause_repair",
    "go_back", "report_result", "create_technician_summary", "draft_landlord_message",
    "check_warranty", "build_parts_cart", "share_insight", "get_insights",
}  # fmt: skip


def free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


@pytest.fixture(scope="module")
def server_url(tmp_path_factory):
    data = tmp_path_factory.mktemp("kilta") / "data"
    shutil.copytree(REPO_DATA, data, ignore=shutil.ignore_patterns("sessions", "state"))
    port = free_port()
    proc = subprocess.Popen(
        [sys.executable, "-m", "kilta.server", "--port", str(port)],
        env={"KILTA_DATA_DIR": str(data), "PATH": "/usr/bin:/bin"},
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    deadline = time.time() + 20
    while time.time() < deadline:
        if proc.poll() is not None:
            pytest.fail(f"server exited early:\n{proc.stdout.read()}")
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    else:
        proc.kill()
        pytest.fail("server did not start")
    yield f"http://127.0.0.1:{port}"
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


def with_session(url: str, fn: Callable[[ClientSession], Awaitable]):
    async def run():
        async with streamable_http_client(f"{url}/mcp") as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return await fn(session)

    return asyncio.run(run())


def test_negotiates_exactly_spec_2025_11_25(server_url):
    async def run():
        async with streamable_http_client(f"{server_url}/mcp") as (read, write, _):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                assert init.protocolVersion == PROTOCOL_VERSION
                assert init.serverInfo.name == "Kilta"
                assert init.capabilities.tools is not None

    asyncio.run(run())


def test_lists_every_tool_with_a_description_and_annotations(server_url):
    tools = with_session(server_url, lambda s: s.list_tools()).tools
    assert {t.name for t in tools} == EXPECTED_TOOLS
    for tool in tools:
        assert tool.description and len(tool.description) > 20, tool.name
        assert tool.annotations is not None, tool.name
        assert tool.annotations.openWorldHint is False
    by_name = {t.name: t for t in tools}
    assert by_name["get_household"].annotations.readOnlyHint is True
    assert by_name["next_step"].annotations.readOnlyHint is False
    assert by_name["next_step"].annotations.destructiveHint is False


def test_sse_transport_is_not_served(server_url):
    assert httpx.get(f"{server_url}/sse").status_code == 404


def test_every_tool_returns_content_and_structured_content(server_url):
    async def run(session: ClientSession):
        started = await session.call_tool(
            "start_repair", {"member_id": "priya", "description": "beep"}
        )
        sid = started.structuredContent["session_id"]
        calls = {
            "get_household": {"member_id": "priya"},
            "list_appliances": {},
            "get_health_card": {"appliance_id": "dishwasher"},
            "identify_appliance": {"session_id": sid, "appliance_id": "dishwasher"},
            "lookup_orders": {"consent": True},
            "find_manual": {"session_id": sid},
            "search_manual": {"query": "not draining"},
            "safety_check": {"session_id": sid, "danger_reported": False},
            "start_repair": {"member_id": "lucia", "description": "no hot water"},
            "get_repair_state": {"session_id": sid},
            "resume_repair": {"session_id": sid},
            "quick_checks": {"session_id": sid},
            "diagnose": {"session_id": sid, "error_code": "E24"},
            "next_step": {"session_id": sid},
            "confirm_gate": {"session_id": sid},
            "pause_repair": {"session_id": sid},
            "go_back": {"session_id": sid},
            "report_result": {"session_id": sid, "outcome": "fixed"},
            "create_technician_summary": {"session_id": sid},
            "draft_landlord_message": {"session_id": sid},
            "check_warranty": {"appliance_id": "washer"},
            "build_parts_cart": {"appliance_id": "dishwasher"},
            "share_insight": {"session_id": sid},
            "get_insights": {},
        }
        assert set(calls) == EXPECTED_TOOLS, "add new tools to this test"
        names = {t.name for t in (await session.list_tools()).tools}
        assert names == set(calls)
        for name, args in calls.items():
            result = await session.call_tool(name, args)
            assert result.isError is False, name
            assert result.content and result.content[0].type == "text", name
            assert result.content[0].text.strip(), f"{name}: empty speech"
            assert len(result.content[0].text) < 700, f"{name}: too long to speak"
            structured = result.structuredContent
            assert isinstance(structured, dict), name
            assert isinstance(structured["card"], dict) and structured["card"]["type"], name
            assert "state" in structured and "session_id" in structured, name
            assert isinstance(structured["refused"], bool), name

    with_session(server_url, run)


def test_scenario_a_over_http_enforces_the_gate(server_url):
    async def run(s: ClientSession):
        async def call(name, **args):
            r = await s.call_tool(name, args)
            return r.structuredContent

        sid = (await call("start_repair", member_id="priya", description="it beeps"))["session_id"]
        refused = await call("next_step", session_id=sid)
        assert refused["refused"] and refused["reason"] == "safety_first"
        await call("safety_check", session_id=sid, danger_reported=False)
        await call("identify_appliance", session_id=sid, appliance_type="dishwasher")
        await call("find_manual", session_id=sid)
        await call("quick_checks", session_id=sid)
        diag = await call("diagnose", session_id=sid, error_code="E24")
        assert diag["state"] == "PREPARE" and diag["card"]["source"]["page"] == 18
        step = await call("next_step", session_id=sid)
        assert step["state"] == "STEPS" and step["card"]["gate"]["confirmed"] is False
        blocked = await call("next_step", session_id=sid)
        assert blocked["refused"] and blocked["reason"] == "gate_unconfirmed"
        await call("confirm_gate", session_id=sid)
        step2 = await call("next_step", session_id=sid)
        assert step2["card"]["step_number"] == 2 and not step2["refused"]

    with_session(server_url, run)


def test_danger_over_http_stops_the_repair(server_url):
    async def run(s: ClientSession):
        r = await s.call_tool(
            "start_repair", {"description": "I smell burning from the dishwasher"}
        )
        assert r.structuredContent["state"] == "STOPPED"
        assert r.structuredContent["card"]["type"] == "safety_stop"
        sid = r.structuredContent["session_id"]
        again = await s.call_tool("next_step", {"session_id": sid})
        assert again.structuredContent["reason"] == "stopped"

    with_session(server_url, run)


def test_manual_resource_and_prompt_are_available(server_url):
    async def run(s: ClientSession):
        templates = (await s.list_resource_templates()).resourceTemplates
        assert [t.uriTemplate for t in templates] == ["kilta://manuals/{manual_id}"]
        res = await s.read_resource("kilta://manuals/kelvara-dw300")
        manual = json.loads(res.contents[0].text)
        assert manual["id"] == "kelvara-dw300"
        prompts = (await s.list_prompts()).prompts
        assert [p.name for p in prompts] == ["start-repair"]

    with_session(server_url, run)
