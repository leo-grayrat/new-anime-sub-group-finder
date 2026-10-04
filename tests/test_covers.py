from fastapi.testclient import TestClient

from fansub_finder.app import create_app
from fansub_finder.config import Config
from fansub_finder.models import Anime
from fansub_finder.monitor import enrich_bgm

ORIGINAL = "https://lain.bgm.tv/pic/cover/l/d3/99/622288_nmbC3.jpg"
RESIZED = "https://lain.bgm.tv/r/400/pic/cover/l/d3/99/622288_nmbC3.jpg"


def test_existing_cover_links_are_direct_without_fetching_or_disk_cache(tmp_path):
    app = create_app(Config(proxy="", data_dir=str(tmp_path)), start_monitor=False)

    async def unexpected_request(*args, **kwargs):
        raise AssertionError("Cover queries must not download metadata or images")

    app.state.monitor.net.get = unexpected_request
    with TestClient(app) as client:
        store = app.state.monitor.store
        store.upsert_anime(
            Anime(id="bgm:1", bgm_id=1, title="封面测试", premiere="2026-10-01", cover_url=RESIZED)
        )
        assert client.get("/api/anime").json()["items"][0]["cover_url"] == ORIGINAL
        response = client.get("/api/anime/bgm:1/cover", follow_redirects=False)
        assert response.status_code == 302
        assert response.headers["location"] == ORIGINAL
        assert not (tmp_path / "covers").exists()


def test_missing_cover_and_unsafe_url_do_not_redirect(tmp_path):
    app = create_app(Config(proxy="", data_dir=str(tmp_path)), start_monitor=False)
    with TestClient(app) as client:
        store = app.state.monitor.store
        for value in ["", "javascript:alert(1)", "https://lain.bgm.tv.evil.test/image.jpg"]:
            # Replace the record so that a deliberately missing URL stays missing.
            with store.db:
                store.db.execute("DELETE FROM anime WHERE id=?", ("bgm:1",))
            store.upsert_anime(Anime(id="bgm:1", title="封面测试", cover_url=value))
            assert client.get("/api/anime/bgm:1/cover", follow_redirects=False).status_code == 404
        assert client.get("/api/anime/unknown/cover").status_code == 404


def test_catalog_prefers_bangumi_original_and_preserves_it_across_sources(tmp_path):
    app = create_app(Config(proxy="", data_dir=str(tmp_path)), start_monitor=False)
    with TestClient(app) as client:
        anime = Anime(id="bgm:1", bgm_id=1, title="封面测试", premiere="2026-10-01")
        enrich_bgm(anime, {"images": {"large": ORIGINAL, "common": RESIZED}}, {})
        assert anime.cover_url == ORIGINAL
        app.state.monitor.store.upsert_anime(anime)
        app.state.monitor.store.upsert_anime(
            Anime(id="bgm:1", title="封面测试", cover_url="https://r2.anibt.net/anime_covers/test.jpg")
        )
        assert client.get("/api/anime").json()["items"][0]["cover_url"] == ORIGINAL
