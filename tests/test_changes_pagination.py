from fansub_finder.config import Config
from fansub_finder.models import Anime
from fansub_finder.monitor import Monitor
from fansub_finder.service import QueryService
from fansub_finder.store import Store


async def test_change_cursor_only_advances_through_returned_page(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    store.upsert_anime(Anime(id="bgm:1", title="测试", premiere="2026-10-01"))
    with store.db:
        store.db.executemany(
            "INSERT INTO changes(anime_id,group_id,group_name,discovered_at) VALUES(?,?,?,?)",
            [("bgm:1", str(i), str(i), "2026-10-04T00:00:00+00:00") for i in range(501)],
        )
    monitor = Monitor(Config(proxy="", data_dir=str(tmp_path)), store)
    query = QueryService(monitor)
    first = query.list_changes()
    assert first["cursor"] == 500
    assert first["has_more"]
    second = query.list_changes(after=first["cursor"])
    assert second["cursor"] == 501
    assert not second["has_more"]
    await monitor.close()
