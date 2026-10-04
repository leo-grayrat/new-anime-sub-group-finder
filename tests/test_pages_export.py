import json

from fansub_finder.config import Config
from fansub_finder.models import Anime, Release
from fansub_finder.monitor import Monitor
from fansub_finder.store import Store


async def test_pages_export_is_read_only_relative_and_contains_current_grouped_data(tmp_path):
    from fansub_finder.pages_export import export_site

    config = Config(proxy="http://127.0.0.1:7897", data_dir=str(tmp_path / "private-data"))
    store = Store(tmp_path / "private-data" / "finder.sqlite")
    monitor = Monitor(config, store)
    cover = "https://lain.bgm.tv/pic/cover/l/d3/99/622288_nmbC3.jpg"
    store.upsert_anime(Anime(id="bgm:1", title="新番", premiere="2026-10-01", cover_url=cover))
    for group in ["中文组", "ANi"]:
        store.ingest(
            Release(
                source="anibt",
                source_id=group,
                anime_id="bgm:1",
                group=group,
                title=f"[{group}] 新番 [01]",
                published_at="2026-10-02T00:00:00Z",
            ),
            monitor.rules,
            baseline=True,
        )
    try:
        output = tmp_path / "site"
        await export_site(monitor, output)
        html = (output / "index.html").read_text(encoding="utf-8")
        assert 'name="finder-mode" content="static"' in html
        assert 'href="static/' in html and 'src="static/' in html
        assert 'href="/static/' not in html and 'src="/static/' not in html
        assert (output / "static/vendor/bangumi-r771.css").is_file()
        data = json.loads((output / "data.json").read_text(encoding="utf-8"))
        assert data["blocked"]["items"][0]["group_name"] == "ANi"
        assert data["anime"][0]["title"] == "新番"
        assert data["anime"][0]["cover_url"] == cover
        assert data["blocked"]["items"][0]["animes"][0]["cover_url"] == cover
        assert "covers" not in data
        assert not (output / "covers").exists()
        assert not (tmp_path / "private-data" / "covers").exists()
        assert data["groups"]["bgm:1"][0]["name"] == "中文组"
        assert "7897" not in json.dumps(data)
        assert "private-data" not in json.dumps(data)
        assert not list(output.rglob("*.sqlite"))
        assert not list(output.rglob("config.json"))
    finally:
        await monitor.close()
        store.close()
