import asyncio
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .config import Config, load_config, save_config
from .mcp_server import create_mcp
from .monitor import Monitor
from .network import Network
from .service import QueryService
from .store import Store


class Override(BaseModel):
    value: Literal["current", "continuing", "excluded", "uncertain"] | None = None


def create_app(config=None, config_path="config.json", start_monitor=True):
    config = config or load_config(config_path)
    store = Store(Path(config.data_dir) / "finder.sqlite")
    monitor = Monitor(config, store)
    query = QueryService(monitor)
    mcp = create_mcp(
        lambda name, params: query.status() if name == "get_status" else getattr(query, name)(**params)
    )
    mcp_app = mcp.streamable_http_app()

    @asynccontextmanager
    async def lifespan(app):
        async with mcp.session_manager.run():
            if start_monitor:
                monitor.task = asyncio.create_task(monitor.loop())
            yield
            await monitor.close()
            store.close()

    app = FastAPI(title="新番字幕组发现", lifespan=lifespan)
    app.state.monitor = monitor
    app.state.query = query
    app.state.mcp = mcp
    static = Path(__file__).parent / "static"

    @app.middleware("http")
    async def same_origin_mutations(request: Request, call_next):
        if request.method in ["POST", "PUT", "PATCH", "DELETE"] and request.url.path.startswith("/api/"):
            origin = request.headers.get("origin")
            if origin and urlsplit(origin).netloc != request.headers.get("host"):
                return JSONResponse({"detail": "拒绝跨站修改请求"}, status_code=403)
        return await call_next(request)

    @app.get("/")
    async def index():
        return FileResponse(static / "index.html")

    @app.get("/api/status")
    async def status():
        return query.status()

    @app.get("/api/anime")
    async def list_anime(
        season: str | None = None,
        include_continuing: bool = True,
        keyword: str = "",
        scope: Literal["active", "current", "continuing", "uncertain", "excluded", "all"] = "active",
        has_groups: bool = False,
    ):
        try:
            return query.list_anime(season, include_continuing, keyword, scope, has_groups)
        except ValueError as e:
            raise HTTPException(422, str(e)) from e

    @app.get("/api/anime/{anime_id}/groups")
    async def groups(anime_id: str):
        return query.list_groups(anime_id)

    @app.get("/api/anime/{anime_id}/releases")
    async def releases(anime_id: str, group: str | None = None):
        return query.list_releases(anime_id, group)

    @app.get("/api/changes")
    async def changes(after: int = 0, since: str | None = None, season: str | None = None):
        return query.list_changes(after, since, season)

    @app.get("/api/blocked")
    async def blocked():
        items = store.releases(blocked=True)
        return {**query.envelope(items[:500]), "total": len(items)}

    @app.get("/api/unmatched")
    async def unmatched():
        items = store.releases(unmatched=True)
        return {**query.envelope(items[:500]), "total": len(items)}

    @app.get("/api/config")
    async def get_config():
        return monitor.config.model_dump()

    @app.put("/api/config")
    async def update_config(config: Config):
        if config.data_dir != monitor.config.data_dir:
            raise HTTPException(422, "运行期间不能更换数据目录；请修改配置后重启")
        if monitor.lock.locked():
            raise HTTPException(409, "正在采集，请等待本轮结束后保存设置")
        async with monitor.lock:
            await monitor.net.close()
            save_config(config, config_path)
            monitor.config = config
            monitor.net = Network(config.proxy)
            store.reclassify(monitor.rules)
        return {"ok": True}

    @app.put("/api/anime/{anime_id}/scope")
    async def override(anime_id: str, value: Override):
        try:
            store.set_override(anime_id, value.value)
        except KeyError as e:
            raise HTTPException(404, "番剧不存在") from e
        return {"ok": True}

    @app.post("/api/scan")
    async def scan(full: bool = False):
        async with monitor.scheduler_lock:
            if monitor.scan_requested or monitor.lock.locked():
                return {"started": False, "message": "已有采集任务在运行"}
            monitor.scan_requested = True
            if monitor.task:
                monitor.task.cancel()
                try:
                    await monitor.task
                except asyncio.CancelledError:
                    pass

            async def run_then_loop():
                try:
                    await monitor.scan(full=full)
                finally:
                    monitor.scan_requested = False
                await asyncio.sleep(monitor.config.poll_minutes * 60)
                await monitor.loop()

            monitor.task = asyncio.create_task(run_then_loop())
            return {"started": True}

    app.mount("/static", StaticFiles(directory=static), name="static")
    app.mount("/", mcp_app)
    return app
