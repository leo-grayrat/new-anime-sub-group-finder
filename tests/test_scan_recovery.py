from fansub_finder.config import Config
from fansub_finder.models import Anime
from fansub_finder.monitor import Monitor
from fansub_finder.store import Store


async def test_failed_catalog_cannot_be_cleared_by_successful_recent_feed(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    monitor = Monitor(Config(proxy="", data_dir=str(tmp_path)), store)

    async def failure():
        raise ValueError("目录失败")

    async def noop(*args):
        pass

    monitor.catalog_mikan = failure
    monitor.catalog_anibt = noop
    monitor.catalog_garden = noop
    monitor.catalog_bgm = noop
    monitor.backfill_anibt = noop
    monitor.backfill_garden = noop
    monitor.recent = noop
    await monitor.scan(full=True)
    assert store.get_state("status:mikan")["error"]
    assert not store.get_state("baseline:mikan", False)
    assert store.get_state("baseline:garden", False)
    assert store.get_state("baseline:anibt", False)
    await monitor.close()


async def test_historical_quarter_checks_current_long_running_calendar_subject(tmp_path):
    from unittest.mock import AsyncMock

    store = Store(tmp_path / "db.sqlite")
    monitor = Monitor(Config(proxy="", season="2026-07", data_dir=str(tmp_path)), store)
    monitor.net.json = AsyncMock(
        side_effect=[
            [{"items": [{"type": 2, "id": 899, "name": "长篇", "air_date": "1996-01-08"}]}],
            {"date": "1996-01-08", "total_episodes": 0},
            {
                "total": 3,
                "data": [
                    {"sort": 1, "airdate": "2026-07-01"},
                    {"sort": 2, "airdate": "2026-07-08"},
                    {"sort": 3, "airdate": "2026-07-15"},
                ],
            },
        ]
    )
    await monitor.catalog_bgm()
    from fansub_finder.rules import scope_for

    assert scope_for(store.anime("bgm:899"), "2026-07") == "continuing"
    await monitor.close()


def test_schedule_corrections_replace_old_dates(tmp_path):
    from fansub_finder.monitor import enrich_bgm
    from fansub_finder.rules import scope_for

    store = Store(tmp_path / "db.sqlite")
    for date in ["2026-10-04", "2026-10-11", "2026-10-18"]:
        a = store.anime("bgm:1") or Anime(id="bgm:1", title="尾集", premiere="2026-07-01")
        enrich_bgm(a, {"date": "2026-07-01", "total_episodes": 12}, {"data": [{"sort": 12, "airdate": date}]})
        store.upsert_anime(a)
    assert scope_for(store.anime("bgm:1"), "2026-10") == "excluded"


async def test_manual_scan_requests_cannot_create_two_schedulers(tmp_path):
    import asyncio

    from fansub_finder.app import create_app

    app = create_app(Config(proxy="", data_dir=str(tmp_path)), start_monitor=False)
    monitor = app.state.monitor
    entered = asyncio.Event()
    finish = asyncio.Event()

    async def slow_scan(full=False):
        entered.set()
        await finish.wait()

    monitor.scan = slow_scan
    monitor.task = asyncio.create_task(asyncio.sleep(3600))
    endpoint = next(route.endpoint for route in app.routes if getattr(route, "path", "") == "/api/scan")
    responses = await asyncio.gather(endpoint(), endpoint())
    assert sorted(r["started"] for r in responses) == [False, True]
    await entered.wait()
    await monitor.close()
    monitor.store.close()


async def test_long_running_episode_pagination_reaches_current_quarter(tmp_path):
    from unittest.mock import AsyncMock

    from fansub_finder.rules import scope_for

    store = Store(tmp_path / "db.sqlite")
    monitor = Monitor(Config(proxy="", season="2026-07", data_dir=str(tmp_path)), store)
    monitor.net.json = AsyncMock(
        side_effect=[
            [{"items": [{"type": 2, "id": 899, "name": "长篇", "air_date": "1996-01-08"}]}],
            {"date": "1996-01-08", "total_episodes": 0},
            {"total": 103, "data": [{"sort": i + 1, "airdate": "1996-01-08"} for i in range(100)]},
            {
                "total": 103,
                "data": [
                    {"sort": 101 + i, "airdate": date}
                    for i, date in enumerate(["2026-07-01", "2026-07-08", "2026-07-15"])
                ],
            },
        ]
    )
    await monitor.catalog_bgm()
    assert scope_for(store.anime("bgm:899"), "2026-07") == "continuing"
    assert monitor.net.json.call_args.args[1]["offset"] == 100
    await monitor.close()
    store.close()
