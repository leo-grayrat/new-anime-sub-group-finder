from fansub_finder.adapters import parse_release_description
from fansub_finder.config import Config
from fansub_finder.models import Anime, Release
from fansub_finder.monitor import Monitor
from fansub_finder.rules import Rules
from fansub_finder.store import Store


def release(**kwargs):
    return Release(source="anibt", source_id="r", title="[测试组] 测试 - 01", group="测试组", **kwargs)


def test_blacklist_aliases_and_user_flagged_groups():
    for group in ["沸班亚马制作组", "沸班亞馬製作組", "Feibanyama", "Skymoon-Raws", "YAYOI"]:
        assert Rules().check(release().model_copy(update={"group": group}))
    assert not Rules().check(release().model_copy(update={"group": "ANimation"}))


def test_foreign_only_resources_do_not_ban_chinese_releases_from_same_publisher():
    assert Rules().check(release(publisher="geckyzz", languages=["EN", "ID", "JA"]))
    assert not Rules().check(release(publisher="geckyzz", languages=["CHT", "EN"]))
    assert not Rules().check(release(languages=[]))


def test_detail_only_platform_tag_is_blocked_and_sidebars_are_ignored():
    r = release()
    parse_release_description(
        '<nav>CR 官字 无字幕</nav><div class="episode-desc">字幕来源：巴哈姆特</div>', "mikan", r
    )
    assert Rules().check(r)
    safe = release()
    parse_release_description(
        '<aside>CR 官字</aside><div class="episode-desc">本组翻译制作</div>', "mikan", safe
    )
    assert not Rules().check(safe)


def test_subtitle_track_language_is_separate_from_audio():
    r = release()
    parse_release_description(
        '<div class="prose">Audio track: Chinese\nSubtitles:\nEnglish (ASS)\nIndonesian (ASS)\nJapanese (ASS)\nChapters: yes</div>',
        "anibt",
        r,
    )
    assert set(r.languages) == {"EN", "ID", "JA"}
    assert Rules().check(r)


def test_subtitle_notes_and_negated_chinese_are_not_tracks():
    for text in [
        "Subtitles: English (ASS)\nNotes: Chinese audio only, no Chinese subtitles.",
        "Subtitles: English (ASS), no Chinese subtitles\nChapters: yes",
    ]:
        r = release()
        parse_release_description(f'<div class="prose">{text}</div>', "anibt", r)
        assert r.languages == ["EN"]
        assert Rules().check(r)


def test_multisub_is_not_itself_a_blacklist_rule():
    r = release()
    parse_release_description(
        '<div class="topic-nfo">Subtitles (3): English, SRT | Chinese (Simplified), SRT | Chinese (Traditional), SRT\nChapters: Yes</div>',
        "garden",
        r,
    )
    assert {"CHS", "CHT"} <= set(r.languages)
    assert not Rules().check(r)


def test_detail_evidence_survives_sparse_feed_update(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    r = release(url="https://anibt.net/release/r")
    parse_release_description('<div class="prose">字幕来源：[CATCHPLAY+]</div>', "anibt", r)
    store.ingest(r, Rules(), baseline=True)
    store.ingest(release(), Rules(), baseline=True)
    result = store.releases(blocked=True)[0]
    assert "CATCHPLAY+" in result["description"]
    assert result["description_checked_at"]
    assert result["description_url"] == r.url
    assert not store.releases()
    assert not store.changes()
    store.close()


def test_cross_source_chinese_evidence_overrides_incomplete_language_field_only(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    magnet = "magnet:?xt=urn:btih:" + "a" * 40
    store.ingest(release(magnet=magnet, languages=["EN"]), Rules(), baseline=True)
    chinese = release(magnet=magnet, languages=["CHS"]).model_copy(update={"source": "garden"})
    store.ingest(chinese, Rules(), baseline=True)
    assert len(store.releases()) == 1
    assert not store.releases(blocked=True)
    chinese.description = "字幕来源：[CR]"
    store.ingest(chinese, Rules(), baseline=True)
    assert not store.releases()
    assert "已标注字幕语言不含中文" not in store.releases(blocked=True)[0]["reasons"]
    assert not store.changes()
    store.close()


def test_new_chinese_group_discovery_uses_merged_language_evidence(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    store.upsert_anime(Anime(id="bgm:1", title="测试", premiere="2026-10-01"))
    magnet = "magnet:?xt=urn:btih:" + "a" * 40
    store.ingest(release(anime_id="bgm:1", magnet=magnet, languages=["EN"]), Rules(), baseline=True)
    chinese = release(anime_id="bgm:1", magnet=magnet, languages=["CHS"]).model_copy(
        update={"source": "garden", "group": "中文组"}
    )
    store.ingest(chinese, Rules())
    assert [c["group_name"] for c in store.changes()] == ["中文组"]
    store.ingest(chinese, Rules())
    assert len(store.changes()) == 1
    store.close()


async def test_description_backfill_is_bounded_and_keeps_failed_data(tmp_path):
    store = Store(tmp_path / "db.sqlite")
    monitor = Monitor(Config(proxy=""), store)
    store.upsert_anime(Anime(id="bgm:1", title="测试", premiere="2026-10-01"))
    for i in range(30):
        store.ingest(
            release(
                anime_id="bgm:1",
                url=f"https://anibt.net/release/{i}",
                languages=["EN"],
                published_at="2026-10-04",
            ).model_copy(update={"source_id": str(i), "group": f"组{i}"}),
            monitor.rules,
            baseline=True,
        )
    calls = []

    async def text(url):
        calls.append(url)
        if url.endswith("/29"):
            raise TimeoutError("模拟简介超时")
        return '<div class="prose">Subtitles: English (ASS)\nChapters: Yes</div>'

    monitor.net.text = text
    await monitor.inspect_descriptions("anibt")
    assert len(calls) == 25
    assert len(store.releases(blocked=True)) == 30
    assert "模拟简介超时" in store.get_state("details:anibt")["error"]
    assert not store.changes()
    assert sum(bool(r["description_checked_at"]) for r in store.releases(blocked=True)) == 24
    await monitor.close()
    store.close()
