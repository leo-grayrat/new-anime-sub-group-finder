import asyncio
import base64

import httpx
from fastapi.testclient import TestClient

from fansub_finder.app import create_app
from fansub_finder.config import Config
from fansub_finder.models import Anime
from fansub_finder.monitor import enrich_bgm
from fansub_finder.network import Network

PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII="
)


def test_cover_fetches_metadata_and_image_then_survives_restart_offline(tmp_path):
    requested = []

    def upstream(request):
        requested.append(str(request.url))
        if request.url.host == "api.bgm.tv":
            return httpx.Response(
                200, json={"images": {"common": "https://lain.bgm.tv/pic/cover/c/test.png"}}
            )
        return httpx.Response(200, content=PNG, headers={"Content-Type": "image/png"})

    config = Config(proxy="", data_dir=str(tmp_path))
    app = create_app(config, start_monitor=False)
    original_net = app.state.monitor.net
    app.state.monitor.net = Network("", transport=httpx.MockTransport(upstream), interval=0)
    with TestClient(app) as client:
        store = app.state.monitor.store
        store.upsert_anime(Anime(id="bgm:1", bgm_id=1, title="封面测试", premiere="2026-10-01"))
        response = client.get("/api/anime/bgm:1/cover")
        assert response.status_code == 200
        assert response.content == PNG
        assert response.headers["content-type"] == "image/png"
        assert "max-age=" in response.headers["cache-control"]
        assert client.get("/api/anime/bgm:1/cover").content == PNG
        assert requested == ["https://api.bgm.tv/v0/subjects/1", "https://lain.bgm.tv/pic/cover/c/test.png"]
        assert store.anime("bgm:1").title == "封面测试"
    # The default client has never made a request; dispose it without leaving a second pool.
    asyncio.run(original_net.close())
    app = create_app(config, start_monitor=False)
    with TestClient(app) as client:
        assert client.get("/api/anime/bgm:1/cover").content == PNG
        assert client.get("/api/anime/unknown/cover").status_code == 404


def test_failed_cover_preserves_anime_queries_and_rejects_non_images(tmp_path):
    requests = []

    def upstream(request):
        requests.append(request.url.host)
        if request.url.host == "api.bgm.tv":
            return httpx.Response(
                200, json={"images": {"common": "https://lain.bgm.tv/pic/cover/c/test.jpg"}}
            )
        return httpx.Response(200, text="<html>upstream failed</html>", headers={"Content-Type": "text/html"})

    app = create_app(Config(proxy="", data_dir=str(tmp_path)), start_monitor=False)
    original_net = app.state.monitor.net
    app.state.monitor.net = Network("", transport=httpx.MockTransport(upstream), interval=0)
    with TestClient(app) as client:
        app.state.monitor.store.upsert_anime(
            Anime(id="bgm:1", bgm_id=1, title="封面测试", premiere="2026-10-01")
        )
        assert client.get("/api/anime/bgm:1/cover").status_code == 404
        assert requests == ["api.bgm.tv", "lain.bgm.tv"]
        assert client.get("/api/anime/bgm:1/cover").status_code == 404
        assert len(requests) == 2
        assert client.get("/api/anime").json()["items"][0]["title"] == "封面测试"
    asyncio.run(original_net.close())


def test_catalog_cover_survives_catalogs_without_images(tmp_path):
    app = create_app(Config(proxy="", data_dir=str(tmp_path)), start_monitor=False)
    with TestClient(app) as client:
        anime = Anime(id="bgm:1", bgm_id=1, title="封面测试", premiere="2026-10-01")
        enrich_bgm(anime, {"images": {"common": "https://lain.bgm.tv/pic/cover/c/test.jpg"}}, {})
        app.state.monitor.store.upsert_anime(anime)
        app.state.monitor.store.upsert_anime(Anime(id="bgm:1", title="封面测试"))
        assert (
            client.get("/api/anime").json()["items"][0]["cover_url"]
            == "https://lain.bgm.tv/pic/cover/c/test.jpg"
        )
