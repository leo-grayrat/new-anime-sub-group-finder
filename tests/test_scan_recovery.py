from fansub_finder.config import Config
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
    await monitor.close()
