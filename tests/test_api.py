from fastapi.testclient import TestClient

from fansub_finder.app import create_app
from fansub_finder.config import Config
from fansub_finder.models import Anime, Release
from fansub_finder.rules import Rules


def test_queries_and_settings_reclassification_do_not_create_changes(tmp_path):
    app = create_app(
        Config(proxy="", data_dir=str(tmp_path)), config_path=tmp_path / "config.json", start_monitor=False
    )
    with TestClient(app) as client:
        store = app.state.monitor.store
        store.upsert_anime(Anime(id="bgm:1", title="新番", premiere="2026-10-01"))
        store.ingest(
            Release(source="anibt", source_id="1", anime_id="bgm:1", group="好组", title="[好组] 新番 [01]"),
            Rules(),
            baseline=True,
        )
        assert client.get("/api/anime").json()["items"][0]["group_count"] == 1
        assert client.get("/api/anime/bgm:1/groups").json()["items"][0]["episodes"] == ["1"]
        assert client.get("/").status_code == 200
        cfg = client.get("/api/config").json()
        cfg["groups"] += ["好组"]
        assert client.put("/api/config", json=cfg).status_code == 200
        assert client.get("/api/anime/bgm:1/groups").json()["items"] == []
        assert len(client.get("/api/blocked").json()["items"]) == 1
        cfg["groups"].remove("好组")
        client.put("/api/config", json=cfg)
        assert client.get("/api/changes").json()["items"] == []
        assert client.put("/api/config", json={**cfg, "season": "bad"}).status_code == 422


def test_cross_origin_mutation_rejected(tmp_path):
    app = create_app(Config(proxy="", data_dir=str(tmp_path)), start_monitor=False)
    with TestClient(app) as client:
        response = client.post("/api/scan", headers={"Origin": "https://untrusted.example"})
        assert response.status_code == 403


def test_restart_applies_configuration_to_persisted_resources(tmp_path):
    config = Config(proxy="", data_dir=str(tmp_path))
    first = create_app(config, start_monitor=False)
    with TestClient(first):
        first.state.monitor.store.ingest(
            Release(source="mikan", source_id="1", title="[好组] 测试 - 01", group="好组"),
            Rules(),
            baseline=True,
        )
    second = create_app(config.model_copy(update={"groups": ["好组"]}), start_monitor=False)
    with TestClient(second) as client:
        assert len(client.get("/api/blocked").json()["items"]) == 1


def test_historical_quarter_drilldown_and_review_settings(tmp_path):
    app = create_app(
        Config(proxy="", data_dir=str(tmp_path)), config_path=tmp_path / "config.json", start_monitor=False
    )
    with TestClient(app) as client:
        store = app.state.monitor.store
        store.upsert_anime(Anime(id="bgm:1", title="长篇", override="continuing"))
        store.ingest(
            Release(
                source="anibt",
                source_id="1",
                anime_id="bgm:1",
                group="NEST",
                title="[NEST] 长篇 [01]",
                published_at="2026-07-15",
            ),
            app.state.monitor.rules,
            baseline=True,
        )
        assert client.get("/api/anime/bgm:1/groups", params={"season": "2026-07"}).json()["items"] == []
        cfg = client.get("/api/config").json()
        cfg["review_groups"] = []
        assert client.put("/api/config", json=cfg).status_code == 200
        assert client.get("/api/anime", params={"season": "2026-07"}).json()["items"][0]["group_count"] == 1
        assert (
            client.get("/api/anime/bgm:1/groups", params={"season": "2026-07"}).json()["items"][0]["name"]
            == "NEST"
        )
        assert len(client.get("/api/anime/bgm:1/releases", params={"season": "2026-07"}).json()["items"]) == 1
        assert client.get("/api/anime/bgm:1/groups").json()["items"] == []
        assert client.get("/api/anime/bgm:1/groups", params={"season": "bad"}).status_code == 422
        assert client.get("/api/anime/bgm:1/releases", params={"season": "bad"}).status_code == 422
        assert client.get("/api/changes").json()["items"] == []
