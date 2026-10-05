from datetime import datetime, timezone

from fastapi.testclient import TestClient

from fansub_finder.app import create_app
from fansub_finder.config import Config
from fansub_finder.models import Anime, Release
from fansub_finder.rules import Rules


def freeze_time(monkeypatch, value):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime.fromisoformat(value).astimezone(tz or timezone.utc)

    monkeypatch.setattr("fansub_finder.service.datetime", Clock)


def test_recent_updates_include_baseline_and_existing_groups_but_exclude_old_and_blocked(
    tmp_path, monkeypatch
):
    freeze_time(monkeypatch, "2026-10-04T12:00:00+00:00")
    app = create_app(Config(proxy="", data_dir=str(tmp_path)), start_monitor=False)
    with TestClient(app) as client:
        store = app.state.monitor.store
        store.upsert_anime(Anime(id="bgm:1", title="新番", premiere="2026-10-01"))
        store.upsert_anime(Anime(id="bgm:2", title="已完结", premiere="2026-07-01", end_date="2026-09-20"))
        store.upsert_anime(Anime(id="bgm:3", title="续播", override="continuing"))
        fixtures = [
            ("1", "bgm:1", "中文组", "01", "2026-10-02T12:00:00Z", "a"),
            ("2", "bgm:1", "中文组", "02", "2026-10-04T10:00:00Z", "b"),
            ("3", "bgm:1", "中文组", "03", "2026-10-04T19:00:00+08:00", "c"),
            ("4", "bgm:1", "另一组", "01", "2026-10-04T09:00:00Z", "d"),
            ("5", "bgm:1", "ANi", "01", "2026-10-04T11:00:00Z", "e"),
            ("6", "bgm:2", "中文组", "12", "2026-10-04T11:00:00Z", "f"),
            ("7", None, "中文组", "01", "2026-10-04T11:00:00Z", "1"),
            ("8", "bgm:1", "中文组", "04", "", "2"),
            ("9", "bgm:1", "中文组", "05", "bad-date", "3"),
            ("10", "bgm:3", "中文组", "14", "2026-10-04T08:00:00", "4"),
        ]
        for source_id, anime_id, group, episode, published, hash_char in fixtures:
            store.ingest(
                Release(
                    source="anibt",
                    source_id=source_id,
                    anime_id=anime_id,
                    group=group,
                    title=f"[{group}] 新番 [{episode}]",
                    published_at=published,
                    magnet=f"magnet:?xt=urn:btih:{hash_char * 40}",
                ),
                app.state.monitor.rules,
                baseline=True,
            )
        store.ingest(
            Release(
                source="mikan",
                source_id="mirror",
                anime_id="bgm:1",
                group="中文组",
                title="[中文组] 新番 [02]",
                published_at="2026-10-04T10:00:00Z",
                magnet=f"magnet:?xt=urn:btih:{'b' * 40}",
            ),
            app.state.monitor.rules,
            baseline=True,
        )
        response = client.get("/api/updates")
        assert response.status_code == 200
        data = response.json()
        assert [(i["anime_title"], i["group_name"], i["episodes"]) for i in data["items"]] == [
            ("新番", "中文组", ["2", "3"]),
            ("新番", "另一组", ["1"]),
            ("续播", "中文组", ["14"]),
        ]
        assert data["items"][0]["updated_at"] == "2026-10-04T11:00:00+00:00"
        assert len(data["items"][0]["releases"]) == 2
        assert len(next(r for r in data["items"][0]["releases"] if r["episodes"] == ["2"])["origins"]) == 2
        assert data["window_start"] == "2026-10-03T12:00:00+00:00"
        assert data["status"]["season"] == "2026-10"
        assert client.get("/api/changes").json()["items"] == []
        store.reclassify(Rules(groups=[*app.state.monitor.config.groups, "中文组"]))
        assert [i["group_name"] for i in client.get("/api/updates").json()["items"]] == ["另一组"]


def test_recent_updates_roll_with_time_and_do_not_treat_rescans_as_publications(tmp_path, monkeypatch):
    freeze_time(monkeypatch, "2026-10-04T12:00:00+00:00")
    app = create_app(Config(proxy="", data_dir=str(tmp_path)), start_monitor=False)
    with TestClient(app) as client:
        store = app.state.monitor.store
        store.upsert_anime(Anime(id="bgm:1", title="新番", premiere="2026-10-01"))
        for source_id, published in [("1", "2026-10-03T12:00:00Z"), ("2", "2026-10-04T12:00:01Z")]:
            store.ingest(
                Release(
                    source="anibt",
                    source_id=source_id,
                    anime_id="bgm:1",
                    group="中文组",
                    title=f"[中文组] 新番 [0{source_id}]",
                    published_at=published,
                ),
                app.state.monitor.rules,
                baseline=True,
            )
        response = client.get("/api/updates")
        assert response.status_code == 200
        assert response.json()["items"][0]["episodes"] == ["1"]
        freeze_time(monkeypatch, "2026-10-05T12:00:00+00:00")
        assert client.get("/api/updates").json()["items"][0]["episodes"] == ["2"]
        freeze_time(monkeypatch, "2026-10-06T12:00:00+00:00")
        store.ingest(
            Release(
                source="anibt",
                source_id="1",
                anime_id="bgm:1",
                group="中文组",
                title="[中文组] 新番 [01]",
                published_at="2026-10-03T12:00:00Z",
            ),
            app.state.monitor.rules,
        )
        assert client.get("/api/updates").json()["items"] == []
        assert client.get("/api/updates", params={"season": "bad"}).status_code == 422


def test_green_tea_known_name_aliases_merge_updates(tmp_path, monkeypatch):
    freeze_time(monkeypatch, "2026-10-05T06:00:00+00:00")
    app = create_app(Config(proxy="", data_dir=str(tmp_path)), start_monitor=False)
    with TestClient(app) as client:
        store = app.state.monitor.store
        store.upsert_anime(Anime(id="bgm:1", title="药屋", premiere="2026-10-01"))
        for i, name in enumerate(["绿茶字幕组", "綠茶字幕組", "绿茶字幕組"]):
            store.ingest(
                Release(
                    source="anibt",
                    source_id=str(i),
                    anime_id="bgm:1",
                    group=name,
                    title=f"[{name}] 药屋 - 49 [CHS]",
                    languages=["CHS"],
                    published_at="2026-10-05T04:00:00Z",
                ),
                Rules(),
                baseline=True,
            )
        updates = client.get("/api/updates").json()["items"]
        assert len(updates) == 1
        assert updates[0]["group_id"] == "绿茶字幕组"
        assert updates[0]["release_count"] == 3
        assert len(client.get("/api/anime/bgm:1/groups").json()["items"]) == 1
