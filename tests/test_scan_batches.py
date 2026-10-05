import asyncio
import time

from fansub_finder.config import Config
from fansub_finder.models import Anime
from fansub_finder.monitor import Monitor
from fansub_finder.store import Store


async def test_source_deadline_preserves_last_success(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    monitor = Monitor(Config(proxy="", data_dir=str(tmp_path)), store)
    store.set_state("status:anibt", {"last_success": "2026-10-05T00:00:00+00:00"})

    async def stuck():
        await asyncio.Event().wait()

    try:
        assert not await monitor.run_source("anibt", stuck, timeout=0.01)
        status = store.get_state("status:anibt")
        assert status["last_success"] == "2026-10-05T00:00:00+00:00"
        assert status["phase"] == "error" and "超时" in status["error"]
    finally:
        await monitor.close()
        store.close()


async def test_latest_feeds_are_saved_before_slow_catalog(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    monitor = Monitor(Config(proxy="", data_dir=str(tmp_path)), store)
    entered, finish = asyncio.Event(), asyncio.Event()
    calls = []

    async def recent(source, baseline):
        calls.append(source)

    async def noop(*args):
        pass

    async def metadata():
        entered.set()
        await finish.wait()

    monitor.recent = recent
    monitor.catalog_mikan = monitor.catalog_garden = monitor.catalog_anibt = noop
    monitor.catalog_bgm = metadata
    monitor.backfill_garden = monitor.backfill_anibt = noop
    monitor.inspect_descriptions = noop
    task = asyncio.create_task(monitor.scan(full=True))
    try:
        await asyncio.wait_for(entered.wait(), 2)
        assert set(calls) == {"mikan", "garden", "anibt"}
        assert store.get_state("last_scan")
        assert monitor.progress["running"]
    finally:
        finish.set()
        await task
        await monitor.close()
        store.close()


async def test_anibt_daily_backfill_resumes_after_restart(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    config = Config(proxy="", data_dir=str(tmp_path))
    for i in range(12):
        store.upsert_anime(Anime(id=f"bgm:{i + 1}", bgm_id=i + 1, title=f"番{i}", premiere="2026-10-01"))
    calls = []

    async def catalog(url, params):
        calls.append(params["bgmId"])
        return {"ok": True, "data": {"bgmId": params["bgmId"], "groups": []}}

    monitor = Monitor(config, store)
    monitor.net.json = catalog
    try:
        assert await monitor.backfill_anibt(False) is False
        assert len(calls) == 10
        await monitor.close()
        monitor = Monitor(config, store)
        monitor.net.json = catalog
        assert await monitor.backfill_anibt(False) is True
        assert len(calls) == 12 and len(set(calls)) == 12
        assert await monitor.backfill_anibt(False) is True
        assert len(calls) == 12
    finally:
        await monitor.close()
        store.close()


async def test_incomplete_batch_does_not_mark_daily_backfill_finished(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    monitor = Monitor(Config(proxy="", data_dir=str(tmp_path)), store)
    store.set_state("catalog:2026-10", time.time())
    for source in ["mikan", "garden", "anibt"]:
        store.set_state("baseline:" + source, True)

    async def noop(*args):
        pass

    async def pending(*args):
        return False

    monitor.recent = monitor.inspect_descriptions = monitor.catalog_mikan = monitor.backfill_garden = noop
    monitor.backfill_anibt = pending
    try:
        await monitor.scan()
        assert store.get_state("backfill:2026-10:anibt", 0) == 0
        assert store.get_state("status:anibt")["phase"] == "ready"
        assert store.get_state("status:anibt")["last_success"]
        assert not monitor.progress["running"]
    finally:
        await monitor.close()
        store.close()
