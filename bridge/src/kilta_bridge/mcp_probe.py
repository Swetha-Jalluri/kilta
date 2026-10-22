"""A small direct MCP client for health checks and the household lookup."""

from __future__ import annotations

from typing import Any

from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def probe(url: str, *, household: bool = False) -> dict[str, Any]:
    """Initialize, list tools, and optionally read the household. Never raises."""
    try:
        async with streamable_http_client(url) as (read, write, _):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                tools = [t.name for t in (await session.list_tools()).tools]
                info: dict[str, Any] = {
                    "reachable": True,
                    "url": url,
                    "protocol_version": init.protocolVersion,
                    "tools": tools,
                }
                if household:
                    result = await session.call_tool("get_household", {})
                    info["household"] = (
                        (result.structuredContent or {}).get("card", {}).get("household")
                    )
                return info
    except Exception as error:  # noqa: BLE001 - a probe reports, it does not raise
        return {"reachable": False, "url": url, "error": f"{type(error).__name__}: {error}"[:200]}
