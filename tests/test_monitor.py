from fansub_finder.config import Config
from fansub_finder.models import Anime, Release
from fansub_finder.monitor import Monitor, enrich_bgm, match_anime
from fansub_finder.store import Store


def test_alias_matching_does_not_merge_seasons():
    animes = [
        Anime(id="bgm:1", title="测试番", aliases=["Test Anime"]),
        Anime(id="bgm:2", title="测试番 第二季", aliases=["Test Anime Season 2"]),
    ]
    assert match_anime("[好组] 测试番 第二季 [01]", animes) == "bgm:2"
    assert match_anime("[好组] Test Anime Season 2 - 01", animes) == "bgm:2"
    assert match_anime("[好组] Test Anime Season 3 - 01", animes) is None


def test_complete_episode_dates_identify_quarter_tail():
    a = Anime(id="bgm:1", title="测试", premiere="2026-07-01")
    enrich_bgm(
        a,
        {"date": "2026-07-01", "total_episodes": 3},
        {
            "total": 3,
            "data": [
                {"sort": 1, "airdate": "2026-09-20"},
                {"sort": 2, "airdate": "2026-09-27"},
                {"sort": 3, "airdate": "2026-10-04"},
            ],
        },
    )
    assert a.end_date == "2026-10-04"


async def test_failed_source_keeps_previous_records_and_marks_error(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    monitor = Monitor(Config(proxy="", data_dir=str(tmp_path)), store)
    store.set_state("status:mikan", {"last_success": "2026-10-03T00:00:00+00:00"})
    store.ingest(
        Release(source="mikan", source_id="1", group="好组", title="[好组] 测试 - 01"),
        monitor.rules,
        baseline=True,
    )

    async def fail():
        raise ValueError("模拟源站失败")

    await monitor.run_source("mikan", fail)
    status = store.get_state("status:mikan")
    assert status["last_success"] == "2026-10-03T00:00:00+00:00"
    assert status["error"] and status["phase"] == "error"
    assert store.releases()[0]["title"] == "[好组] 测试 - 01"
    await monitor.close()
