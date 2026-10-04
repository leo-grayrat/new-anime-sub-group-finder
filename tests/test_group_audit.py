from fansub_finder.config import Config
from fansub_finder.models import Anime, Release
from fansub_finder.monitor import Monitor
from fansub_finder.rules import Rules
from fansub_finder.service import QueryService
from fansub_finder.store import Store


def test_insufficiently_documented_group_is_pending_and_can_be_reviewed():
    r = Release(source="anibt", source_id="1", title="[NEST] 番 - 01", group="NEST", languages=["CHS"])
    assert any("待核实" in reason for reason in Rules().check(r))
    assert not Rules(review_groups=[]).check(r)
    assert not Rules().check(r.model_copy(update={"group": "SweetSub", "title": "[SweetSub] 番 - 01"}))
    bucket = r.model_copy(update={"group": "生肉/不明字幕", "title": "未来少年柯南.英文+法文"})
    assert any("待核实" in reason for reason in Rules().check(bucket))
    assert not Rules(review_groups=[]).check(bucket)


async def test_continuing_series_hides_inactive_archival_groups_but_keeps_history(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    monitor = Monitor(Config(proxy=""), store)
    query = QueryService(monitor)
    store.upsert_anime(
        Anime(id="bgm:1", title="长篇", premiere="1996-01-01", on_air=True, override="continuing")
    )
    for sid, group, date, episode in [
        ("1", "历史组", "2020-01-01", "1"),
        ("2", "活跃组", "2026-09-01", "2"),
        ("3", "活跃组", "2026-09-28", "3"),
        ("4", "未来组", "2027-01-01", "4"),
    ]:
        store.ingest(
            Release(
                source="mikan",
                source_id=sid,
                title=f"[{group}] 长篇 - {episode}",
                anime_id="bgm:1",
                group=group,
                published_at=date,
            ),
            Rules(),
            baseline=True,
        )
    groups = query.list_groups("bgm:1")["items"]
    assert [g["name"] for g in groups] == ["活跃组"]
    assert groups[0]["episodes"] == ["2", "3"]
    assert [g["name"] for g in query.list_anime()["items"][0]["groups"]] == ["活跃组"]
    assert {r["group"] for r in query.list_releases("bgm:1")["items"]} == {"活跃组"}
    assert len(store.releases("bgm:1")) == 4
    assert len(query.list_releases("bgm:1", "历史组")["items"]) == 1
    await monitor.close()
    store.close()


async def test_continuing_activity_uses_each_origin_date(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    monitor = Monitor(Config(proxy=""), store)
    query = QueryService(monitor)
    store.upsert_anime(Anime(id="bgm:1", title="长篇", override="continuing"))
    for source, group, published in [
        ("mikan", "历史组", "2020-01-01"),
        ("garden", "活跃组", "2026-10-01"),
    ]:
        store.ingest(
            Release(
                source=source,
                source_id="1",
                title="长篇 - 01",
                anime_id="bgm:1",
                group=group,
                published_at=published,
                magnet="magnet:?xt=urn:btih:" + "a" * 40,
            ),
            Rules(),
            baseline=True,
        )
    groups = query.list_groups("bgm:1")["items"]
    assert [g["name"] for g in groups] == ["活跃组"]
    assert groups[0]["last_published"] == "2026-10-01"
    await monitor.close()
    store.close()
