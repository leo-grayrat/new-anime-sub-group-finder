from fastapi.testclient import TestClient

from fansub_finder.app import create_app
from fansub_finder.config import Config
from fansub_finder.models import Anime, Release


def test_blocked_groups_only_include_selected_quarter_and_relevant_anime(tmp_path):
    app = create_app(Config(proxy="", data_dir=str(tmp_path)), start_monitor=False)
    with TestClient(app) as client:
        store = app.state.monitor.store
        for a in [
            Anime(id="bgm:1", bgm_id=1, title="新番甲", premiere="2026-10-01"),
            Anime(id="bgm:2", title="新番乙", premiere="2026-10-02"),
            Anime(id="bgm:3", title="续播", override="continuing"),
            Anime(id="bgm:4", title="旧番", premiere="2026-07-01", end_date="2026-09-20"),
        ]:
            store.upsert_anime(a)
        for source_id, anime_id, group, published in [
            ("1", "bgm:1", "ANi", "2026-10-01T00:00:00Z"),
            ("2", "bgm:2", "ANi", "2026-10-02T00:00:00Z"),
            ("3", "bgm:3", "ANi", "2026-08-01T00:00:00Z"),
            ("4", "bgm:4", "ANi", "2026-10-01T00:00:00Z"),
            ("5", None, "ANi", "2026-10-01T00:00:00Z"),
            ("6", "bgm:1", "ANi", ""),
            ("7", "bgm:3", "Nix-Raws", "2026-10-03T00:00:00Z"),
            ("8", "bgm:3", "Nix-Raw", "2026-09-30T18:00:00Z"),
            ("9", "bgm:3", "Nix-Raws", "2027-01-01T00:00:00Z"),
        ]:
            store.ingest(
                Release(
                    source="anibt",
                    source_id=source_id,
                    anime_id=anime_id,
                    group=group,
                    title=f"[{group}] 测试 [01]",
                    published_at=published,
                ),
                app.state.monitor.rules,
                baseline=True,
            )
        response = client.get("/api/blocked")
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 4
        assert [(g["group_name"], g["anime_count"], g["release_count"]) for g in data["items"]] == [
            ("ANi", 2, 2),
            ("Nix-Raws", 1, 2),
        ]
        assert [a["title"] for a in data["items"][0]["animes"]] == ["新番乙", "新番甲"]
        assert all(a["reasons"] for g in data["items"] for a in g["animes"])
        assert len(store.releases(blocked=True)) == 9
        assert client.get("/api/blocked", params={"season": "bad"}).status_code == 422
        july = client.get("/api/blocked", params={"season": "2026-07"}).json()
        assert july["total"] == 1
        assert july["items"][0]["animes"][0]["title"] == "续播"
