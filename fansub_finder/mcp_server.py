import inspect

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations


def create_mcp(provider):
    mcp = FastMCP(
        "新番字幕组发现",
        stateless_http=True,
        json_response=True,
        instructions="查询本机持续采集的三站资源。保留 status 中的过期或失败信息；未命中黑名单不代表已证实原创字幕。",
    )
    read = ToolAnnotations(readOnlyHint=True, destructiveHint=False, idempotentHint=True)

    async def call(name, **kwargs):
        result = provider(name, kwargs)
        return await result if inspect.isawaitable(result) else result

    @mcp.tool(annotations=read)
    async def list_anime(
        season: str | None = None,
        include_continuing: bool = True,
        keyword: str = "",
        scope: str = "active",
        has_groups: bool = False,
    ) -> dict:
        """查询季度番剧及可用组。season 格式 YYYY-01/04/07/10；scope 为 active/current/continuing/uncertain/excluded/all。"""
        return await call(
            "list_anime",
            season=season,
            include_continuing=include_continuing,
            keyword=keyword,
            scope=scope,
            has_groups=has_groups,
        )

    @mcp.tool(annotations=read)
    async def list_groups(anime_id: str, season: str | None = None) -> dict:
        """查询番剧的发布组、集数、来源与 RSS；历史季度下钻请传入与 list_anime 相同的 season。"""
        return await call("list_groups", anime_id=anime_id, season=season)

    @mcp.tool(annotations=read)
    async def list_releases(anime_id: str, group: str | None = None, season: str | None = None) -> dict:
        """列出资源与原站、磁力链接；历史季度下钻请传同一 season，指定 group 可查询该组完整采集历史。"""
        return await call("list_releases", anime_id=anime_id, group=group, season=season)

    @mcp.tool(annotations=read)
    async def list_changes(after: int = 0, since: str | None = None, season: str | None = None) -> dict:
        """查询新出现的番剧与字幕组组合。首次扫描是基线，不逐集提醒；返回 cursor 供下次增量查询。"""
        return await call("list_changes", after=after, since=since, season=season)

    @mcp.tool(annotations=read)
    async def get_status() -> dict:
        """查询各站采集状态、数据过期标记和扫描进度。"""
        return await call("get_status")

    return mcp


def run_stdio(base_url):
    async def provider(name, params):
        paths = {
            "list_anime": "/api/anime",
            "list_groups": "/api/anime/{anime_id}/groups",
            "list_releases": "/api/anime/{anime_id}/releases",
            "list_changes": "/api/changes",
            "get_status": "/api/status",
        }
        path = paths[name]
        if "anime_id" in params:
            from urllib.parse import quote

            path = path.format(anime_id=quote(params.pop("anime_id"), safe=""))
        params = {k: str(v).lower() if isinstance(v, bool) else v for k, v in params.items() if v is not None}
        try:
            async with httpx.AsyncClient(trust_env=False, timeout=30) as client:
                r = await client.get(base_url.rstrip("/") + path, params=params)
                r.raise_for_status()
                return r.json()
        except httpx.HTTPError as e:
            raise RuntimeError(f"无法查询常驻服务，请先启动网页服务：{base_url}；{e}") from e

    create_mcp(provider).run(transport="stdio")
