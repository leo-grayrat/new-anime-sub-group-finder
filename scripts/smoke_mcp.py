"""Exercise the real HTTP and stdio MCP transports against a running service."""

import asyncio
import json
import sys
from pathlib import Path

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client

sys.stdout.reconfigure(encoding="utf-8")
url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:18765"
expected = {"list_anime", "list_groups", "list_releases", "list_changes", "get_status"}


async def verify(read, write, label):
    async with ClientSession(read, write) as session:
        await session.initialize()
        tools = await session.list_tools()
        assert {t.name for t in tools.tools} == expected
        assert all(t.annotations.readOnlyHint for t in tools.tools)
        state = await session.call_tool("get_status", {})
        assert not state.isError
        payload = state.structuredContent or json.loads(state.content[0].text)
        assert payload["season"] == "2026-10"
        anime = await session.call_tool("list_anime", {"has_groups": True})
        assert not anime.isError
        data = anime.structuredContent or json.loads(anime.content[0].text)
        if data["items"]:
            aid = data["items"][0]["id"]
            for name in ["list_groups", "list_releases"]:
                result = await session.call_tool(name, {"anime_id": aid})
                assert not result.isError
        changes = await session.call_tool("list_changes", {"after": 0})
        assert not changes.isError
        print(label, "OK", len(data["items"]), "anime", "tools=5")


async def main():
    def factory(**kwargs):
        return httpx.AsyncClient(trust_env=False, **kwargs)

    async with streamablehttp_client(url + "/mcp", httpx_client_factory=factory) as (read, write, _):
        await verify(read, write, "HTTP MCP")
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "fansub_finder", "mcp", "--server", url],
        cwd=str(Path(__file__).resolve().parents[1]),
    )
    async with stdio_client(params) as (read, write):
        await verify(read, write, "STDIO MCP")


asyncio.run(main())
